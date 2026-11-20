"""A small REST client for the Gigahog calls that the data import writer makes.

Gigahog is a hoglake server, so the routes and bodies are hoglake's (`server/.../api/Routes.kt` and `Dto.kt` in
PostHog/hoglake). pyhoglake is not used, because it needs a newer pyarrow than this repository pins.

The writer reaches Gigahog on its public listener, which refuses every request without a valid token. For each team,
the writer exchanges its `hlw_` credential at hogtower's OAuth token endpoint for two credentials that cover only that
team: a Gigahog token, and an S3 session that reads the team's prepared files and writes its Gigahog prefix.

This module must not import the workflow module: the workflow imports it.
"""

from __future__ import annotations

import time
import uuid
import datetime as dt
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import field
from functools import partial
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
# A copy cannot renew its S3 session, so credentials are renewed while a copy started on them has this long to run.
_CREDENTIAL_RENEWAL_MARGIN_SECONDS = 300.0


@frozen
class GigahogConfig:
    url: str
    catalog: str
    data_path: str
    token_url: str
    client_id: str
    client_secret: str = field(repr=False)


@frozen
class GigahogStorageSession:
    access_key_id: str
    secret_access_key: str = field(repr=False)
    session_token: str = field(repr=False)
    region: str | None


@frozen
class _TeamCredentials:
    access_token: str = field(repr=False)
    storage: GigahogStorageSession
    renew_at_monotonic: float


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
    def __init__(self, status_code: int, code: str, detail: str | None, *, after_ambiguous_send: bool = False) -> None:
        super().__init__(f"Gigahog answered HTTP {status_code} {code}" + (f": {detail}" if detail else ""))
        self.status_code = status_code
        self.code = code
        self.detail = detail
        # An earlier send of the same request ended without a clear answer, and it may have been applied.
        self.after_ambiguous_send = after_ambiguous_send

    @property
    def retryable(self) -> bool:
        # A fresh read fixes a 409 or 410, and hogtower's team sync fixes `invalid_target`. 429 and 5xx are the server's
        # own trouble. Every other 4xx refuses the request itself, so a repeat fails the same way.
        return self.status_code in (409, 410, 429) or self.status_code >= 500 or self.code == "invalid_target"

    @property
    def refused(self) -> bool:
        # A 5xx can come after the server applied the request, and a 429 can come from a proxy. Another 4xx is a
        # refusal, unless an earlier send may have landed: a repeat's auth refusal precedes the receipt lookup.
        return 400 <= self.status_code < 500 and self.status_code != 429 and not self.after_ambiguous_send


class GigahogTokenError(GigahogError):
    """hogtower refused or failed the token exchange, which says nothing about what Gigahog applied."""

    @property
    def refused(self) -> bool:
        return False


# Per process and per team, so a team's syncs reuse its credentials, and one team's slow exchange blocks no other.
_team_credentials: dict[tuple[str, str, int], _TeamCredentials] = {}
_team_locks: dict[tuple[str, str, int], threading.Lock] = {}
_team_locks_lock = threading.Lock()


def _team_credentials_for(
    config: GigahogConfig, team_id: int, session: requests.Session, *, renew: bool = False
) -> _TeamCredentials:
    key = (config.token_url, config.client_id, team_id)
    with _team_locks_lock:
        team_lock = _team_locks.setdefault(key, threading.Lock())
    with team_lock:
        cached = _team_credentials.get(key)
        if renew or cached is None or time.monotonic() >= cached.renew_at_monotonic:
            cached = _exchange_for_team(config, team_id, session)
            _team_credentials[key] = cached
        return cached


def _exchange_for_team(config: GigahogConfig, team_id: int, session: requests.Session) -> _TeamCredentials:
    response, _ = _send_repeating_transient_failures(
        partial(
            session.post,
            config.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "team_id": str(team_id),
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        ),
        target="token",
    )
    if response.status_code >= 300:
        raise _error_from_response(response, error_type=GigahogTokenError)
    body = response.json()
    storage = body["storage"]
    storage_expires_at = dt.datetime.fromisoformat(storage["expiration"])
    if storage_expires_at.tzinfo is None:
        storage_expires_at = storage_expires_at.replace(tzinfo=dt.UTC)
    lifetime = min(
        float(body["expires_in"]),
        (storage_expires_at - dt.datetime.now(dt.UTC)).total_seconds(),
    )
    return _TeamCredentials(
        access_token=body["access_token"],
        storage=GigahogStorageSession(
            access_key_id=storage["access_key_id"],
            secret_access_key=storage["secret_access_key"],
            session_token=storage["session_token"],
            region=storage.get("region"),
        ),
        renew_at_monotonic=time.monotonic() + max(lifetime - _CREDENTIAL_RENEWAL_MARGIN_SECONDS, 0),
    )


class GigahogClient:
    """Gigahog calls for one team, with that team's token."""

    def __init__(self, config: GigahogConfig, *, team_id: int, session: requests.Session | None = None) -> None:
        self._config = config
        self._team_id = team_id
        self._session = session or requests.Session()
        self._base = f"{config.url.rstrip('/')}/v1/catalogs/{_segment(config.catalog)}"

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> GigahogClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def storage_session(self, *, fresh: bool = False) -> GigahogStorageSession:
        """The team's S3 session. A `fresh` one has its full lifetime, for a copy that may take long."""
        return _team_credentials_for(self._config, self._team_id, self._session, renew=fresh).storage

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
        """Send the request, repeating it on a lost connection, a 5xx or a 429, and renewing the token on a 401.

        Every call this client makes is safe to repeat with the same body: a create answers `already_exists` when
        the first attempt went through, and a commit carries an idempotency key. The author is left out, so the
        server records the token's subject, which is the only author it accepts from a tenant token.
        """
        renewed = False
        ambiguous = False
        while True:
            token = _team_credentials_for(self._config, self._team_id, self._session, renew=renewed).access_token
            response, ambiguous_send = _send_repeating_transient_failures(
                partial(
                    self._session.request,
                    method,
                    f"{self._base}{path}",
                    json=json,
                    headers={"User-Agent": _USER_AGENT, "Authorization": f"Bearer {token}"},
                    timeout=_REQUEST_TIMEOUT_SECONDS,
                ),
                target=path,
            )
            ambiguous = ambiguous or ambiguous_send
            if response.status_code < 300:
                return response.json() if response.content else None
            refusal = _error_from_response(response, after_ambiguous_send=ambiguous)
            if refusal.status_code != 401 or renewed:
                raise refusal
            LOGGER.warning("Renewing the Gigahog token after a 401", path=path)
            renewed = True


def _send_repeating_transient_failures(
    send: Callable[[], requests.Response], *, target: str
) -> tuple[requests.Response, bool]:
    """Send, and repeat on a lost connection, a 5xx or a 429.

    Return the last response, whatever its status, and whether an earlier send ended without a clear answer.
    """
    for attempt in range(1, _TRANSIENT_ATTEMPTS + 1):
        try:
            response = send()
        except requests.RequestException as transport_error:
            if attempt == _TRANSIENT_ATTEMPTS:
                raise
            LOGGER.warning(
                "Repeating a Gigahog request after a transport error", target=target, error=str(transport_error)
            )
        else:
            transient = response.status_code == 429 or response.status_code >= 500
            if not transient or attempt == _TRANSIENT_ATTEMPTS:
                return response, attempt > 1
            LOGGER.warning("Repeating a Gigahog request", target=target, status=response.status_code)
        time.sleep(_TRANSIENT_BACKOFF_SECONDS * 2 ** (attempt - 1))
    raise AssertionError("unreachable")


def _segment(name: str) -> str:
    return quote(name, safe="")


def _error_from_response(
    response: requests.Response,
    *,
    error_type: type[GigahogError] = GigahogError,
    after_ambiguous_send: bool = False,
) -> GigahogError:
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
    return error_type(response.status_code, code, detail, after_ambiguous_send=after_ambiguous_send)


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
