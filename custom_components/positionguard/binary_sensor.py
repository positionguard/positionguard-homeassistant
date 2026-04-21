"""Binary sensor platform for PositionGuard.

Exposes one binary_sensor per (member, area) pair visible through selected groups.
State is 'on' when the member is inside that specific area.

All binary_sensors are disabled by default. Users enable only the specific
(member, area) combinations they care about via the HA Entities page.
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
    entities: list[PositionGuardAreaPresence] = []

    def _collect_entities() -> list[PositionGuardAreaPresence]:
        new: list[PositionGuardAreaPresence] = []
        groups = (coordinator.data or {}).get("groups", {})
        for group_id, group_data in groups.items():
            member_ids = [m["user_id"] for m in group_data.get("members", [])]
            areas = group_data.get("areas", [])
            for user_id in member_ids:
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