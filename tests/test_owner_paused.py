"""The key's owner has paused sharing: 409 OWNER_PAUSED.

While the account that owns the API key is paused, PositionGuard answers
members, area counts and presence with 409 and the code OWNER_PAUSED. That is
a pause the user chose, not an outage:

  1. every entity keeps its last state (nothing goes unavailable);
  2. one info line is logged, not one per poll;
  3. polling goes on, and the first poll after the owner resumes updates;
  4. any other error, a 409 without that code included, behaves as before.
"""
from __future__ import annotations

import logging

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.positionguard.api import (
    PositionGuardAPIError,
    PositionGuardClient,
    PositionGuardOwnerPausedError,
)
from custom_components.positionguard.device_tracker import PositionGuardDeviceTracker

from .fixtures_data import (
    FAKE_API_KEY,
    FRED_ID,
    GROUP_ID,
    HOME_AREA_ID,
    SALLY_ID,
    SCHOOL_AREA_ID,
    make_member,
)

_COORD_LOGGER = "custom_components.positionguard.coordinator"
_PAUSED = PositionGuardOwnerPausedError("sharing is paused for the account that owns this API key")


def _info_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.INFO and r.name == _COORD_LOGGER]


def _loud_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


# --- the coordinator ---------------------------------------------------------


async def test_entities_keep_their_last_state_while_the_owner_is_paused(coordinator, mock_client, caplog):
    await coordinator.async_refresh()
    baseline = coordinator.data
    fred = PositionGuardDeviceTracker(coordinator, GROUP_ID, FRED_ID)
    sally = PositionGuardDeviceTracker(coordinator, GROUP_ID, SALLY_ID)
    assert fred.available and sally.available

    mock_client.list_group_members.side_effect = _PAUSED
    with caplog.at_level(logging.DEBUG, logger=_COORD_LOGGER):
        for _ in range(3):
            await coordinator.async_refresh()
            # Not an outage: the poll counts as a success and nothing changed.
            assert coordinator.last_update_success is True
            assert coordinator.data is baseline
            assert coordinator._consecutive_failures == 0
            assert fred.available and sally.available

    # Fred is still shown where he was last seen.
    members = coordinator.data["groups"][GROUP_ID]["members"]
    assert next(m for m in members if m["user_id"] == FRED_ID)["current_area"]["id"] == HOME_AREA_ID

    # One info line for the whole pause, and nothing louder.
    info = _info_lines(caplog)
    assert len(info) == 1, info
    assert "paused" in info[0] and "keep their last state" in info[0]
    assert not _loud_records(caplog)


async def test_polling_goes_on_and_a_pause_is_not_retried(coordinator, mock_client):
    await coordinator.async_refresh()
    mock_client.list_groups.reset_mock()
    mock_client.list_group_members.reset_mock()
    mock_client.list_group_members.side_effect = _PAUSED

    for _ in range(3):
        await coordinator.async_refresh()

    # Each poll asked once: three polls, three calls. A transient error would
    # have been retried inside the cycle (two calls each).
    assert mock_client.list_groups.call_count == 3
    assert mock_client.list_group_members.call_count == 3
    # The interval is untouched, so Home Assistant keeps scheduling polls.
    assert coordinator.update_interval is not None


async def test_the_first_poll_after_resuming_updates_and_says_so_once(coordinator, mock_client, caplog):
    await coordinator.async_refresh()
    mock_client.list_group_members.side_effect = _PAUSED
    await coordinator.async_refresh()

    # The owner resumes; Fred has meanwhile gone to school.
    mock_client.list_group_members.side_effect = None
    mock_client.list_group_members.return_value = [
        make_member(FRED_ID, "Fred", inside=True, area_id=SCHOOL_AREA_ID),
        make_member(SALLY_ID, "Sally", inside=True, area_id=SCHOOL_AREA_ID),
    ]
    caplog.clear()      # the pause's own line is counted in the test above
    with caplog.at_level(logging.DEBUG, logger=_COORD_LOGGER):
        await coordinator.async_refresh()
        await coordinator.async_refresh()

    members = coordinator.data["groups"][GROUP_ID]["members"]
    assert next(m for m in members if m["user_id"] == FRED_ID)["current_area"]["id"] == SCHOOL_AREA_ID
    info = _info_lines(caplog)
    assert len(info) == 1 and "resumed" in info[0], info

    # A second pause is announced again: one line per pause, not one ever.
    mock_client.list_group_members.side_effect = _PAUSED
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=_COORD_LOGGER):
        await coordinator.async_refresh()
        await coordinator.async_refresh()
    assert len(_info_lines(caplog)) == 1


async def test_a_pause_seen_on_area_counts_holds_the_whole_poll(coordinator, mock_client):
    await coordinator.async_refresh()
    baseline = coordinator.data

    # Members answer, the counts are refused: still a pause, not "no counts".
    mock_client.list_group_area_counts.side_effect = _PAUSED
    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert coordinator.data is baseline


async def test_paused_at_the_first_poll_has_no_state_to_keep(coordinator, mock_client):
    assert coordinator.data is None
    mock_client.list_group_members.side_effect = _PAUSED

    with pytest.raises(UpdateFailed, match="paused"):
        await coordinator._async_update_data()


async def test_other_errors_behave_as_before(coordinator, mock_client, caplog):
    """A 409 without the code, like any API error: one cycle tolerated, then surfaced."""
    await coordinator.async_refresh()
    mock_client.list_group_members.side_effect = PositionGuardAPIError("unexpected status 409")

    await coordinator.async_refresh()
    assert coordinator.last_update_success is True      # the one tolerated cycle
    assert coordinator._consecutive_failures == 1

    with caplog.at_level(logging.DEBUG, logger=_COORD_LOGGER):
        await coordinator.async_refresh()
    assert coordinator.last_update_success is False     # surfaced: entities unavailable
    assert not _info_lines(caplog)


# --- the client --------------------------------------------------------------


class _Response:
    def __init__(self, status: int, body) -> None:
        self.status = status
        self.headers: dict[str, str] = {}
        self._body = body

    async def json(self, content_type=None):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Session:
    def __init__(self, response: _Response) -> None:
        self._response = response

    def get(self, url, headers=None, timeout=None):
        return self._response


def _client(status: int, body) -> PositionGuardClient:
    return PositionGuardClient(_Session(_Response(status, body)), FAKE_API_KEY, "https://api.example.invalid/api/v1")


_PAUSED_BODY = {
    "error": "Sharing is paused for this account, so other people's presence isn't available. "
    "Resume sharing in the PositionGuard app.",
    "code": "OWNER_PAUSED",
}


@pytest.mark.parametrize("call", ["members", "area_counts", "presence"])
async def test_a_409_with_the_code_is_owner_paused(call):
    client = _client(409, _PAUSED_BODY)
    with pytest.raises(PositionGuardOwnerPausedError):
        if call == "members":
            await client.list_group_members(GROUP_ID)
        elif call == "area_counts":
            await client.list_group_area_counts(GROUP_ID)
        else:
            await client.get_user_presence(FRED_ID)


@pytest.mark.parametrize("body", [{"error": "conflict", "code": "SOMETHING_ELSE"}, {}, ["not", "an", "object"], ValueError("not json")])
async def test_any_other_409_is_an_ordinary_error(body):
    client = _client(409, body)
    with pytest.raises(PositionGuardAPIError) as caught:
        await client.list_group_members(GROUP_ID)
    assert not isinstance(caught.value, PositionGuardOwnerPausedError)
    assert "409" in str(caught.value)
