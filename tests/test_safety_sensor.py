"""Tests for the 'outside usual area' safety binary sensor.

The sensor's contract, pinned here:

  1. on  only for safety_status == "out_of_zone"
  2. off for at_area / in_zone
  3. unavailable for stale — "no recent position" is a different kind of claim
     than inside/outside; mapping it to HA-native unavailable lets automations
     filter it instead of seeing an Inside/Outside flap. Never "off means
     inside".
  4. unavailable when the server sent no safety fields (flag off / muted
     member / public group / older server) — absence never reads as "Inside"
  5. unavailable when sharing is paused
  6. the device_tracker carries the safety fields as attributes when present,
     and omits them when the server did
  7. a held at_area (position_fresh false, the server's area hold) stays
     AVAILABLE and off — availability follows "stale", never position_fresh,
     or the flap the hold removes comes back; position_fresh rides along as
     an attribute on both entities, and is absent (not False) when the server
     didn't send it
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
    read as inside their usual area, and HA-native unavailable lets automations
    filter the flap a stationary phone produced instead of Inside/Outside
    bands."""
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
    """No safety fields from the server -> unavailable, never 'off means inside'."""
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


async def test_held_at_area_stays_available(coordinator, mock_client) -> None:
    """Pins the availability rule against the area hold: at_area with
    position_fresh False (36,000 s old) is available and off, not unavailable.
    Tying availability to position_fresh would bring back the at_area <->
    unavailable flap the server's hold exists to remove."""
    member = make_member(
        FRED_ID,
        "Fred",
        inside=True,
        area_id=HOME_AREA_ID,
        safety_status="at_area",
        safety_area="Home",
        position_age_seconds=36000,
        position_fresh=False,
    )
    await _refresh_with_member(coordinator, mock_client, member)

    sensor = PositionGuardOutsideUsualArea(coordinator, GROUP_ID, FRED_ID)
    assert sensor.available
    assert sensor.is_on is False
    attrs = sensor.extra_state_attributes
    assert attrs["position_fresh"] is False
    assert attrs["position_age_seconds"] == 36000
    assert attrs["safety_status"] == "at_area"

    tracker = PositionGuardDeviceTracker(coordinator, GROUP_ID, FRED_ID)
    assert tracker.extra_state_attributes["position_fresh"] is False


async def test_stale_with_position_fresh_is_still_unavailable(
    coordinator, mock_client
) -> None:
    """A new server's stale row (position_fresh False) is unavailable exactly
    as before — the stale rule is unchanged."""
    member = make_member(
        FRED_ID,
        "Fred",
        inside=False,
        safety_status="stale",
        position_age_seconds=4200,
        position_fresh=False,
    )
    await _refresh_with_member(coordinator, mock_client, member)

    sensor = PositionGuardOutsideUsualArea(coordinator, GROUP_ID, FRED_ID)
    assert not sensor.available


async def test_position_fresh_attribute_present_only_when_sent(
    coordinator, mock_client
) -> None:
    """position_fresh True passes through; an older server's row (no field)
    leaves the attribute out entirely rather than reporting False."""
    member = make_member(
        FRED_ID,
        "Fred",
        inside=True,
        area_id=HOME_AREA_ID,
        safety_status="at_area",
        position_age_seconds=60,
        position_fresh=True,
    )
    await _refresh_with_member(coordinator, mock_client, member)
    sensor = PositionGuardOutsideUsualArea(coordinator, GROUP_ID, FRED_ID)
    tracker = PositionGuardDeviceTracker(coordinator, GROUP_ID, FRED_ID)
    assert sensor.extra_state_attributes["position_fresh"] is True
    assert tracker.extra_state_attributes["position_fresh"] is True

    member = make_member(
        FRED_ID,
        "Fred",
        inside=True,
        area_id=HOME_AREA_ID,
        safety_status="at_area",
        position_age_seconds=60,
    )
    await _refresh_with_member(coordinator, mock_client, member)
    assert sensor.available
    assert "position_fresh" not in sensor.extra_state_attributes
    assert "position_fresh" not in tracker.extra_state_attributes


async def test_tracker_stays_available_when_stale(coordinator, mock_client) -> None:
    """Pins what the README points automations at: on a stale member the
    outside-usual-area sensor goes unavailable (no attributes), but the
    device tracker stays AVAILABLE and carries safety_status "stale", with
    position_fresh False (when the server sends it) and the age."""
    member = make_member(
        FRED_ID,
        "Fred",
        inside=False,
        safety_status="stale",
        position_age_seconds=4200,
        position_fresh=False,
    )
    await _refresh_with_member(coordinator, mock_client, member)

    sensor = PositionGuardOutsideUsualArea(coordinator, GROUP_ID, FRED_ID)
    assert not sensor.available

    tracker = PositionGuardDeviceTracker(coordinator, GROUP_ID, FRED_ID)
    assert tracker.available
    attrs = tracker.extra_state_attributes
    assert attrs["safety_status"] == "stale"
    assert attrs["position_fresh"] is False
    assert attrs["position_age_seconds"] == 4200


async def test_sensor_is_display_only_no_device_class(coordinator, mock_client) -> None:
    """The SAFETY device class is gone (it rendered on/off as "Unsafe"/"Safe",
    a judgement this product does not make), and nothing else moved with it:
    the unique_id and the on/off mapping are what they were, so existing
    entity ids, history and automations are untouched. The new labels come
    from translation_key via translations/en.json, which is display only."""
    member = make_member(
        FRED_ID,
        "Fred",
        inside=False,
        safety_status="out_of_zone",
        position_age_seconds=60,
    )
    await _refresh_with_member(coordinator, mock_client, member)

    sensor = PositionGuardOutsideUsualArea(coordinator, GROUP_ID, FRED_ID)
    assert sensor.device_class is None
    assert sensor.translation_key == "outside_usual_area"
    assert sensor.unique_id == (
        f"{coordinator.config_entry.entry_id}_{GROUP_ID}_{FRED_ID}_outside_usual_area"
    )
    assert sensor.is_on is True

    # Same entity, member back inside a saved place: off, same unique_id.
    member = make_member(
        FRED_ID,
        "Fred",
        inside=True,
        area_id=HOME_AREA_ID,
        safety_status="at_area",
        position_age_seconds=60,
    )
    await _refresh_with_member(coordinator, mock_client, member)
    assert sensor.is_on is False
    assert sensor.available
    assert sensor.unique_id == (
        f"{coordinator.config_entry.entry_id}_{GROUP_ID}_{FRED_ID}_outside_usual_area"
    )


def test_state_labels_and_icons_are_registered() -> None:
    """The labels and icons HA reads for a custom integration: it loads
    translations/<lang>.json (strings.json is the source copy, not read at
    runtime) and icons.json, both keyed by translation_key. Icons are plain
    map markers — no alert or warning glyph."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "custom_components" / "positionguard"
    key = "outside_usual_area"
    for name in ("translations/en.json", "strings.json"):
        states = json.loads((root / name).read_text())["entity"]["binary_sensor"][key]["state"]
        assert states == {"off": "Inside", "on": "Outside"}, name

    icons = json.loads((root / "icons.json").read_text())["entity"]["binary_sensor"][key]
    assert icons["default"] == "mdi:map-marker-radius"
    assert icons["state"]["on"] == "mdi:map-marker-outline"
    rendered = [icons["default"], *icons["state"].values()]
    assert all(i.startswith("mdi:map-marker") for i in rendered), rendered
    assert not any(w in i for i in rendered for w in ("alert", "warning", "danger")), rendered
