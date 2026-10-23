from collections.abc import Iterator
from dataclasses import field
from typing import Any

import requests

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import make_tracked_session

FIVETRAN_API_URL = "https://api.fivetran.com/v1"
_PAGE_LIMIT = 1000
_TIMEOUT_SECONDS = (10, 60)


@frozen
class FivetranCredentials:
    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)


class FivetranAPIError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Fivetran API returned {status_code}: {message}")
        self.status_code = status_code


class FivetranAuthError(FivetranAPIError):
    pass


class FivetranClient:
    """Read-only client for the Fivetran REST API. It never calls a write endpoint."""

    def __init__(self, credentials: FivetranCredentials, base_url: str = FIVETRAN_API_URL) -> None:
        self._base_url = base_url
        self._session = make_tracked_session(
            headers={"Accept": "application/json;version=2"},
            redact_values=(credentials.api_key, credentials.api_secret),
            # Response bodies carry connection config, so keep them out of HTTP sample capture.
            capture=False,
        )
        self._session.auth = (credentials.api_key, credentials.api_secret)

    def get_account_info(self) -> dict[str, Any]:
        return self._get("/account/info")

    def list_groups(self) -> list[dict[str, Any]]:
        return list(self._paginate("/groups"))

    def get_destination(self, destination_id: str) -> dict[str, Any]:
        return self._get(f"/destinations/{destination_id}")

    def list_connections(self) -> list[dict[str, Any]]:
        return list(self._paginate("/connections"))

    def get_connection(self, connection_id: str) -> dict[str, Any]:
        return self._get(f"/connections/{connection_id}")

    def get_schema_config(self, connection_id: str) -> dict[str, Any]:
        return self._get(f"/connections/{connection_id}/schemas")

    def _paginate(self, path: str) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": _PAGE_LIMIT}
            if cursor:
                params["cursor"] = cursor
            data = self._get(path, params=params)
            yield from data.get("items") or []
            cursor = data.get("next_cursor")
            if not cursor:
                return

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._session.get(f"{self._base_url}{path}", params=params, timeout=_TIMEOUT_SECONDS)
        if not response.ok:
            raise _error_for(response)
        return response.json().get("data") or {}


def _error_for(response: requests.Response) -> FivetranAPIError:
    try:
        message = str(response.json().get("message") or response.reason)
    except ValueError:
        message = response.reason
    if response.status_code in (401, 403):
        return FivetranAuthError(response.status_code, message)
    return FivetranAPIError(response.status_code, message)
