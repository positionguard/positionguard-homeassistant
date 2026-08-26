"""Fictional, public-repo-safe test data for the PositionGuard tests.

Everything here is INVENTED. No real API keys, user UUIDs, names, area names,
or coordinates appear — this repo is public and its git history is permanent.
Identities follow the README's sample family (Fred, Sarah, Peter, John, Sally)
with generic areas (Home, School).
"""
from __future__ import annotations

from typing import Any

# Obviously-fake API key (keeps the ``pg_live_`` prefix the config flow checks).
FAKE_API_KEY = "pg_live_test_0000000000"

# Invented UUIDs — deliberately patterned so they read as fake, not real.
GROUP_ID = "11111111-1111-1111-1111-111111111111"
FRED_ID = "aaaaaaaa-0000-0000-0000-000000000001"
SALLY_ID = "aaaaaaaa-0000-0000-0000-000000000002"
HOME_AREA_ID = "22222222-0000-0000-0000-000000000001"
SCHOOL_AREA_ID = "22222222-0000-0000-0000-000000000002"

_AREA_NAMES = {HOME_AREA_ID: "Home", SCHOOL_AREA_ID: "School"}


def make_group() -> dict[str, Any]:
    """A single fictional 'Family' group, shaped like a GET /groups item."""
    return {
        "id": GROUP_ID,
        "name": "Family",
        "icon": "mdi:account-group",
        "group_type": "family",
    }


def make_areas() -> list[dict[str, Any]]:
    """Two generic areas with invented (non-real) coordinates."""
    return [
        {
            "id": HOME_AREA_ID,
            "name": "Home",
            "latitude": 12.3456,
            "longitude": 65.4321,
            "radius_meters": 100,
        },
        {
            "id": SCHOOL_AREA_ID,
            "name": "School",
            "latitude": 12.3556,
            "longitude": 65.4421,
            "radius_meters": 150,
        },
    ]


def make_member(
    user_id: str,
    nickname: str,
    *,
    inside: bool,
    area_id: str | None = None,
    sharing_disabled: bool = False,
    safety_status: str | None = None,
    safety_area: str | None = None,
    position_age_seconds: int | None = None,
) -> dict[str, Any]:
    """A member record shaped like a GET /groups/{id}/members item."""
    current_area = None
    if inside and area_id is not None:
        current_area = {"id": area_id, "name": _AREA_NAMES.get(area_id, "Unknown")}
    record: dict[str, Any] = {
        "user_id": user_id,
        "nickname": nickname,
        "inside": inside,
        "current_area": current_area,
        "sharing_disabled": sharing_disabled,
        "avatar_url": None,
        "last_update": "2026-06-17T00:00:00Z",
    }
    # The REST API omits the safety fields entirely (omitempty) when the
    # server flag is off, the member is muted in the group, or the group is
    # public — mirror that: absent keys, never nulls. A record without
    # safety_status is how "the server can't say" arrives.
    if safety_status is not None:
        record["safety_status"] = safety_status
        if safety_area is not None:
            record["safety_area"] = safety_area
        if position_age_seconds is not None:
            record["position_age_seconds"] = position_age_seconds
    return record
