from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from django.conf import settings
from django.core.cache import cache

from rest_framework import status
from rest_framework.response import Response

_STATE_KEY_PREFIX = "managed-warehouse:local-dev:org:"
_ORG_INDEX_KEY = "managed-warehouse:local-dev:org-index"
_LOCAL_PASSWORD = "posthog"
_METRIC_UNITS = {
    "query_rate": "queries/s",
    "error_ratio": "ratio",
    "duration_p50": "seconds",
    "duration_p95": "seconds",
    "sessions_active": "count",
    "s3_bytes_rate": "bytes/s",
    "acquire_p95": "seconds",
    "acquire_by_source": "count",
    "storage_bytes": "bytes",
    "worker_crash_rate": "crashes/s",
}


def _state_key(organization_id: str) -> str:
    return f"{_STATE_KEY_PREFIX}{organization_id}"


def _get_state(organization_id: str) -> dict[str, object] | None:
    value = cache.get(_state_key(organization_id))
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def _set_state(organization_id: str, state: dict[str, object]) -> None:
    cache.set(_state_key(organization_id), state, timeout=None)
    organization_ids = set(cache.get(_ORG_INDEX_KEY) or [])
    organization_ids.add(organization_id)
    cache.set(_ORG_INDEX_KEY, sorted(organization_ids), timeout=None)


def _delete_state(organization_id: str) -> None:
    cache.delete(_state_key(organization_id))
    organization_ids = set(cache.get(_ORG_INDEX_KEY) or [])
    organization_ids.discard(organization_id)
    cache.set(_ORG_INDEX_KEY, sorted(organization_ids), timeout=None)


def _teams(state: dict[str, object]) -> list[dict[str, object]]:
    value = state.get("teams")
    return cast(list[dict[str, object]], value) if isinstance(value, list) else []


def _team_id(row: dict[str, object]) -> int | None:
    value = row.get("team_id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _warehouse_status(organization_id: str, state: dict[str, object]) -> Response:
    lifecycle_state = state.get("state", "ready")
    ready = lifecycle_state == "ready"
    connection = None
    if ready:
        connection = {
            "host": getattr(settings, "MANAGED_WAREHOUSE_LOCAL_DUCKGRES_HOST", "127.0.0.1"),
            "port": getattr(settings, "MANAGED_WAREHOUSE_LOCAL_DUCKGRES_PORT", 15432),
            "database": state.get("database_name", "local-warehouse"),
            "username": "posthog",
        }
    now = datetime.now(UTC).isoformat()
    return Response(
        {
            "org_id": organization_id,
            "state": lifecycle_state,
            "status_message": "Local managed warehouse is ready" if ready else "Local managed warehouse was deleted",
            "s3_state": "ready" if ready else "deleted",
            "metadata_store_state": "ready" if ready else "deleted",
            "identity_state": "ready" if ready else "deleted",
            "secrets_state": "ready" if ready else "deleted",
            "ready_at": state.get("ready_at") if ready else None,
            "failed_at": None,
            "connection": connection,
            "bucket": "ducklake-dev" if ready else None,
            "bucket_region": "us-east-1" if ready else None,
            "updated_at": now,
        },
        status=status.HTTP_200_OK,
    )


def _monitoring_snapshot(organization_id: str, state: dict[str, object]) -> Response:
    return Response(
        {
            "schema_version": 1,
            "org_id": organization_id,
            "as_of": datetime.now(UTC).isoformat(),
            "warehouse": {"state": state.get("state", "ready")},
            "limits": {
                "max_workers": 1,
                "max_vcpus": 1,
                "default_worker_cpu": "1",
                "default_worker_memory": "1Gi",
                "default_worker_ttl_seconds": 300,
                "default_worker_min_hot_idle": 0,
            },
            "totals": {
                "workers": 0,
                "allocated_cpu_cores": 0,
                "allocated_memory_bytes": 0,
                "active_sessions": 0,
                "running_queries": 0,
                "queued_connections": 0,
            },
            "workers": [],
            "coverage": {"cp_responders": 1, "cp_total": 1, "partial": False},
        },
        status=status.HTTP_200_OK,
    )


def _monitoring_series(organization_id: str, params: dict | None) -> Response:
    now = datetime.now(UTC)
    start = now - timedelta(hours=1)
    metric = str((params or {}).get("metric", "query_rate"))
    return Response(
        {
            "schema_version": 1,
            "org_id": organization_id,
            "metric": metric,
            "unit": _METRIC_UNITS.get(metric, "count"),
            "start": start.isoformat(),
            "end": now.isoformat(),
            "step_seconds": 60,
            "series": [],
        },
        status=status.HTTP_200_OK,
    )


def _upsert_team(organization_id: str, state: dict[str, object], body: dict[str, object]) -> Response:
    team_id = body.get("team_id")
    schema_name = body.get("schema_name")
    teams = _teams(state)
    if any(row.get("schema_name") == schema_name and _team_id(row) != team_id for row in teams):
        return Response({"error": "schema name already in use"}, status=status.HTTP_409_CONFLICT)

    existing = next((row for row in teams if _team_id(row) == team_id), None)
    if existing is None:
        existing = {"team_id": team_id}
        teams.append(existing)
    existing.update(body)
    state["teams"] = teams
    _set_state(organization_id, state)
    return Response(existing, status=status.HTTP_200_OK)


def request(
    method: str,
    organization_id: UUID | str,
    path: str,
    *,
    json_body: dict | None = None,
    params: dict | None = None,
) -> Response:
    organization_id = str(organization_id)
    body = cast(dict[str, object], json_body or {})

    if not organization_id and path == "teams" and method == "GET":
        rows: list[dict[str, object]] = []
        for org_id in cache.get(_ORG_INDEX_KEY) or []:
            state = _get_state(str(org_id))
            if state is not None:
                rows.extend({**row, "org_id": str(org_id)} for row in _teams(state))
        return Response(rows, status=status.HTTP_200_OK)

    if path == "database-name/check" and method == "GET":
        name = (params or {}).get("name")
        taken = any(
            (_get_state(str(org_id)) or {}).get("database_name") == name for org_id in cache.get(_ORG_INDEX_KEY) or []
        )
        return Response({"name": name, "available": not taken}, status=status.HTTP_200_OK)

    state = _get_state(organization_id)
    if path == "/provision" and method == "POST":
        if state is not None and state.get("state") != "deleted":
            return Response({"error": "warehouse already exists"}, status=status.HTTP_409_CONFLICT)
        ready_at = datetime.now(UTC).isoformat()
        state = {
            "database_name": body.get("database_name"),
            "ready_at": ready_at,
            "state": "ready",
            "teams": [
                {
                    "team_id": body.get("team_id"),
                    "schema_name": body.get("schema_name"),
                    "enabled": True,
                    "backfill_enabled": False,
                }
            ],
        }
        _set_state(organization_id, state)
        return Response(
            {
                "status": "provisioning started",
                "org": organization_id,
                "username": "posthog",
                "password": _LOCAL_PASSWORD,
                "bucket": "ducklake-dev",
                "bucket_region": "us-east-1",
            },
            status=status.HTTP_202_ACCEPTED,
        )

    if state is None:
        return Response({"error": "managed warehouse not found"}, status=status.HTTP_404_NOT_FOUND)

    if path == "/warehouse/status" and method == "GET":
        return _warehouse_status(organization_id, state)
    if path == "/monitoring/snapshot" and method == "GET":
        return _monitoring_snapshot(organization_id, state)
    if path == "/monitoring/series" and method == "GET":
        return _monitoring_series(organization_id, params)
    if path == "/teams" and method == "GET":
        return Response(
            {"teams": _teams(state), "data_imports_table_naming_version": "legacy"},
            status=status.HTTP_200_OK,
        )
    if path == "/teams" and method == "POST":
        return _upsert_team(organization_id, state, body)
    if path.startswith("/teams/"):
        try:
            requested_team_id = int(path.rsplit("/", 1)[1])
        except ValueError:
            return Response({"error": "invalid team id"}, status=status.HTTP_400_BAD_REQUEST)
        teams = _teams(state)
        team = next((row for row in teams if _team_id(row) == requested_team_id), None)
        if team is None:
            return Response({"error": "team not found"}, status=status.HTTP_404_NOT_FOUND)
        if method == "PUT":
            team.update(body)
            _set_state(organization_id, state)
            return Response(team, status=status.HTTP_200_OK)
        if method == "DELETE":
            if len(teams) == 1:
                return Response({"error": "cannot delete the final team"}, status=status.HTTP_409_CONFLICT)
            state["teams"] = [row for row in teams if _team_id(row) != requested_team_id]
            _set_state(organization_id, state)
            return Response({"status": "deleted"}, status=status.HTTP_200_OK)
    if path == "/trino" and method == "GET":
        ready = state.get("state") == "ready"
        return Response(
            {
                "enabled": ready,
                "status": {
                    "org": organization_id,
                    "state": "ready" if ready else "deleted",
                    "trino_catalog_name": getattr(settings, "MANAGED_WAREHOUSE_LOCAL_TRINO_CATALOG", "ducklake"),
                    "connection": {
                        "host": getattr(settings, "MANAGED_WAREHOUSE_LOCAL_TRINO_HOST", "127.0.0.1"),
                        "port": getattr(settings, "MANAGED_WAREHOUSE_LOCAL_TRINO_PORT", 38080),
                        "username": "posthog",
                    },
                },
            },
            status=status.HTTP_200_OK,
        )
    if path == "/reset-password" and method == "POST":
        return Response({"password": _LOCAL_PASSWORD}, status=status.HTTP_200_OK)
    if path == "/deprovision" and method == "POST":
        state.update({"state": "deleted", "teams": []})
        _set_state(organization_id, state)
        return Response(
            {"status": "deprovisioning started", "org": organization_id},
            status=status.HTTP_202_ACCEPTED,
        )
    if path == "" and method == "DELETE":
        _delete_state(organization_id)
        return Response({"status": "deleted", "org": organization_id}, status=status.HTTP_200_OK)

    return Response({"error": "local managed warehouse endpoint not implemented"}, status=status.HTTP_404_NOT_FOUND)
