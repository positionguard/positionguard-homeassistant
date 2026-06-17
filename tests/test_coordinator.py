"""Tests for the PositionGuard coordinator's transient-failure resilience.

Covers the retry-once + tolerate-one-failed-cycle behavior:

  1. a single transient failure is tolerated (last-known state held, no ERROR)
  2. a sustained failure surfaces (entities unavailable, original wording kept)
  3. an auth error surfaces immediately (never retried or tolerated)
  4. a paused-sharing payload is a normal success (resilience path never engages)
  5. a first-refresh failure surfaces immediately (no last-known state to hold)
"""
from __future__ import annotations

import asyncio
import logging

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.positionguard.api import (
    PositionGuardAPIError,
    PositionGuardAuthError,
)
from custom_components.positionguard.device_tracker import PositionGuardDeviceTracker

from .fixtures_data import (
    FRED_ID,
    GROUP_ID,
    SALLY_ID,
    SCHOOL_AREA_ID,
    make_member,
)

_COORD_LOGGER = "custom_components.positionguard.coordinator"


async def test_single_transient_failure_is_tolerated(coordinator, mock_client, caplog):
    """One fully-failed cycle keeps last-known state: no flap, no ERROR."""
    # Cycle 1: success establishes last-known data.
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    baseline = coordinator.data
    assert baseline is not None
    assert coordinator._consecutive_failures == 0

    # Cycle 2: every fetch attempt fails (both the attempt and its retry).
    mock_client.list_groups.reset_mock()
    mock_client.list_groups.side_effect = PositionGuardAPIError("server error 502")

    with caplog.at_level(logging.DEBUG, logger=_COORD_LOGGER):
        await coordinator.async_refresh()

    # Entities keep their state: success flag stays True, same data object.
    assert coordinator.last_update_success is True
    assert coordinator.data is baseline
    assert coordinator._consecutive_failures == 1
    # Retried once within the cycle (attempt + retry == 2 calls).
    assert mock_client.list_groups.call_count == 2
    # Logged at DEBUG, never ERROR.
    assert "keeping last-known data" in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    # Cycle 3: success again — counter resets.
    mock_client.list_groups.side_effect = None
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert coordinator._consecutive_failures == 0


async def test_sustained_timeout_surfaces_as_timeout(coordinator, mock_client, caplog):
    """Two consecutive timeout cycles -> unavailable; TimeoutError preserved."""
    await coordinator.async_refresh()  # baseline success
    assert coordinator.last_update_success is True

    mock_client.list_groups.side_effect = asyncio.TimeoutError()

    # Cycle 1 (consecutive == 1): tolerated.
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert coordinator._consecutive_failures == 1

    # Cycle 2 (consecutive == 2): surfaces.
    with caplog.at_level(logging.ERROR, logger=_COORD_LOGGER):
        await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert coordinator._consecutive_failures == 2
    # Re-raised as-is (not wrapped), so HA logs the preserved timeout message.
    assert isinstance(coordinator.last_exception, (asyncio.TimeoutError, TimeoutError))
    assert "Timeout fetching positionguard data" in caplog.text


async def test_sustained_api_error_surfaces_as_updatefailed(
    coordinator, mock_client, caplog
):
    """Two consecutive API-error cycles -> unavailable; existing wording kept."""
    await coordinator.async_refresh()  # baseline success
    assert coordinator.last_update_success is True

    mock_client.list_groups.side_effect = PositionGuardAPIError("server error 502")

    await coordinator.async_refresh()  # consecutive == 1, tolerated
    assert coordinator.last_update_success is True
    assert coordinator._consecutive_failures == 1

    with caplog.at_level(logging.ERROR, logger=_COORD_LOGGER):
        await coordinator.async_refresh()  # consecutive == 2, surfaces

    assert coordinator.last_update_success is False
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert "error fetching data: server error 502" in str(coordinator.last_exception)
    assert "Error fetching positionguard data" in caplog.text


async def test_auth_error_surfaces_immediately(coordinator, mock_client):
    """Auth errors are never retried or tolerated, even with tolerable state."""
    await coordinator.async_refresh()  # baseline success (data set, counter 0)
    assert coordinator.last_update_success is True

    mock_client.list_groups.reset_mock()
    mock_client.list_groups.side_effect = PositionGuardAuthError(
        "invalid or revoked API key"
    )

    await coordinator.async_refresh()  # a single auth failure

    # Surfaces on the FIRST failure (contrast with a transient, which is held).
    assert coordinator.last_update_success is False
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert "authentication failed" in str(coordinator.last_exception)
    # Not retried (one call, no backoff retry) and the counter is never consulted.
    assert mock_client.list_groups.call_count == 1
    assert coordinator._consecutive_failures == 0


async def test_paused_sharing_is_normal_success(coordinator, mock_client):
    """A sharing_disabled payload is a valid success; resilience never engages."""
    mock_client.list_group_members.return_value = [
        make_member(FRED_ID, "Fred", inside=False, sharing_disabled=True),
        make_member(SALLY_ID, "Sally", inside=True, area_id=SCHOOL_AREA_ID),
    ]

    await coordinator.async_refresh()

    # Success path: no error, counter zero, single fetch (no retry triggered).
    assert coordinator.last_update_success is True
    assert coordinator._consecutive_failures == 0
    assert mock_client.list_groups.call_count == 1

    # The paused flag passes through untouched in the data.
    members = coordinator.data["groups"][GROUP_ID]["members"]
    fred = next(m for m in members if m["user_id"] == FRED_ID)
    assert fred["sharing_disabled"] is True

    # The EXISTING entity logic (not the resilience path) resolves paused Fred
    # to unavailable while active Sally stays available.
    fred_tracker = PositionGuardDeviceTracker(coordinator, GROUP_ID, FRED_ID)
    sally_tracker = PositionGuardDeviceTracker(coordinator, GROUP_ID, SALLY_ID)
    assert fred_tracker.available is False
    assert sally_tracker.available is True


async def test_first_refresh_failure_surfaces_without_state(coordinator, mock_client):
    """With no last-known data, a transient failure surfaces immediately."""
    assert coordinator.data is None
    mock_client.list_groups.side_effect = PositionGuardAPIError("server error 502")

    # Direct call: with self.data is None we must raise, never return None,
    # even though the failure counter (1) is still under the threshold (2).
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator.data is None
    assert coordinator._consecutive_failures == 1
