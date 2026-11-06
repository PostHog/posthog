from collections.abc import Iterator
from dataclasses import field
from typing import Any

import requests
from requests.adapters import BaseAdapter
from requests.models import PreparedRequest

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
        for prefix in ("https://", "http://"):
            self._session.mount(prefix, _ReadOnlyAdapter(self._session.get_adapter(prefix)))

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
        try:
            response = self._session.get(f"{self._base_url}{path}", params=params, timeout=_TIMEOUT_SECONDS)
        except requests.RequestException as error:
            raise FivetranAPIError(0, f"could not reach Fivetran ({type(error).__name__})") from error
        if not response.ok:
            raise _error_for(response)
        try:
            body = response.json()
        except ValueError as error:
            raise FivetranAPIError(response.status_code, "the response was not JSON") from error
        if not isinstance(body, dict):
            raise FivetranAPIError(response.status_code, "the response was not a JSON object")
        return body.get("data") or {}


class FivetranWriteBlockedError(Exception):
    pass


class _ReadOnlyAdapter(BaseAdapter):
    """Refuses every request that is not a GET, then hands the rest to the wrapped adapter."""

    def __init__(self, inner: BaseAdapter) -> None:
        super().__init__()
        self._inner = inner

    def send(self, request: PreparedRequest, *args: Any, **kwargs: Any) -> requests.Response:
        # The key opens the customer's live account, so a write must fail here even if a caller adds one.
        if (request.method or "").upper() != "GET":
            raise FivetranWriteBlockedError(
                f"Refusing {request.method} {request.url}: the Fivetran client is read-only."
            )
        return self._inner.send(request, *args, **kwargs)

    def close(self) -> None:
        self._inner.close()


def _error_for(response: requests.Response) -> FivetranAPIError:
    try:
        body = response.json()
    except ValueError:
        body = None
    message = str((body.get("message") if isinstance(body, dict) else None) or response.reason)
    if response.status_code in (401, 403):
        return FivetranAuthError(response.status_code, message)
    return FivetranAPIError(response.status_code, message)
