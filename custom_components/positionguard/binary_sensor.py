"""Binary sensor platform for PositionGuard.

Two kinds of binary sensor:

* One per (member, area) pair visible through selected groups — 'on' when the
  member is inside that specific area. Disabled by default (the spawn is
  combinatorial); users enable the specific pairs they care about.

* One "outside usual area" safety sensor per (group, member) — 'on' when the
  server's safety status says the member is confirmed outside their own usual
  area. Enabled by default: this is the one condition worth automating on
  directly (a notification, an announcement), and its cardinality matches the
  device_tracker's.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import PositionGuardCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create per-area binary sensors for each (member, area) pair.

    We spawn an entity for every combination of member and area visible
    through a selected group. Users enable only the ones they use.
    """
    coordinator: PositionGuardCoordinator = hass.data[DOMAIN][entry.entry_id]

    known: set[tuple[str, str, str]] = set()  # (group_id, user_id, area_id)
    known_safety: set[tuple[str, str]] = set()  # (group_id, user_id)
    entities: list[BinarySensorEntity] = []

    def _collect_entities() -> list[BinarySensorEntity]:
        new: list[BinarySensorEntity] = []
        groups = (coordinator.data or {}).get("groups", {})
        for group_id, group_data in groups.items():
            member_ids = [m["user_id"] for m in group_data.get("members", [])]
            areas = group_data.get("areas", [])
            for user_id in member_ids:
                # One safety sensor per (group, member) — spawned regardless of
                # whether the current payload carries safety fields, so a
                # server-side flag flip lights existing entities up rather than
                # needing a reload. Until then they sit unavailable.
                safety_key = (group_id, user_id)
                if safety_key not in known_safety:
                    known_safety.add(safety_key)
                    new.append(
                        PositionGuardOutsideUsualArea(
                            coordinator=coordinator,
                            group_id=group_id,
                            user_id=user_id,
                        )
                    )
                for area in areas:
                    key = (group_id, user_id, area["id"])
                    if key in known:
                        continue
                    known.add(key)
                    new.append(
                        PositionGuardAreaPresence(
                            coordinator=coordinator,
                            group_id=group_id,
                            user_id=user_id,
                            area_id=area["id"],
                        )
                    )
        return new

    entities.extend(_collect_entities())
    async_add_entities(entities)

    # If a group gains new members or areas during a poll cycle, create
    # matching binary_sensors automatically.
    @callback
    def _add_new() -> None:
        new = _collect_entities()
        if new:
            async_add_entities(new)

    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class PositionGuardOutsideUsualArea(
    CoordinatorEntity[PositionGuardCoordinator], BinarySensorEntity
):
    """On when the server says a member is confirmed OUTSIDE their usual area.

    'Usual area' is the member's own server-computed safety zone (their
    visit-weighted cluster of saved places). The mapping is deliberately
    strict so this can drive alert automations directly:

    * on  — safety_status == "out_of_zone": a fresh position exists and it is
            confirmed outside the member's usual area.
    * off — at_area / in_zone: the member is somewhere expected.
    * unavailable — the server sent no safety fields (feature flag off, member
            muted in this group, public group, or an older server), OR
            safety_status == "stale". "No recent position" is a different kind
            of claim than inside/outside, so it maps to HA's native unavailable:
            automations filter it like any unavailable entity, instead of the
            Safe/Unsafe flap a stationary phone produced by dropping to "off".
            A phone dying in a pocket must never render as "safe" nor fire an
            outside-zone alarm. The raw status string stays in the attributes.
            Absence of knowledge must never render as "safe".
    """

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    # SAFETY device class: 'on' renders as a problem state in HA, which is
    # exactly the semantics — on means "outside their usual area".
    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(
        self,
        coordinator: PositionGuardCoordinator,
        group_id: str,
        user_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._group_id = group_id
        self._user_id = user_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_"
            f"{group_id}_{user_id}_outside_usual_area"
        )

    @property
    def _member(self) -> dict[str, Any] | None:
        group = (self.coordinator.data or {}).get("groups", {}).get(self._group_id)
        if not group:
            return None
        for m in group.get("members", []):
            if m["user_id"] == self._user_id:
                return m
        return None

    @property
    def _group_name(self) -> str:
        group = (self.coordinator.data or {}).get("groups", {}).get(self._group_id, {})
        return group.get("info", {}).get("name", "Unknown Group")

    @property
    def available(self) -> bool:
        """Unavailable when there is nothing trustworthy to report.

        Member gone from the group, sharing paused, or the server sent no
        safety fields — in every one of those, "off" would falsely read as
        "safely inside their usual area".
        """
        if not super().available:
            return False
        member = self._member
        if member is None:
            return False
        if member.get("sharing_disabled"):
            return False
        if "safety_status" not in member:
            return False
        # Stale renders as unavailable, not "off". "No recent position" is a
        # different KIND of claim than "inside their usual area" (off), so
        # mapping it to HA's native unavailable lets automations filter it like
        # any unavailable entity, instead of the Safe/Unsafe flap a stationary
        # phone produced by dropping to "off". Rare once the server's 50-minute
        # stale threshold lands; when it does show, the phone is genuinely dark.
        return member.get("safety_status") != "stale"

    @property
    def name(self) -> str:
        member = self._member
        nickname = (member or {}).get("nickname") or "Unknown"
        return f"{nickname} outside usual area"

    @property
    def is_on(self) -> bool:
        member = self._member or {}
        return member.get("safety_status") == "out_of_zone"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        member = self._member or {}
        attrs: dict[str, Any] = {
            "group_id": self._group_id,
            "group_name": self._group_name,
            "user_id": self._user_id,
            "nickname": member.get("nickname"),
        }
        for key in ("safety_status", "safety_area", "position_age_seconds"):
            if key in member:
                attrs[key] = member[key]
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        """Same group 'device' the tracker and area sensors hang off."""
        return {
            "identifiers": {
                (
                    DOMAIN,
                    f"{self.coordinator.config_entry.entry_id}_{self._group_id}",
                )
            },
            "name": f"PositionGuard: {self._group_name}",
            "manufacturer": MANUFACTURER,
            "model": "Group",
            "configuration_url": "https://positionguardai.com",
        }


class PositionGuardAreaPresence(
    CoordinatorEntity[PositionGuardCoordinator], BinarySensorEntity
):
    """True when a specific member is currently inside a specific area.

    Scoped to a specific group context so area membership respects
    group visibility — a user might be inside an area belonging to
    one group but not another.
    """

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PRESENCE
    # Disabled by default — users enable specific ones they want
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: PositionGuardCoordinator,
        group_id: str,
        user_id: str,
        area_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._group_id = group_id
        self._user_id = user_id
        self._area_id = area_id

        # Stable unique_id across restarts
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_"
            f"{group_id}_{user_id}_{area_id}_presence"
        )

    @property
    def _group_data(self) -> dict[str, Any] | None:
        return (self.coordinator.data or {}).get("groups", {}).get(self._group_id)

    @property
    def _member(self) -> dict[str, Any] | None:
        g = self._group_data
        if not g:
            return None
        for m in g.get("members", []):
            if m["user_id"] == self._user_id:
                return m
        return None

    @property
    def _area(self) -> dict[str, Any] | None:
        g = self._group_data
        if not g:
            return None
        for a in g.get("areas", []):
            if a["id"] == self._area_id:
                return a
        return None

    @property
    def _member_nickname(self) -> str:
        m = self._member
        if m and m.get("nickname"):
            return m["nickname"]
        return "Unknown"

    @property
    def _area_name(self) -> str:
        a = self._area
        if a:
            return a.get("name", "Unknown Area")
        return "Unknown Area"

    @property
    def _group_name(self) -> str:
        g = self._group_data or {}
        return g.get("info", {}).get("name", "Unknown Group")

    @property
    def available(self) -> bool:
        """Unavailable if member is gone from group, area removed, or sharing off."""
        if not super().available:
            return False
        member = self._member
        if member is None or self._area is None:
            return False
        if member.get("sharing_disabled"):
            return False
        return True

    @property
    def name(self) -> str:
        """Entity name: '<nickname> at <area_name>'."""
        return f"{self._member_nickname} at {self._area_name}"

    @property
    def is_on(self) -> bool:
        """True when member is currently inside this specific area."""
        m = self._member
        if not m or not m.get("inside"):
            return False
        current = m.get("current_area") or {}
        return current.get("id") == self._area_id

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Surface context useful for automations."""
        return {
            "group_id": self._group_id,
            "group_name": self._group_name,
            "user_id": self._user_id,
            "nickname": self._member_nickname,
            "area_id": self._area_id,
            "area_name": self._area_name,
        }

    @property
    def device_info(self) -> dict[str, Any]:
        """Associate with the group's 'device' so entities group logically."""
        return {
            "identifiers": {
                (
                    DOMAIN,
                    f"{self.coordinator.config_entry.entry_id}_{self._group_id}",
                )
            },
            "name": f"PositionGuard: {self._group_name}",
            "manufacturer": MANUFACTURER,
            "model": "Group",
            "configuration_url": "https://positionguardai.com",
        }