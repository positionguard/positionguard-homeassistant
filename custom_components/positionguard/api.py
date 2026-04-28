"""API client for PositionGuard REST API."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class PositionGuardAPIError(Exception):
    """Base exception for API errors."""


class PositionGuardAuthError(PositionGuardAPIError):
    """Authentication failed (invalid or revoked API key)."""


class PositionGuardNotFoundError(PositionGuardAPIError):
    """Resource not found or caller not authorized to see it."""


class PositionGuardClient:
    """Async client for the PositionGuard REST API.

    Uses a single aiohttp session per HA integration instance.
    All methods are async because HA's event loop is async.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        base_url: str,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }

    async def _get(self, path: str) -> Any:
        """Internal GET helper. Handles common error cases."""
        url = f"{self._base_url}{path}"
        _LOGGER.debug("GET %s", url)
        try:
            async with self._session.get(
                url, headers=self._headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                _LOGGER.debug("Response status %d for %s", resp.status, url)
                if resp.status == 401:
                    raise PositionGuardAuthError("invalid or revoked API key")
                if resp.status == 404:
                    raise PositionGuardNotFoundError(f"not found: {path}")
                if resp.status == 429:
                    retry_after = resp.headers.get("Retry-After", "60")
                    raise PositionGuardAPIError(
                        f"rate limit exceeded; retry after {retry_after}s"
                    )
                if resp.status >= 500:
                    raise PositionGuardAPIError(f"server error {resp.status}")
                if resp.status != 200:
                    raise PositionGuardAPIError(f"unexpected status {resp.status}")
                return await resp.json()
        except aiohttp.ClientError as err:
            raise PositionGuardAPIError(f"network error: {err}") from err

    async def list_groups(self) -> list[dict[str, Any]]:
        """GET /groups — list groups the authenticated user belongs to."""
        return await self._get("/groups")

    async def list_group_members(self, group_id: str) -> list[dict[str, Any]]:
        """GET /groups/{id}/members — members with presence state."""
        return await self._get(f"/groups/{group_id}/members")

    async def list_group_areas(self, group_id: str) -> list[dict[str, Any]]:
        """GET /groups/{id}/areas — areas linked to a group."""
        return await self._get(f"/groups/{group_id}/areas")

    async def get_user_presence(self, user_id: str) -> dict[str, Any]:
        """GET /users/{id}/presence — areas a user is currently inside."""
        return await self._get(f"/users/{user_id}/presence")
