"""Config flow for the PositionGuard integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    PositionGuardAPIError,
    PositionGuardAuthError,
    PositionGuardClient,
)
from .const import (
    CONF_BASE_URL,
    CONF_GROUP_IDS,
    DEFAULT_BASE_URL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


# Schema for step 1: API key + optional base URL override.
STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): str,
        vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
    }
)


class PositionGuardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Two-step config flow.

    Step 1 (user): user enters API key. We validate it by calling /groups and
                   cache the result for step 2.
    Step 2 (groups): we present checkboxes of available groups; user picks.
    """

    VERSION = 1

    def __init__(self) -> None:
        """Initialize transient state used across steps."""
        self._api_key: str | None = None
        self._base_url: str = DEFAULT_BASE_URL
        self._groups: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step: collect and validate the API key."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            base_url = user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL).strip()

            # Quick sanity check on the key format.
            if not api_key.startswith("pg_live_"):
                errors[CONF_API_KEY] = "invalid_format"
            else:
                session = async_get_clientsession(self.hass)
                client = PositionGuardClient(
                    session=session, api_key=api_key, base_url=base_url
                )
                try:
                    groups = await client.list_groups()
                except PositionGuardAuthError:
                    errors[CONF_API_KEY] = "invalid_auth"
                except PositionGuardAPIError as err:
                    _LOGGER.error("API error during config flow: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    if not groups:
                        errors["base"] = "no_groups"
                    else:
                        # Save for step 2.
                        self._api_key = api_key
                        self._base_url = base_url
                        self._groups = groups
                        return await self.async_step_groups()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={"docs_url": "https://positionguardai.com"},
        )

    async def async_step_groups(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Second step: user picks which groups to integrate."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected = user_input.get(CONF_GROUP_IDS, [])
            if not selected:
                errors[CONF_GROUP_IDS] = "no_selection"
            else:
                # Use the API key as a stable unique_id so re-adding with the
                # same key triggers the already_configured guard.
                await self.async_set_unique_id(self._api_key)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="PositionGuard",
                    data={
                        CONF_API_KEY: self._api_key,
                        CONF_BASE_URL: self._base_url,
                        CONF_GROUP_IDS: selected,
                    },
                )

        # Build a dropdown mapping group_id -> "Group Name (X members)".
        group_options = {
            g["id"]: g["name"] for g in self._groups
        }

        schema = vol.Schema(
            {
                vol.Required(CONF_GROUP_IDS): vol.All(
                    vol.Coerce(list),
                    [vol.In(group_options)],
                )
            }
        )

        return self.async_show_form(
            step_id="groups",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "group_count": str(len(self._groups)),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "PositionGuardOptionsFlow":
        """Return the options flow for existing entries."""
        return PositionGuardOptionsFlow(config_entry)


class PositionGuardOptionsFlow(config_entries.OptionsFlow):
    """Options flow: lets users reconfigure which groups are selected.

    Triggered by the 'Configure' button on the integration's card in HA UI.
    Does NOT re-prompt for API key — just group selection.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Store the entry we're reconfiguring."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Present the group re-selection form."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Re-fetch groups to show current names / catch any new groups.
        session = async_get_clientsession(self.hass)
        client = PositionGuardClient(
            session=session,
            api_key=self.config_entry.data[CONF_API_KEY],
            base_url=self.config_entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
        )

        try:
            groups = await client.list_groups()
        except PositionGuardAPIError as err:
            _LOGGER.error("Failed to fetch groups for options flow: %s", err)
            return self.async_abort(reason="cannot_connect")

        group_options = {g["id"]: g["name"] for g in groups}
        current = self.config_entry.data.get(CONF_GROUP_IDS, [])

        schema = vol.Schema(
            {
                vol.Required(CONF_GROUP_IDS, default=current): vol.All(
                    vol.Coerce(list),
                    [vol.In(group_options)],
                )
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)