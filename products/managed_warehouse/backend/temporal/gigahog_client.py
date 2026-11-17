"""A small REST client for the Gigahog calls that the data import writer makes.

Gigahog is a hoglake server, so the routes and bodies are hoglake's (`server/.../api/Routes.kt` and `Dto.kt` in
PostHog/hoglake). pyhoglake is not used, because it needs a newer pyarrow than this repository pins.

The writer reaches Gigahog on its public listener, which refuses every request without a valid tenant token. The
token comes from hogtower's OAuth token endpoint, in exchange for the writer's `hlw_` credential.

This module must not import the workflow module: the workflow imports it.
"""

from __future__ import annotations

import time
import uuid
import threading
from collections.abc import Mapping, Sequence
from dataclasses import field
from typing import Any
from urllib.parse import quote

import requests
import structlog

from posthog.dataclasses import frozen

LOGGER = structlog.get_logger(__name__)

_USER_AGENT = "posthog-data-imports-writer"
_REQUEST_TIMEOUT_SECONDS = 60.0
_TRANSIENT_ATTEMPTS = 4
_TRANSIENT_BACKOFF_SECONDS = 1.0
# Renewing early keeps a token from expiring while its request is on the way to Gigahog.
_TOKEN_RENEWAL_MARGIN_SECONDS = 60.0
# A server without this capability ignores the `org` of a containment mark and confines the namespace's files to
# `data/<namespace>/`, which would refuse every file under the imports layout.
ORG_MARKED_CONTAINMENT_CAPABILITY = "org-marked-containment-v1"


@frozen
class GigahogConfig:
    url: str
    catalog: str
    data_path: str
    token_url: str
    client_id: str
    client_secret: str = field(repr=False)
    mark_namespaces: bool = False


@frozen
class GigahogColumn:
    name: str
    type: str
    type_params: Mapping[str, Any] | None = None
    nullable: bool = True

    def to_wire(self) -> dict[str, Any]:
        body: dict[str, Any] = {"name": self.name, "type": self.type, "nullable": self.nullable}
        if self.type_params:
            body["type_params"] = dict(self.type_params)
        return body


@frozen
class GigahogContainment:
    field: str
    value: int
    org: str | None


@frozen
class GigahogNamespace:
    name: str
    containment: GigahogContainment | None


@frozen
class GigahogTable:
    namespace: str
    name: str
    table_uuid: uuid.UUID
    read_snapshot_id: int
    columns: tuple[GigahogColumn, ...]


@frozen
class GigahogFile:
    path: str
    record_count: int
    file_size_bytes: int
    footer_size: int

    def to_wire(self) -> dict[str, Any]:
        # Without column_stats the server registers the file with pending stats and fills them from the footer.
        return {
            "path": self.path,
            "record_count": self.record_count,
            "file_size_bytes": self.file_size_bytes,
            "footer_size": self.footer_size,
        }


@frozen
class GigahogCommit:
    snapshot_id: int
    ended_files: int | None


class GigahogError(Exception):
    def __init__(self, status_code: int, code: str, detail: str | None) -> None:
        super().__init__(f"Gigahog answered HTTP {status_code} {code}" + (f": {detail}" if detail else ""))
        self.status_code = status_code
        self.code = code
        self.detail = detail

    @property
    def retryable(self) -> bool:
        # 409 is a concurrent change and 410 an expired read snapshot, which a fresh read fixes. 429 and 5xx are the
        # server's own trouble. Every other 4xx refuses the request itself, so a repeat fails the same way.
        return self.status_code in (409, 410, 429) or self.status_code >= 500


class _WriterToken:
    """The writer's bearer token, exchanged for the `hlw_` credential and renewed before it expires."""

    def __init__(self, config: GigahogConfig, session: requests.Session) -> None:
        self._config = config
        self._session = session
        self._lock = threading.Lock()
        self._token: str | None = None
        self._renew_at = 0.0

    def get(self, *, renew: bool = False) -> str:
        with self._lock:
            if renew or self._token is None or time.monotonic() >= self._renew_at:
                self._exchange()
            assert self._token is not None
            return self._token

    def _exchange(self) -> None:
        response = self._session.post(
            self._config.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code >= 300:
            raise _error_from_response(response)
        body = response.json()
        self._token = body["access_token"]
        self._renew_at = time.monotonic() + max(float(body.get("expires_in", 0)) - _TOKEN_RENEWAL_MARGIN_SECONDS, 0)


class GigahogClient:
    def __init__(self, config: GigahogConfig, *, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._token = _WriterToken(config, self._session)
        self._base = f"{config.url.rstrip('/')}/v1/catalogs/{_segment(config.catalog)}"

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> GigahogClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def create_namespace(self, namespace: str) -> bool:
        """Create the namespace, and return False when it already exists."""
        try:
            self._request("POST", "/namespaces", json={"name": namespace, "message": "data imports"})
        except GigahogError as error:
            if error.code == "already_exists":
                return False
            raise
        return True

    def capabilities(self) -> frozenset[str]:
        return frozenset(self._request("GET", "").get("capabilities") or ())

    def mark_namespace(self, namespace: str, *, team_id: int, org: str) -> None:
        """Mark the namespace as the team's, with its org. Gigahog refuses this once the namespace has held a table."""
        self._request(
            "PUT",
            f"/namespaces/{_segment(namespace)}/containment",
            json={"field": "team_id", "value": int(team_id), "org": org},
        )

    def namespace(self, namespace: str) -> GigahogNamespace:
        body = self._request("GET", f"/namespaces/{_segment(namespace)}")
        containment = body.get("containment")
        return GigahogNamespace(
            name=body["name"],
            containment=None
            if containment is None
            else GigahogContainment(
                field=containment["field"], value=int(containment["value"]), org=containment.get("org")
            ),
        )

    def table(self, namespace: str, table: str) -> GigahogTable | None:
        try:
            body = self._request("GET", f"/namespaces/{_segment(namespace)}/tables/{_segment(table)}")
        except GigahogError as error:
            if error.status_code == 404:
                return None
            raise
        return _table_from_wire(body)

    def create_table(self, namespace: str, table: str, columns: Sequence[GigahogColumn]) -> GigahogTable:
        """Create the table, or return the existing one when a concurrent writer created it first."""
        try:
            self._request(
                "POST",
                f"/namespaces/{_segment(namespace)}/tables",
                json={"name": table, "columns": [column.to_wire() for column in columns], "message": "data imports"},
            )
        except GigahogError as error:
            if error.code != "already_exists":
                raise
        created = self.table(namespace, table)
        if created is None:
            raise GigahogError(404, "table_not_found", f"{namespace}.{table} is missing right after its creation")
        return created

    def replace_table_files(
        self,
        table: GigahogTable,
        files: Sequence[GigahogFile],
        *,
        idempotency_key: uuid.UUID,
        message: str,
    ) -> GigahogCommit:
        """End every live file of the table and add `files`, in one snapshot based on `table.read_snapshot_id`.

        The server keeps a receipt per idempotency key, so the identical body sent again after a lost response
        returns the first commit. A changed body under the same key is refused, so a caller that reads the table
        again must also use a new key.
        """
        guard = {"namespace": table.namespace, "table": table.name, "expected_table_uuid": str(table.table_uuid)}
        body = self._request(
            "POST",
            "/commit/replacements/prepared",
            json={
                "read_snapshot": table.read_snapshot_id,
                "idempotency_key": str(idempotency_key),
                "appends": [{**guard, "files": [file.to_wire() for file in files]}],
                "file_ends": [{**guard, "all_files": True}],
                "message": message,
            },
        )
        return GigahogCommit(snapshot_id=int(body["snapshot_id"]), ended_files=body.get("ended_files"))

    def _request(self, method: str, path: str, *, json: Any = None) -> Any:
        """Send the request, repeating it on a lost connection, a 5xx or a 429.

        Every call this client makes is safe to repeat with the same body: a create answers `already_exists` when
        the first attempt went through, and a commit carries an idempotency key. The author is left out, so the
        server records the token's subject, which is the only author it accepts from a tenant token.
        """
        renew_token = False
        for attempt in range(1, _TRANSIENT_ATTEMPTS + 1):
            headers = {"User-Agent": _USER_AGENT, "Authorization": f"Bearer {self._token.get(renew=renew_token)}"}
            renew_token = False
            try:
                response = self._session.request(
                    method, f"{self._base}{path}", json=json, headers=headers, timeout=_REQUEST_TIMEOUT_SECONDS
                )
            except requests.RequestException as transport_error:
                if attempt == _TRANSIENT_ATTEMPTS:
                    raise
                LOGGER.warning(
                    "Repeating a Gigahog request after a transport error", path=path, error=str(transport_error)
                )
            else:
                if response.status_code < 300:
                    return response.json() if response.content else None
                refusal = _error_from_response(response)
                # A token can expire between the check and the request, so one 401 renews it.
                renew_token = refusal.status_code == 401 and attempt == 1
                repeat = renew_token or refusal.status_code == 429 or refusal.status_code >= 500
                if not repeat or attempt == _TRANSIENT_ATTEMPTS:
                    raise refusal
                LOGGER.warning("Repeating a Gigahog request", path=path, status=refusal.status_code, code=refusal.code)
                if renew_token:
                    continue
            time.sleep(_TRANSIENT_BACKOFF_SECONDS * 2 ** (attempt - 1))
        raise AssertionError("unreachable")


def _segment(name: str) -> str:
    return quote(name, safe="")


def _error_from_response(response: requests.Response) -> GigahogError:
    code = f"http_{response.status_code}"
    detail: str | None = None
    try:
        body = response.json()
    except ValueError:
        detail = response.text[:500] or None
    else:
        if isinstance(body, dict):
            code = str(body.get("error") or code)
            detail = body.get("detail") or body.get("error_description")
    return GigahogError(response.status_code, code, detail)


def _table_from_wire(body: Mapping[str, Any]) -> GigahogTable:
    return GigahogTable(
        namespace=body["namespace"],
        name=body["name"],
        table_uuid=uuid.UUID(body["table_uuid"]),
        read_snapshot_id=int(body["read_snapshot_id"]),
        columns=tuple(
            GigahogColumn(
                name=column["name"],
                type=column["type"],
                type_params=column.get("type_params"),
                nullable=column.get("nullable", True),
            )
            for column in body["columns"]
        ),
    )
