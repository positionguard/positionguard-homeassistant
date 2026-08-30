"""Sensor platform for PositionGuard.

One "member count" sensor per (group, area): how many members of that group are
currently inside that area, from the server-computed ``member_count`` /
``stale_count`` fields on the dedicated ``/groups/{id}/area-counts`` endpoint
(kept separate from the areas/geometry payload so the count stays coordinate-free
and pollable without refetching geometry every cycle).

This is the household-automation primitive that replaces ANDing one presence
sensor per family member (which breaks whenever group membership changes):

* ``== 0``  -> away mode
* ``0 -> 1`` -> arrival routine
* ``>= 4``  -> everyone home

Tri-state, deliberately: an integer (including a real ``0``) is an authoritative
count; an **absent** count renders the sensor **unavailable**, never ``0``. The
server withholds the count for public groups, archived areas, and compute
failures — and a ``0`` returned for any of those would fire "away mode" on a full
house. Absent means unknown, so the sensor goes unavailable and automations that
guard on availability do the right thing.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import PositionGuardCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one member-count sensor per (group, area).

    Spawned for every area of every selected group, including public groups and
    archived areas; those simply carry no count and the sensor sits unavailable
    until (if ever) the server sends one. That mirrors how the safety sensor is
    spawned regardless of whether the fields are currently present.
    """
    coordinator: PositionGuardCoordinator = hass.data[DOMAIN][entry.entry_id]

    known: set[tuple[str, str]] = set()  # (group_id, area_id)

    def _collect_entities() -> list[SensorEntity]:
        new: list[SensorEntity] = []
        groups = (coordinator.data or {}).get("groups", {})
        for group_id, group_data in groups.items():
            for area in group_data.get("areas", []):
                key = (group_id, area["id"])
                if key in known:
                    continue
                known.add(key)
                new.append(
                    PositionGuardAreaMemberCount(
                        coordinator=coordinator,
                        group_id=group_id,
                        area_id=area["id"],
                    )
                )
        return new

    async_add_entities(_collect_entities())

    @callback
    def _add_new() -> None:
        new = _collect_entities()
        if new:
            async_add_entities(new)

    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class PositionGuardAreaMemberCount(
    CoordinatorEntity[PositionGuardCoordinator], SensorEntity
):
    """How many of a group's members are currently inside a specific area.

    State is the server's ``member_count`` for the (group, area). ``stale_count``
    (members whose last position is stale) and a derived ``fresh_count`` ride
    along as attributes, so an automation author can choose resilience
    (``member_count``, stale included — the default, since a household asleep on
    battery saver goes stale together and excluding them fires a false away) or
    strict freshness (``fresh_count``).
    """

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:account-group"

    def __init__(
        self,
        coordinator: PositionGuardCoordinator,
        group_id: str,
        area_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._group_id = group_id
        self._area_id = area_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_"
            f"{group_id}_{area_id}_member_count"
        )

    @property
    def _group_data(self) -> dict[str, Any] | None:
        return (self.coordinator.data or {}).get("groups", {}).get(self._group_id)

    @property
    def _area(self) -> dict[str, Any] | None:
        """The area's geometry entry (for its name / existence)."""
        g = self._group_data
        if not g:
            return None
        for a in g.get("areas", []):
            if a["id"] == self._area_id:
                return a
        return None

    @property
    def _count(self) -> dict[str, Any] | None:
        """This area's entry in the volatile area_counts map, or None when the
        counts were not fetched this cycle (the endpoint is missing on an older
        backend, or a transient error degraded them) or the area is not
        present."""
        g = self._group_data
        if not g:
            return None
        return (g.get("area_counts") or {}).get(self._area_id)

    @property
    def _area_name(self) -> str:
        a = self._area
        return a.get("name", "Unknown Area") if a else "Unknown Area"

    @property
    def _group_name(self) -> str:
        g = self._group_data or {}
        return g.get("info", {}).get("name", "Unknown Group")

    @property
    def available(self) -> bool:
        """Unavailable when the count is absent — never coerce absent to 0.

        The server omits ``member_count`` for public groups, archived areas, and
        compute failures, and the whole counts payload is missing on an older
        backend or a degraded cycle. Either way the count is "unknown", which
        must surface as unavailable so an automation guarding on availability
        does not read it as an empty house.
        """
        if not super().available:
            return False
        count = self._count
        return count is not None and count.get("member_count") is not None

    @property
    def name(self) -> str:
        """Entity name: '<area_name> member count'."""
        return f"{self._area_name} member count"

    @property
    def native_value(self) -> int | None:
        """The authoritative member count, or None when withheld/unfetched."""
        return (self._count or {}).get("member_count")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Stale/fresh breakdown and context for automations."""
        count = self._count or {}
        member = count.get("member_count")
        stale = count.get("stale_count")
        attrs: dict[str, Any] = {
            "group_id": self._group_id,
            "group_name": self._group_name,
            "area_id": self._area_id,
            "area_name": self._area_name,
            "stale_count": stale,
        }
        # fresh_count only when both are real integers — never fabricate it from
        # a withheld count.
        if isinstance(member, int) and isinstance(stale, int):
            attrs["fresh_count"] = member - stale
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        """Group the sensor under the group's device, like the other entities."""
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
