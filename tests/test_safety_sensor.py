"""Tests for the 'outside usual area' safety binary sensor.

The sensor's contract, pinned here:

  1. on  only for safety_status == "out_of_zone"
  2. off for at_area / in_zone
  3. unavailable for stale — "no recent position" is a different kind of claim
     than inside/outside; mapping it to HA-native unavailable lets automations
     filter it instead of seeing a Safe/Unsafe flap. Never "off means safe".
  4. unavailable when the server sent no safety fields (flag off / muted
     member / public group / older server) — absence never reads as "safe"
  5. unavailable when sharing is paused
  6. the device_tracker carries the safety fields as attributes when present,
     and omits them when the server did
"""
from __future__ import annotations

import pytest

from custom_components.positionguard.binary_sensor import (
    PositionGuardOutsideUsualArea,
)
from custom_components.positionguard.device_tracker import PositionGuardDeviceTracker

from .fixtures_data import (
    FRED_ID,
    GROUP_ID,
    HOME_AREA_ID,
    make_member,
)


async def _refresh_with_member(coordinator, mock_client, member) -> None:
    mock_client.list_group_members.return_value = [member]
    await coordinator.async_refresh()
    assert coordinator.last_update_success


@pytest.mark.parametrize(
    ("safety_status", "expect_on"),
    [
        ("out_of_zone", True),
        ("at_area", False),
        ("in_zone", False),
    ],
)
async def test_state_mapping(
    coordinator, mock_client, safety_status: str, expect_on: bool
) -> None:
    """Only out_of_zone turns the sensor on; every other status is off."""
    member = make_member(
        FRED_ID,
        "Fred",
        inside=False,
        safety_status=safety_status,
        position_age_seconds=60,
    )
    await _refresh_with_member(coordinator, mock_client, member)

    sensor = PositionGuardOutsideUsualArea(coordinator, GROUP_ID, FRED_ID)
    assert sensor.available
    assert sensor.is_on is expect_on
    assert sensor.extra_state_attributes["safety_status"] == safety_status


async def test_stale_is_unavailable(coordinator, mock_client) -> None:
    """Stale -> unavailable, not 'off'. Absence of a fresh position must never
    read as safely inside, and HA-native unavailable lets automations filter
    the flap a stationary phone produced instead of seeing Safe/Unsafe bands."""
    member = make_member(
        FRED_ID,
        "Fred",
        inside=False,
        safety_status="stale",
        position_age_seconds=3600,
    )
    await _refresh_with_member(coordinator, mock_client, member)

    sensor = PositionGuardOutsideUsualArea(coordinator, GROUP_ID, FRED_ID)
    assert not sensor.available
    assert not sensor.is_on


async def test_unavailable_without_safety_fields(coordinator, mock_client) -> None:
    """No safety fields from the server -> unavailable, never 'off means safe'."""
    member = make_member(FRED_ID, "Fred", inside=True, area_id=HOME_AREA_ID)
    await _refresh_with_member(coordinator, mock_client, member)

    sensor = PositionGuardOutsideUsualArea(coordinator, GROUP_ID, FRED_ID)
    assert not sensor.available
    assert "safety_status" not in sensor.extra_state_attributes


async def test_unavailable_when_sharing_paused(coordinator, mock_client) -> None:
    """A paused member is unavailable even if stale fields linger in the payload."""
    member = make_member(
        FRED_ID,
        "Fred",
        inside=False,
        sharing_disabled=True,
        safety_status="out_of_zone",
    )
    await _refresh_with_member(coordinator, mock_client, member)

    sensor = PositionGuardOutsideUsualArea(coordinator, GROUP_ID, FRED_ID)
    assert not sensor.available


async def test_name_and_safety_area_attribute(coordinator, mock_client) -> None:
    """Name reads '<nickname> outside usual area'; safety_area rides along."""
    member = make_member(
        FRED_ID,
        "Fred",
        inside=True,
        area_id=HOME_AREA_ID,
        safety_status="at_area",
        safety_area="Home",
        position_age_seconds=42,
    )
    await _refresh_with_member(coordinator, mock_client, member)

    sensor = PositionGuardOutsideUsualArea(coordinator, GROUP_ID, FRED_ID)
    assert sensor.name == "Fred outside usual area"
    attrs = sensor.extra_state_attributes
    assert attrs["safety_area"] == "Home"
    assert attrs["position_age_seconds"] == 42


async def test_tracker_attributes_carry_safety_fields(
    coordinator, mock_client
) -> None:
    """The device_tracker exposes the fields when present, omits when absent."""
    member = make_member(
        FRED_ID,
        "Fred",
        inside=True,
        area_id=HOME_AREA_ID,
        safety_status="at_area",
        safety_area="Home",
    )
    await _refresh_with_member(coordinator, mock_client, member)
    tracker = PositionGuardDeviceTracker(coordinator, GROUP_ID, FRED_ID)
    attrs = tracker.extra_state_attributes
    assert attrs["safety_status"] == "at_area"
    assert attrs["safety_area"] == "Home"

    # Same member, no safety fields — the keys disappear rather than nulling.
    member = make_member(FRED_ID, "Fred", inside=True, area_id=HOME_AREA_ID)
    await _refresh_with_member(coordinator, mock_client, member)
    attrs = tracker.extra_state_attributes
    assert "safety_status" not in attrs
    assert "safety_area" not in attrs
