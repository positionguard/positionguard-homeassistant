"""Data update coordinator for PositionGuard.

Handles polling the REST API on a fixed interval and caching the result.
All entities read from coordinator.data rather than calling the API directly.
"""
from __future__ import annotations

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
from .const import DEFAULT_SCAN_INTERVAL_SECONDS, DOMAIN

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

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the current data.

        Called every `update_interval`. Raising UpdateFailed marks entities as
        unavailable until the next successful poll.
        """
        try:
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

        except PositionGuardAuthError as err:
            # Raising this specifically triggers HA's reauth flow.
            raise UpdateFailed(f"authentication failed: {err}") from err
        except PositionGuardAPIError as err:
            raise UpdateFailed(f"error fetching data: {err}") from err

    def _should_refresh_areas(self) -> bool:
        """Refresh areas roughly every 10 poll cycles.

        Naive cycle counter — good enough for V1.
        """
        # update_count is incremented by DataUpdateCoordinator automatically
        # after each successful update. We refresh when it's divisible by 10.
        return self.update_count > 0 and (self.update_count % 10 == 0)