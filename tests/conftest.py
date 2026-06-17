"""Shared fixtures for the PositionGuard test suite.

All fixtures use the fictional, public-repo-safe data from ``fixtures_data``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.positionguard.const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_GROUP_IDS,
    DEFAULT_BASE_URL,
    DOMAIN,
)
from custom_components.positionguard.coordinator import PositionGuardCoordinator

from .fixtures_data import (
    FAKE_API_KEY,
    FRED_ID,
    GROUP_ID,
    HOME_AREA_ID,
    SALLY_ID,
    SCHOOL_AREA_ID,
    make_areas,
    make_group,
    make_member,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load the positionguard custom component during tests (HA standard)."""
    yield


@pytest.fixture(autouse=True)
def _instant_retry_backoff(monkeypatch):
    """Collapse the in-cycle retry backoff to 0s so tests don't really sleep."""
    monkeypatch.setattr(
        "custom_components.positionguard.coordinator.RETRY_BACKOFF_SECONDS", 0
    )


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A config entry with fictional data selecting the one fixture group."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="PositionGuard",
        unique_id=FAKE_API_KEY,
        data={
            CONF_API_KEY: FAKE_API_KEY,
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_GROUP_IDS: [GROUP_ID],
        },
    )


@pytest.fixture
def mock_client() -> MagicMock:
    """PositionGuardClient stand-in.

    Defaults to a healthy 'Family' group: Fred at Home, Sally at School.
    Individual tests override ``return_value`` / ``side_effect`` per case.
    """
    client = MagicMock()
    client.list_groups = AsyncMock(return_value=[make_group()])
    client.list_group_members = AsyncMock(
        return_value=[
            make_member(FRED_ID, "Fred", inside=True, area_id=HOME_AREA_ID),
            make_member(SALLY_ID, "Sally", inside=True, area_id=SCHOOL_AREA_ID),
        ]
    )
    client.list_group_areas = AsyncMock(return_value=make_areas())
    return client


@pytest.fixture
def coordinator(hass, mock_client, mock_config_entry) -> PositionGuardCoordinator:
    """A coordinator wired to the mock client and a config entry."""
    mock_config_entry.add_to_hass(hass)
    coord = PositionGuardCoordinator(hass, mock_client, [GROUP_ID])
    # During real setup HA infers config_entry from context; set it explicitly
    # here so entity construction (which builds unique_ids from it) works.
    coord.config_entry = mock_config_entry
    return coord
