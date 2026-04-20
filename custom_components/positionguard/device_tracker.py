"""Device tracker platform for PositionGuard.

Exposes one device_tracker entity per member of each selected group. State
is home/not_home based on whether the member is inside any area belonging
to the group. Current area name is exposed as an attribute.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_HOME, STATE_NOT_HOME
from homeassistant.core import HomeAssistant, callback
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
    """Create device_tracker entities for each member of each selected group."""
    coordinator: PositionGuardCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[PositionGuardDeviceTracker] = []
    known: set[tuple[str, str]] = set()  # (group_id, user_id) pairs

    # Initial pass — create entities from what the first refresh returned.
    for group_id, group_data in (coordinator.data or {}).get("groups", {}).items():
        for member in group_data.get("members", []):
            key = (group_id, member["user_id"])
            if key not in known:
                known.add(key)
                entities.append(
                    PositionGuardDeviceTracker(coordinator, group_id, member["user_id"])
                )

    async_add_entities(entities)

    # Dynamic entity creation: if a new member joins a group later, we want
    # a device_tracker to appear for them automatically. Subscribe to
    # coordinator updates and add entities as needed.
    @callback
    def _add_new_members() -> None:
        new_entities: list[PositionGuardDeviceTracker] = []
        for group_id, group_data in (coordinator.data or {}).get("groups", {}).items():
            for member in group_data.get("members", []):
                key = (group_id, member["user_id"])
                if key not in known:
                    known.add(key)
                    new_entities.append(
                        PositionGuardDeviceTracker(
                            coordinator, group_id, member["user_id"]
                        )
                    )
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_add_new_members))


class PositionGuardDeviceTracker(CoordinatorEntity[PositionGuardCoordinator], TrackerEntity):
    """Tracks one member's presence relative to one group.

    A user in multiple groups gets one entity per group, so automations can
    target 'Chris in the Family group' vs 'Chris in the Work group' independently.
    """

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PositionGuardCoordinator,
        group_id: str,
        user_id: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._group_id = group_id
        self._user_id = user_id

        # unique_id combines config entry + group + user to guarantee uniqueness
        # across multiple accounts and repeated group memberships.
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{group_id}_{user_id}"

    @property
    def _member(self) -> dict[str, Any] | None:
        """Look up this entity's current member record from coordinator data."""
        groups = (self.coordinator.data or {}).get("groups", {})
        group = groups.get(self._group_id)
        if not group:
            return None
        for member in group.get("members", []):
            if member["user_id"] == self._user_id:
                return member
        return None

    @property
    def _group_name(self) -> str:
        """The display name of the group this entity belongs to."""
        group = (self.coordinator.data or {}).get("groups", {}).get(self._group_id, {})
        return group.get("info", {}).get("name", "Unknown Group")

    @property
    def available(self) -> bool:
        """Entity is unavailable if member disappeared from API or sharing is off.

        Marking unavailable (rather than not_home) when sharing is disabled
        prevents HA automations that trigger on home/not_home transitions
        from firing when a user simply pauses sharing.
        """
        if not super().available:
            return False
        member = self._member
        if member is None:
            return False
        if member.get("sharing_disabled"):
            return False
        return True

    @property
    def name(self) -> str | None:
        """Entity name shown in HA UI.

        Using 'Nickname in GroupName' makes automations readable.
        E.g. 'Carl in Family' vs 'Carl in Pickleball'.
        """
        member = self._member
        if not member:
            return None
        nickname = member.get("nickname") or "Unknown"
        return f"{nickname} in {self._group_name}"

    @property
    def source_type(self) -> SourceType:
        """We treat presence as GPS-like for HA categorization."""
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Not exposed in V1. Returning None keeps map widgets neutral.

        V2 could expose area centroids or actual last-known GPS if we add
        that data to the API.
        """
        return None

    @property
    def longitude(self) -> float | None:
        return None

    @property
    def location_name(self) -> str | None:
        """The zone-like name shown in HA.

        Returning 'home' when inside triggers HA's standard home/not_home
        state handling. Automations can trigger on state changes directly.
        """
        member = self._member
        if not member:
            return None
        if member.get("inside"):
            return STATE_HOME
        return STATE_NOT_HOME

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Extra data exposed for automations and dashboards."""
        member = self._member
        if not member:
            return {}

        area = member.get("current_area")
        attrs: dict[str, Any] = {
            "group_id": self._group_id,
            "group_name": self._group_name,
            "user_id": self._user_id,
            "nickname": member.get("nickname"),
            "avatar_url": member.get("avatar_url"),
            "area": area["name"] if area else None,
            "area_id": area["id"] if area else None,
            "last_update": member.get("last_update"),
        }
        # Include sharing state so dashboard cards can show "Not sharing".
        if member.get("sharing_disabled"):
            attrs["sharing_status"] = "disabled"
        else:
            attrs["sharing_status"] = "active"
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        """Represent this as a logical 'device' in HA's registry.

        Grouping entities by device makes the HA UI cleaner. Per-group
        device grouping means 'Family' shows all family members together.
        """
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.config_entry.entry_id}_{self._group_id}")},
            "name": f"PositionGuard: {self._group_name}",
            "manufacturer": MANUFACTURER,
            "model": "Group",
            "configuration_url": "https://positionguardai.com",
        }