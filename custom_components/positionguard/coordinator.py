"""Data update coordinator for PositionGuard.

Handles polling the REST API on a fixed interval and caching the result.
All entities read from coordinator.data rather than calling the API directly.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    PositionGuardAPIError,
    PositionGuardAuthError,
    PositionGuardClient,
)
from .const import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MAX_CONSECUTIVE_FAILURES,
    RETRY_BACKOFF_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class PositionGuardCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the PositionGuard API and exposes cached data to entities.

    coordinator.data shape:
        {
            "groups": {
                "<group_id>": {
                    "info": { id, name, icon, group_type, ... },
                    "members": [ { user_id, nickname, inside, current_area, ... }, ... ],
                    "areas":   [ { id, name, latitude, longitude, radius_meters }, ... ],
                },
                ...
            }
        }

    Entities key into this structure by group_id + user_id / area_id.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: PositionGuardClient,
        group_ids: list[str],
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: the HA instance.
            client: configured PositionGuardClient (pre-auth'd with API key).
            group_ids: the subset of groups the user selected during config flow.
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS),
        )
        self._client = client
        self._group_ids = group_ids
        # Cache group info (rarely changes) so we don't re-fetch every cycle.
        self._group_info_cache: dict[str, dict[str, Any]] = {}
        # Same for areas (also rarely change).
        self._areas_cache: dict[str, list[dict[str, Any]]] = {}
        self._update_cycle = 0
        # Consecutive failed cycles, for transient-failure toleration. Reset to
        # 0 on any success; see _async_update_data / _handle_failed_cycle.
        self._consecutive_failures = 0

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the current data for this poll cycle.

        Called every ``update_interval``. Wraps the actual fetch with a single
        short-backoff retry (absorbs brief edge/tunnel hiccups) and tolerates
        one fully failed cycle by returning the last-known data, so a lone
        transient blip neither flaps entities nor logs an ERROR.

        Failure handling:
          * Auth errors raise immediately (no retry, no toleration) so HA's
            reauth flow starts right away.
          * A transient failure that survives the in-cycle retry is tolerated
            for up to ``MAX_CONSECUTIVE_FAILURES`` cycles, then surfaced.
          * A successful payload — including one where a member has paused
            sharing (``sharing_disabled``) — is returned untouched: toleration
            only reacts to exceptions, never to a valid response.
        """
        self._update_cycle += 1
        try:
            data = await self._fetch_with_retry()
        except PositionGuardAuthError as err:
            # Never retried or tolerated — raising this triggers HA's reauth.
            raise UpdateFailed(f"authentication failed: {err}") from err
        except (PositionGuardAPIError, asyncio.TimeoutError) as err:
            # Transient (network / timeout / 5xx / 429 / 404) and still failing
            # after the retry — tolerate this cycle or surface it.
            return self._handle_failed_cycle(err)

        # Success — clear any failure streak and publish fresh data.
        self._consecutive_failures = 0
        return data

    async def _fetch_with_retry(self) -> dict[str, Any]:
        """Run one fetch, retrying ONCE after a short backoff on transients.

        The retry catches the common case: an edge/tunnel 502, a rate-limit
        blip, a reset connection, or a momentary timeout that is gone a couple
        of seconds later. Auth errors are never retried (a bad key won't fix
        itself); they propagate immediately.
        """
        try:
            return await self._fetch_once()
        except PositionGuardAuthError:
            raise  # bad credentials — surface now, don't waste a retry
        except (PositionGuardAPIError, asyncio.TimeoutError) as err:
            _LOGGER.debug(
                "PositionGuard fetch attempt failed (%s); retrying once in %ss",
                err,
                RETRY_BACKOFF_SECONDS,
            )
            await asyncio.sleep(RETRY_BACKOFF_SECONDS)
            return await self._fetch_once()

    def _handle_failed_cycle(self, err: Exception) -> dict[str, Any]:
        """Tolerate a failed cycle, or surface it once it looks persistent.

        Increments the consecutive-failure counter, then either:
          * returns the last-known ``self.data`` so entities keep their state
            for this cycle (DEBUG-logged only) while under the threshold, or
          * re-raises so HA marks entities unavailable and logs at ERROR.

        Re-raising preserves the existing ERROR wording so any log-watching
        automations keep working: a timeout re-raises as-is (HA logs
        "Timeout fetching positionguard data"); an API error wraps in
        UpdateFailed (HA logs "Error fetching positionguard data: ...").
        """
        self._consecutive_failures += 1

        # Tolerate while under the threshold — but only when we have a previous
        # success to fall back on. On the very first refresh there is no
        # last-known state, so we surface immediately (ConfigEntryNotReady).
        if (
            self._consecutive_failures < MAX_CONSECUTIVE_FAILURES
            and self.data is not None
        ):
            _LOGGER.debug(
                "Transient PositionGuard poll failure %d/%d (%s); keeping "
                "last-known data for this cycle so entities don't flap",
                self._consecutive_failures,
                MAX_CONSECUTIVE_FAILURES,
                err,
            )
            return self.data

        # Persistent (or nothing to fall back on) — surface it.
        if isinstance(err, PositionGuardAPIError):
            raise UpdateFailed(f"error fetching data: {err}") from err
        raise err

    async def _fetch_once(self) -> dict[str, Any]:
        """Perform a single full fetch of all selected groups' data.

        One attempt, no retry/toleration logic — that lives in the callers.
        Raises PositionGuardAuthError / PositionGuardAPIError /
        asyncio.TimeoutError on failure.
        """
        # Refresh the groups list first — catches newly joined groups and
        # also picks up if the user was removed from a selected group.
        all_groups = await self._client.list_groups()
        groups_by_id = {g["id"]: g for g in all_groups}

        # Filter to only the groups the user selected in config flow.
        active_group_ids = [gid for gid in self._group_ids if gid in groups_by_id]

        if not active_group_ids:
            _LOGGER.warning(
                "None of the configured group IDs are still accessible; "
                "user may have left all selected groups"
            )

        result: dict[str, Any] = {"groups": {}}

        for gid in active_group_ids:
            info = groups_by_id[gid]

            # Members update every cycle — this is the main presence data.
            members = await self._client.list_group_members(gid)

            # Areas are cached on first fetch; refresh every 10 cycles to
            # catch new / renamed / removed areas without hammering the API.
            if gid not in self._areas_cache or self._should_refresh_areas():
                self._areas_cache[gid] = await self._client.list_group_areas(gid)

            result["groups"][gid] = {
                "info": info,
                "members": members,
                "areas": self._areas_cache[gid],
            }

        return result

    def _should_refresh_areas(self) -> bool:
        """Refresh areas roughly every 10 poll cycles."""
        return self._update_cycle > 0 and (self._update_cycle % 10 == 0)