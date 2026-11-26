"""Hogtower adapter for the managed-warehouse control plane.

Hogtower is the management plane that replaces duckgres' control plane. When
``HOGTOWER_API_URL`` is set, every control-plane call PostHog makes goes to hogtower's
canonical ``/api/v2`` routes instead of duckgres' ``/api/v1`` routes; when it is unset
nothing here runs and the duckgres client is unchanged. Flipping the env var is the
switch.

Callers keep speaking the duckgres v1 vocabulary (``_request("POST", org, "/provision")``
and friends). :func:`request` maps each of those calls onto its v2 route and translates
the v2 response back into the exact v1 body the callers and the UI already parse, so no
caller needs to know which control plane answered.

The return value quacks like a ``requests.Response`` (``status_code``, ``json()``,
``text``) so both transports share the callers' error handling. Transport errors
(``requests.Timeout``, ``requests.ConnectionError``, ...) propagate unchanged.

Deliberately free of DRF: ``cp_teams`` uses this from the data-import sink hot path.
"""

from __future__ import annotations

import re
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from django.conf import settings

import structlog

from posthog.dataclasses import frozen
from posthog.security.outbound_proxy import internal_requests

logger = structlog.get_logger(__name__)

INTERNAL_SECRET_HEADER = "X-Hogtower-Internal-Secret"

# duckgres' message for DELETE /orgs/:id while the warehouse still exists.
_WAREHOUSE_STILL_EXISTS = (
    "warehouse still exists — deprovision it and wait for teardown to complete before deleting the org"
)

_TEAM_PATH = re.compile(r"/teams/(?P<team_id>[^/]+)")
_SERVICE_GRANT_PATH = re.compile(r"/service-grants/(?P<credential_id>[^/]+)")
_HOGLAKE_CREDENTIAL_PATH = re.compile(r"/hoglake-credentials/(?P<credential_id>[^/]+)(?P<rotate>/rotate)?")


def is_configured() -> bool:
    """Whether control-plane calls go to hogtower (``HOGTOWER_API_URL`` is set)."""
    return bool(getattr(settings, "HOGTOWER_API_URL", None))


@frozen(kw_only=False)
class TranslatedResponse:
    """A control-plane answer in duckgres v1 shape, duck-typed like ``requests.Response``."""

    status_code: int
    body: Any

    def json(self) -> Any:
        return self.body

    @property
    def text(self) -> str:
        return json.dumps(self.body, default=str)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


def _send(
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    params: dict | None = None,
    timeout: int | float,
) -> TranslatedResponse:
    """One raw call to ``{HOGTOWER_API_URL}/api/v2{path}``."""
    base_url = str(getattr(settings, "HOGTOWER_API_URL", "") or "").rstrip("/")
    token = getattr(settings, "HOGTOWER_INTERNAL_SECRET", None)
    headers: dict[str, str] = {}
    if token:
        headers[INTERNAL_SECRET_HEADER] = token
    resp = internal_requests.request(
        method, f"{base_url}/api/v2{path}", json=json_body, params=params, headers=headers, timeout=timeout
    )
    try:
        body = resp.json()
    except ValueError:
        body = {"error": resp.text[:500]}
    return TranslatedResponse(resp.status_code, body)


@frozen(kw_only=False)
class _Call:
    """One v1-vocabulary call being translated."""

    org_id: str
    json_body: dict | None
    params: dict | None
    timeout: int | float

    @property
    def warehouse(self) -> str:
        return f"/warehouses/{quote(self.org_id, safe='')}"

    def send(self, method: str, path: str, json_body: dict | None = None, params: dict | None = None):
        return _send(method, path, json_body=json_body, params=params, timeout=self.timeout)


def _bad_request(message: str) -> TranslatedResponse:
    return TranslatedResponse(400, {"error": message})


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


# --- warehouses -------------------------------------------------------------------------


def _provision(call: _Call) -> TranslatedResponse:
    """v1 POST /orgs/:id/provision -> v2 POST /warehouses (202; root password returned once)."""
    body = call.json_body or {}
    team: dict[str, Any] = {"id": body.get("team_id") or body.get("default_team_id")}
    if body.get("schema_name"):
        team["schema_name"] = body["schema_name"]
    v2_body: dict[str, Any] = {"id": call.org_id, "database_name": body.get("database_name"), "team": team}
    # ducklake.enabled is implied by v2 (always DuckLake).
    for key in ("metadata_store", "data_store", "trino"):
        if body.get(key) is not None:
            v2_body[key] = body[key]
    resp = call.send("POST", "/warehouses", json_body=v2_body)
    if not resp.ok or not isinstance(resp.body, dict):
        return resp
    root = _dict(resp.body.get("root"))
    out: dict[str, Any] = {
        "status": "provisioning started",
        "org": call.org_id,
        "username": root.get("username") or "root",
        "password": root.get("password", ""),
    }
    bucket = _dict(_dict(resp.body.get("warehouse")).get("data_store")).get("bucket_name")
    if bucket:
        out["bucket"] = bucket
    return TranslatedResponse(resp.status_code, out)


def _deprovision(call: _Call) -> TranslatedResponse:
    """v1 POST /orgs/:id/deprovision -> v2 DELETE /warehouses/:id (202)."""
    resp = call.send("DELETE", call.warehouse)
    if not resp.ok or not isinstance(resp.body, dict):
        return resp
    return TranslatedResponse(
        resp.status_code, {"status": resp.body.get("status") or "deprovisioning started", "org": call.org_id}
    )


def _status(call: _Call) -> TranslatedResponse:
    """v1 GET /orgs/:id/warehouse/status -> v2 GET /warehouses/:id (detail)."""
    resp = call.send("GET", call.warehouse)
    if not resp.ok or not isinstance(resp.body, dict):
        return resp
    warehouse = _dict(resp.body.get("warehouse"))
    out: dict[str, Any] = {
        key: warehouse.get(key, "")
        for key in (
            "org_id",
            "state",
            "status_message",
            "s3_state",
            "metadata_store_state",
            "identity_state",
            "secrets_state",
        )
    }
    for key in ("ready_at", "failed_at"):
        if warehouse.get(key) is not None:
            out[key] = warehouse[key]
    if warehouse.get("state") == "ready":
        connection = _dict(resp.body.get("connection"))
        out["connection"] = {
            "host": connection.get("host", ""),
            "port": connection.get("port", 0),
            "database": connection.get("database") or warehouse.get("database_name", ""),
            "username": connection.get("username") or "root",
        }
    data_store = _dict(warehouse.get("data_store"))
    if data_store.get("bucket_name"):
        out["bucket"] = data_store["bucket_name"]
    if data_store.get("prefix"):
        out["bucket_prefix"] = data_store["prefix"]
    return TranslatedResponse(resp.status_code, out)


def _delete_org(call: _Call) -> TranslatedResponse:
    """v1 DELETE /orgs/:id: drop a torn-down warehouse's record so its name can be reused.

    hogtower has no separate record to drop: a warehouse whose teardown finished is
    soft-deleted (its name is free and v2 answers 404 for it). v2 DELETE /warehouses/:id
    is deprovision, which this must never trigger, so the duckgres semantics are
    reproduced from the detail read: gone -> deleted, still live -> 409.
    """
    resp = call.send("GET", call.warehouse)
    if resp.status_code == 404:
        return TranslatedResponse(200, {"deleted": call.org_id})
    if not resp.ok or not isinstance(resp.body, dict):
        return resp
    if _dict(resp.body.get("warehouse")).get("state") == "deleted":
        return TranslatedResponse(200, {"deleted": call.org_id})
    return TranslatedResponse(409, {"error": _WAREHOUSE_STILL_EXISTS})


def _reset_password(call: _Call) -> TranslatedResponse:
    """v1 POST /orgs/:id/reset-password -> v2 POST /warehouses/:id/root-password (same body)."""
    return call.send("POST", f"{call.warehouse}/root-password")


def _check_name(call: _Call) -> TranslatedResponse:
    """v1 GET /database-name/check?name= -> v2 GET /database-names/:name?org_id=.

    hogtower reserves a name for the org whose warehouse carried it, and without org_id it
    answers for a new org: the asking org's own earlier names would read as taken.
    """
    name = (call.params or {}).get("name")
    if not name:
        return _bad_request("name query parameter is required")
    params = {"org_id": call.org_id} if call.org_id else None
    resp = call.send("GET", f"/database-names/{quote(str(name), safe='')}", params=params)
    if resp.ok and isinstance(resp.body, dict) and not resp.body.get("reason"):
        # v1 omits an empty reason.
        resp.body.pop("reason", None)
    return resp


# --- teams ------------------------------------------------------------------------------


def _list_teams(call: _Call) -> TranslatedResponse:
    """v1 GET /orgs/:id/teams -> v2 GET /warehouses/:id/teams.

    v1 also carries the warehouse's data_imports_table_naming_version; when the v2 teams
    body does not, it is read from the warehouse detail.
    """
    resp = call.send("GET", f"{call.warehouse}/teams")
    if not resp.ok or not isinstance(resp.body, dict):
        return resp
    out = {"teams": resp.body.get("teams") or []}
    naming_version = resp.body.get("data_imports_table_naming_version")
    if not naming_version:
        detail = call.send("GET", call.warehouse)
        if not detail.ok or not isinstance(detail.body, dict):
            return detail
        naming_version = _dict(detail.body.get("warehouse")).get("data_imports_table_naming_version")
    out["data_imports_table_naming_version"] = naming_version or ""
    return TranslatedResponse(resp.status_code, out)


def _list_all_teams(call: _Call) -> TranslatedResponse:
    """v1 GET /teams (every warehouse) -> v2 GET /teams."""
    resp = call.send("GET", "/teams")
    if not resp.ok or not isinstance(resp.body, dict) or not isinstance(resp.body.get("teams"), list):
        return resp
    teams = [
        {**row, "org_id": row.get("org_id") or row.get("warehouse_id")} if isinstance(row, dict) else row
        for row in resp.body["teams"]
    ]
    return TranslatedResponse(resp.status_code, {"teams": teams})


def _unwrap_team(resp: TranslatedResponse) -> TranslatedResponse:
    """v2 answers team writes with {"team": row}; v1 answered with the row itself."""
    if resp.ok and isinstance(resp.body, dict) and isinstance(resp.body.get("team"), dict):
        return TranslatedResponse(resp.status_code, resp.body["team"])
    return resp


def _upsert_team(call: _Call) -> TranslatedResponse:
    """v1 POST /orgs/:id/teams (upsert, team_id in body) -> v2 PUT /warehouses/:id/teams/:team_id."""
    body = call.json_body or {}
    team_id = body.get("team_id")
    if not team_id:
        return _bad_request("team_id is required (a positive PostHog team id)")
    return _unwrap_team(call.send("PUT", f"{call.warehouse}/teams/{quote(str(team_id), safe='')}", json_body=body))


def _update_team(call: _Call, team_id: str) -> TranslatedResponse:
    """v1 PUT /orgs/:id/teams/:team_id (presence-aware partial update) -> v2 PUT upsert.

    The v2 upsert requires schema_name; absent fields are preserved. So the team's current
    schema_name is read first and sent alongside exactly the fields the caller passed.
    A team the warehouse does not have is a 404, as in v1 (never created by an update).
    """
    listed = call.send("GET", f"{call.warehouse}/teams")
    if not listed.ok or not isinstance(listed.body, dict):
        return listed
    existing = next(
        (
            row
            for row in listed.body.get("teams") or []
            if isinstance(row, dict) and str(row.get("team_id")) == str(team_id)
        ),
        None,
    )
    if existing is None:
        return TranslatedResponse(404, {"error": "team not found"})
    body = {"schema_name": existing.get("schema_name"), **(call.json_body or {})}
    return _unwrap_team(call.send("PUT", f"{call.warehouse}/teams/{quote(team_id, safe='')}", json_body=body))


def _delete_team(call: _Call, team_id: str) -> TranslatedResponse:
    """v1 DELETE /orgs/:id/teams/:team_id -> v2 DELETE /warehouses/:id/teams/:team_id."""
    resp = call.send("DELETE", f"{call.warehouse}/teams/{quote(team_id, safe='')}")
    if resp.ok and isinstance(resp.body, dict):
        return TranslatedResponse(resp.status_code, {**resp.body, "org": call.org_id})
    return resp


# --- Trino ------------------------------------------------------------------------------


def _trino(call: _Call) -> TranslatedResponse:
    """v1 GET /orgs/:id/trino -> v2 GET /warehouses/:id/trino.

    v2 returns {"trino": <tenancy row>, "live": <org detail>}; ``live`` is the duckgres v1
    body (enabled + status with catalog and connection) and is returned as-is. Without
    ``live`` only the tenancy row is known: it is projected onto the v1 shape with no
    catalog or connection, which every caller treats as "Trino not ready".
    """
    resp = call.send("GET", f"{call.warehouse}/trino")
    if not resp.ok or not isinstance(resp.body, dict):
        return resp
    tenancy = resp.body.get("trino")
    live = resp.body.get("live")
    if isinstance(live, dict) and isinstance(live.get("enabled"), bool):
        # The live body is duckgres's and knows nothing of hoglake: the tenancy row says
        # which backend the catalog is and whether hoglake's catalog exists yet.
        detail = dict(live)
        if isinstance(tenancy, dict):
            if tenancy.get("backend"):
                detail["backend"] = tenancy["backend"]
            if "hoglake_initialized" in tenancy:
                detail["hoglake_initialized"] = tenancy["hoglake_initialized"] is True
        return TranslatedResponse(resp.status_code, detail)
    if not isinstance(tenancy, dict) or tenancy.get("enabled") is not True:
        out: dict[str, Any] = {"enabled": False}
        if isinstance(tenancy, dict) and tenancy.get("backend"):
            out["backend"] = tenancy["backend"]
        return TranslatedResponse(resp.status_code, out)
    trino_status: dict[str, Any] = {
        "org": tenancy.get("org_id") or call.org_id,
        "backend": tenancy.get("backend", ""),
        "tier": tenancy.get("tier", ""),
        "state": tenancy.get("state") or "pending",
        "status_message": tenancy.get("status_message", ""),
    }
    for key in ("ready_at", "failed_at"):
        if tenancy.get(key) is not None:
            trino_status[key] = tenancy[key]
    return TranslatedResponse(
        resp.status_code,
        {
            "enabled": True,
            "backend": tenancy.get("backend", ""),
            "hoglake_initialized": tenancy.get("hoglake_initialized") is True,
            "status": trino_status,
        },
    )


# --- service credentials ----------------------------------------------------------------


def _mint_credential(call: _Call) -> TranslatedResponse:
    """v1 POST /orgs/:id/service-credentials -> v2 POST /warehouses/:id/service-credentials (same body)."""
    return call.send("POST", f"{call.warehouse}/service-credentials", json_body=call.json_body)


def _refresh_credential(call: _Call) -> TranslatedResponse:
    """v1 POST /orgs/:id/service-credentials/refresh -> v2 POST .../service-credentials/:cid/refresh."""
    body = dict(call.json_body or {})
    credential_id = body.pop("credential_id", None)
    if not credential_id:
        return _bad_request("credential_id is required")
    return call.send(
        "POST",
        f"{call.warehouse}/service-credentials/{quote(str(credential_id), safe='')}/refresh",
        json_body=body,
    )


def _revoke_credential(call: _Call, credential_id: str) -> TranslatedResponse:
    """v1 DELETE /orgs/:id/service-grants/:cid -> v2 DELETE /warehouses/:id/service-credentials/:cid.

    Both answer {"revoked": "<cid>"} on success, so the body passes through.
    """
    return call.send("DELETE", f"{call.warehouse}/service-credentials/{quote(credential_id, safe='')}")


# --- hoglake credentials -------------------------------------------------------------
#
# Customer OAuth clients for hoglake (hlc_<id> + a secret shown once), exchanged at
# hogtower's public /oauth/token. hogtower-only: duckgres has no equivalent, so the
# v1-style paths below exist only in this adapter and views refuse them without hogtower.


def _list_hoglake_credentials(call: _Call) -> TranslatedResponse:
    """GET /hoglake-credentials -> v2 GET /warehouses/:id/hoglake-credentials (never a secret).

    ``owner_user_uuid`` keeps only that member's personal credentials; nothing else is forwarded.
    """
    owner = (call.params or {}).get("owner_user_uuid")
    params = {"owner_user_uuid": str(owner)} if owner else None
    return call.send("GET", f"{call.warehouse}/hoglake-credentials", params=params)


def _create_hoglake_credential(call: _Call) -> TranslatedResponse:
    """POST /hoglake-credentials -> v2 POST /warehouses/:id/hoglake-credentials (secret once)."""
    return call.send("POST", f"{call.warehouse}/hoglake-credentials", json_body=call.json_body)


def _hoglake_credential(call: _Call, method: str, credential_id: str, rotate: bool) -> TranslatedResponse:
    """POST /hoglake-credentials/:cid/rotate (secret once) and DELETE /hoglake-credentials/:cid (revoke).

    ``owner_user_uuid`` (rotate: body, revoke: params) names the acting member, and hogtower then
    acts only on that member's own credentials. Without it the call acts as an organization admin.
    Nothing else is forwarded.
    """
    path = f"{call.warehouse}/hoglake-credentials/{quote(credential_id, safe='')}"
    if rotate and method == "POST":
        owner = (call.json_body or {}).get("owner_user_uuid")
        return call.send("POST", f"{path}/rotate", json_body={"owner_user_uuid": str(owner)} if owner else None)
    if not rotate and method == "DELETE":
        owner = (call.params or {}).get("owner_user_uuid")
        return call.send("DELETE", path, params={"owner_user_uuid": str(owner)} if owner else None)
    return _not_supported(method, f"/hoglake-credentials/{credential_id}{'/rotate' if rotate else ''}")


def _not_supported(method: str, path: str) -> TranslatedResponse:
    """A v1 call this adapter has no v2 mapping for: 501, never forwarded to hogtower.

    501 (not 500) because nothing failed: the hogtower control plane simply does not serve
    this v1 operation, which is the same status ``_request`` uses when no control plane is
    configured at all. Only the method and path are logged; bodies may carry secrets.
    """
    logger.warning("hogtower_adapter_unmapped_route", method=method, path=path or "/")
    return TranslatedResponse(501, {"error": f"not supported by the hogtower control plane: {method} {path or '/'}"})


# --- passthroughs -----------------------------------------------------------------------


def _org_passthrough(suffix: str) -> Callable[[_Call], TranslatedResponse]:
    def handle(call: _Call) -> TranslatedResponse:
        return call.send("GET", f"{call.warehouse}{suffix}", params=call.params)

    return handle


def _discovery_warehouses(call: _Call) -> TranslatedResponse:
    """v1 GET /warehouses (discovery) -> v2 GET /discovery/warehouses (same body)."""
    return call.send("GET", "/discovery/warehouses")


# Org-scoped v1 paths ("/..." under /api/v1/orgs/:id) keyed by (method, path).
_ORG_ROUTES: dict[tuple[str, str], Callable[[_Call], TranslatedResponse]] = {
    ("POST", "/provision"): _provision,
    ("POST", "/deprovision"): _deprovision,
    ("GET", "/warehouse/status"): _status,
    ("POST", "/reset-password"): _reset_password,
    ("GET", "/teams"): _list_teams,
    ("POST", "/teams"): _upsert_team,
    ("GET", "/trino"): _trino,
    ("POST", "/service-credentials"): _mint_credential,
    ("POST", "/service-credentials/refresh"): _refresh_credential,
    ("GET", "/hoglake-credentials"): _list_hoglake_credentials,
    ("POST", "/hoglake-credentials"): _create_hoglake_credential,
    ("GET", "/monitoring/snapshot"): _org_passthrough("/monitoring/snapshot"),
    ("GET", "/monitoring/series"): _org_passthrough("/monitoring/series"),
    ("GET", "/monitoring/trino/snapshot"): _org_passthrough("/monitoring/trino/snapshot"),
    ("GET", "/monitoring/trino/series"): _org_passthrough("/monitoring/trino/series"),
}

# Global v1 paths (under /api/v1) keyed by (method, path).
_GLOBAL_ROUTES: dict[tuple[str, str], Callable[[_Call], TranslatedResponse]] = {
    ("GET", "teams"): _list_all_teams,
    ("GET", "database-name/check"): _check_name,
    ("GET", "warehouses"): _discovery_warehouses,
}


def request(
    method: str,
    organization_id: object,
    path: str,
    *,
    json_body: dict | None = None,
    params: dict | None = None,
    timeout: int | float = 30,
) -> TranslatedResponse:
    """Serve one duckgres-v1-vocabulary control-plane call from hogtower's v2 API.

    ``path`` follows ``presentation.views._request``: "" is the org resource itself,
    "/..." is org-scoped, anything else is a global path.
    """
    method = method.upper()
    call = _Call(org_id=str(organization_id), json_body=json_body, params=params, timeout=timeout)
    handler: Callable[[_Call], TranslatedResponse] | None
    if path == "":
        handler = _delete_org if method == "DELETE" else None
    elif path.startswith("/"):
        handler = _ORG_ROUTES.get((method, path))
        team = _TEAM_PATH.fullmatch(path)
        if handler is None and team is not None:
            team_id = team.group("team_id")
            if method == "PUT":
                return _update_team(call, team_id)
            if method == "DELETE":
                return _delete_team(call, team_id)
        grant = _SERVICE_GRANT_PATH.fullmatch(path)
        if handler is None and grant is not None and method == "DELETE":
            return _revoke_credential(call, grant.group("credential_id"))
        hoglake = _HOGLAKE_CREDENTIAL_PATH.fullmatch(path)
        if handler is None and hoglake is not None:
            return _hoglake_credential(call, method, hoglake.group("credential_id"), bool(hoglake.group("rotate")))
    else:
        handler = _GLOBAL_ROUTES.get((method, path))
    if handler is None:
        return _not_supported(method, path)
    return handler(call)


# --- hogtower-only routes -----------------------------------------------------------------
# No duckgres v1 counterpart, so no translation: callers check is_configured() first.

MEMBER_TEAMS_TIMEOUT_SECONDS = 10


def _member_path(organization_id: object, user_uuid: object) -> str:
    return f"/warehouses/{quote(str(organization_id), safe='')}/members/{quote(str(user_uuid), safe='')}"


def list_warehouses(*, timeout: int | float = 30) -> TranslatedResponse:
    """v2 GET /warehouses: every warehouse hogtower manages, as ``{"warehouses": [...]}``."""
    return _send("GET", "/warehouses", timeout=timeout)


def list_members(organization_id: object, *, timeout: int | float = MEMBER_TEAMS_TIMEOUT_SECONDS) -> TranslatedResponse:
    """v2 GET /warehouses/:id/members: the members hogtower holds who are not removed."""
    return _send("GET", f"/warehouses/{quote(str(organization_id), safe='')}/members", timeout=timeout)


def put_member_teams(
    organization_id: object,
    user_uuid: object,
    teams: dict[int, str],
    version: int,
    *,
    timeout: int | float = MEMBER_TEAMS_TIMEOUT_SECONDS,
) -> TranslatedResponse:
    """v2 PUT /warehouses/:id/members/:user_uuid/teams: the member's whole team set.

    ``teams`` maps a team id to ``"read"`` or ``"write"``. hogtower keeps the push with
    the highest ``version`` and answers 409 for an older one.
    """
    body = {"teams": {str(team_id): perm for team_id, perm in teams.items()}, "version": version}
    return _send("PUT", f"{_member_path(organization_id, user_uuid)}/teams", json_body=body, timeout=timeout)


def remove_member(
    organization_id: object,
    user_uuid: object,
    version: int,
    *,
    timeout: int | float = MEMBER_TEAMS_TIMEOUT_SECONDS,
) -> TranslatedResponse:
    """v2 DELETE /warehouses/:id/members/:user_uuid: tombstone the member at ``version``.

    hogtower revokes every team credential the member owns in the same transaction.
    """
    return _send("DELETE", _member_path(organization_id, user_uuid), json_body={"version": version}, timeout=timeout)
