from datetime import date
from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests

from products.managed_warehouse.backend import cp_teams
from products.managed_warehouse.backend.presentation import (
    hogtower,
    views as managed_warehouse,
)
from products.managed_warehouse.backend.service_credentials import (
    mint_service_credential,
    refresh_service_credential,
    renew_service_credential,
)
from products.managed_warehouse.backend.trino_compiler import get_ready_trino_catalog_name
from products.managed_warehouse.backend.trino_target import get_ready_trino_connection_target

BASE = "http://hogtower.invalid"
ORG = "0194d640-5db4-0000-6cde-48d6114c0f99"
PRINCIPAL = "user:test"

# Never a real secret.
_FAKE_SECRET = "test-plaintext-sentinel-not-a-real-grant"

HOGTOWER = override_settings(
    HOGTOWER_API_URL=f"{BASE}/",
    HOGTOWER_INTERNAL_SECRET="ht-secret",
    # Set too, to prove hogtower wins when both are configured.
    DUCKGRES_API_URL="http://duckgres.invalid",
    DUCKGRES_INTERNAL_SECRET="dg-secret",
)


def _http(status_code: int, body: object) -> MagicMock:
    resp = MagicMock(status_code=status_code, text=str(body))
    resp.json.return_value = body
    return resp


class FakeHogtower:
    """Answers hogtower v2 calls from a (method, path) table and records every call."""

    def __init__(self, routes: dict[tuple[str, str], tuple[int, object]]) -> None:
        self.routes = routes
        self.calls: list[dict] = []

    def __call__(self, method: str, url: str, *, json=None, params=None, headers=None, timeout=None) -> MagicMock:
        assert url.startswith(f"{BASE}/api/v2/"), url
        path = url.removeprefix(f"{BASE}/api/v2")
        self.calls.append(
            {"method": method, "path": path, "json": json, "params": params, "headers": headers, "timeout": timeout}
        )
        if (method, path) not in self.routes:
            return _http(404, {"error": "not found"})
        return _http(*self.routes[(method, path)])

    @property
    def paths(self) -> list[tuple[str, str]]:
        return [(call["method"], call["path"]) for call in self.calls]


@pytest.fixture
def fake(request):
    routes = getattr(request, "param", {})
    fake = FakeHogtower(routes)
    with (
        HOGTOWER,
        patch("products.managed_warehouse.backend.presentation.hogtower.internal_requests.request", side_effect=fake),
    ):
        yield fake


def _routes(routes: dict[tuple[str, str], tuple[int, object]]):
    return pytest.mark.parametrize("fake", [routes], indirect=True)


W = f"/warehouses/{ORG}"

_WAREHOUSE = {
    "org_id": ORG,
    "database_name": "acme",
    "data_imports_table_naming_version": "copy_v1",
    "data_store": {"kind": "s3bucket", "bucket_name": "posthog-duckling-acme"},
    "state": "ready",
    "status_message": "Ready",
    "metadata_store_state": "ready",
    "s3_state": "ready",
    "identity_state": "ready",
    "secrets_state": "ready",
    "provisioning_started_at": "2026-10-01T00:00:00Z",
    "ready_at": "2026-10-01T00:05:00Z",
    "failed_at": None,
}

_TEAM = {
    "org_id": ORG,
    "team_id": 7,
    "schema_name": "acme_prod",
    "enabled": True,
    "backfill_enabled": True,
    "events_table_name": "events_acme_prod",
    "earliest_event_date": None,
}


def _detail(**warehouse_overrides: object) -> tuple[int, dict]:
    warehouse = {**_WAREHOUSE, **warehouse_overrides}
    connection = (
        {"host": "acme.dw.us.postwh.com", "port": 5432, "database": "acme", "username": "root"}
        if warehouse["state"] == "ready"
        else None
    )
    body: dict = {"warehouse": warehouse, "teams": [_TEAM], "users": []}
    if connection:
        body["connection"] = connection
    return 200, body


def _mapped(method: str, path: str, **kwargs) -> hogtower.TranslatedResponse:
    return hogtower.request(method, ORG, path, **kwargs)


class TestTransport:
    @_routes({("GET", f"{W}/teams"): (200, {"teams": [], "data_imports_table_naming_version": "copy_v1"})})
    def test_sends_the_hogtower_secret_header_and_timeout(self, fake: FakeHogtower) -> None:
        _mapped("GET", "/teams", timeout=12)

        assert fake.calls[0]["headers"] == {"X-Hogtower-Internal-Secret": "ht-secret"}
        assert fake.calls[0]["timeout"] == 12

    def test_non_json_body_becomes_an_error_body(self) -> None:
        resp = MagicMock(status_code=502, text="<html>bad gateway</html>")
        resp.json.side_effect = ValueError
        with (
            HOGTOWER,
            patch(
                "products.managed_warehouse.backend.presentation.hogtower.internal_requests.request", return_value=resp
            ),
        ):
            out = _mapped("POST", "/reset-password")

        assert (out.status_code, out.json()) == (502, {"error": "<html>bad gateway</html>"})

    @pytest.mark.parametrize(
        "method,path,shown",
        [
            ("PATCH", "/teams", "PATCH /teams"),
            ("GET", "/service-grants", "GET /service-grants"),
            ("POST", "/service-grants/svc_x", "POST /service-grants/svc_x"),
            ("PUT", "", "PUT /"),
            ("POST", "warehouses", "POST warehouses"),
        ],
    )
    def test_unmapped_route_is_501_without_calling_hogtower(
        self, fake: FakeHogtower, method: str, path: str, shown: str
    ) -> None:
        with patch("products.managed_warehouse.backend.presentation.hogtower.logger") as logger:
            out = _mapped(method, path, json_body={"credential_secret": _FAKE_SECRET})

        assert (out.status_code, out.json()) == (
            501,
            {"error": f"not supported by the hogtower control plane: {shown}"},
        )
        assert fake.calls == []
        logger.warning.assert_called_once_with("hogtower_adapter_unmapped_route", method=method, path=path or "/")
        assert _FAKE_SECRET not in str(logger.mock_calls)

    def test_is_configured_follows_the_setting(self) -> None:
        with override_settings(HOGTOWER_API_URL=None):
            assert not hogtower.is_configured()
        with override_settings(HOGTOWER_API_URL=BASE):
            assert hogtower.is_configured()


class TestWarehouseRoutes:
    @_routes(
        {
            ("POST", "/warehouses"): (
                202,
                {
                    "warehouse": {**_WAREHOUSE, "state": "pending"},
                    "root": {"username": "root", "password": _FAKE_SECRET, "database": "acme"},
                },
            )
        }
    )
    def test_provision_posts_warehouse_and_returns_the_v1_body(self, fake: FakeHogtower) -> None:
        out = _mapped(
            "POST",
            "/provision",
            json_body={
                "database_name": "acme",
                "team_id": 7,
                "schema_name": "acme_prod",
                "ducklake": {"enabled": True},
                "metadata_store": {"type": "cnpg-shard"},
                "data_store": {"type": "s3bucket"},
                "trino": {"enabled": True},
            },
        )

        assert fake.calls[0]["json"] == {
            "id": ORG,
            "database_name": "acme",
            "team": {"id": 7, "schema_name": "acme_prod"},
            "metadata_store": {"type": "cnpg-shard"},
            "data_store": {"type": "s3bucket"},
            "trino": {"enabled": True},
        }
        assert (out.status_code, out.json()) == (
            202,
            {
                "status": "provisioning started",
                "org": ORG,
                "username": "root",
                "password": _FAKE_SECRET,
                "bucket": "posthog-duckling-acme",
            },
        )

    @_routes({("POST", "/warehouses"): (409, {"error": "warehouse already exists in non-terminal state"})})
    def test_provision_passes_errors_through(self, fake: FakeHogtower) -> None:
        out = _mapped("POST", "/provision", json_body={"database_name": "acme", "team_id": 7})

        assert (out.status_code, out.json()) == (409, {"error": "warehouse already exists in non-terminal state"})

    @_routes({("DELETE", W): (202, {"status": "deprovisioning started", "id": ORG})})
    def test_deprovision_deletes_the_warehouse(self, fake: FakeHogtower) -> None:
        out = _mapped("POST", "/deprovision")

        assert fake.paths == [("DELETE", W)]
        assert (out.status_code, out.json()) == (202, {"status": "deprovisioning started", "org": ORG})

    @_routes({("GET", W): _detail()})
    def test_status_projects_the_detail_onto_the_v1_status(self, fake: FakeHogtower) -> None:
        out = _mapped("GET", "/warehouse/status")

        assert (out.status_code, out.json()) == (
            200,
            {
                "org_id": ORG,
                "state": "ready",
                "status_message": "Ready",
                "s3_state": "ready",
                "metadata_store_state": "ready",
                "identity_state": "ready",
                "secrets_state": "ready",
                "ready_at": "2026-10-01T00:05:00Z",
                "connection": {"host": "acme.dw.us.postwh.com", "port": 5432, "database": "acme", "username": "root"},
                "bucket": "posthog-duckling-acme",
            },
        )

    @_routes(
        {("GET", W): _detail(data_store={"kind": "s3bucket", "bucket_name": "posthog-duckling-acme", "prefix": "lake"})}
    )
    def test_status_reports_the_data_store_prefix(self, fake: FakeHogtower) -> None:
        body = _mapped("GET", "/warehouse/status").json()

        assert (body["bucket"], body["bucket_prefix"]) == ("posthog-duckling-acme", "lake")

    @_routes({("GET", W): _detail(state="provisioning", ready_at=None, data_store={"kind": "external"})})
    def test_status_omits_connection_and_bucket_until_known(self, fake: FakeHogtower) -> None:
        body = _mapped("GET", "/warehouse/status").json()

        assert body["state"] == "provisioning"
        assert "connection" not in body
        assert "bucket" not in body
        assert "ready_at" not in body

    @_routes({("POST", f"{W}/root-password"): (200, {"username": "root", "password": _FAKE_SECRET})})
    def test_reset_password_rotates_root(self, fake: FakeHogtower) -> None:
        out = _mapped("POST", "/reset-password")

        assert (out.status_code, out.json()) == (200, {"username": "root", "password": _FAKE_SECRET})

    @pytest.mark.parametrize(
        "fake, expected",
        [
            ({}, (200, {"deleted": ORG})),
            ({("GET", W): _detail(state="deleted")}, (200, {"deleted": ORG})),
            ({("GET", W): _detail(state="deleting")}, (409, {"error": hogtower._WAREHOUSE_STILL_EXISTS})),
            ({("GET", W): (500, {"error": "db down"})}, (500, {"error": "db down"})),
        ],
        indirect=["fake"],
    )
    def test_delete_org_never_deprovisions(self, fake: FakeHogtower, expected: tuple[int, dict]) -> None:
        out = _mapped("DELETE", "")

        assert (out.status_code, out.json()) == expected
        assert fake.paths == [("GET", W)]

    @_routes({("GET", "/database-names/acme"): (200, {"name": "acme", "available": True, "reason": ""})})
    def test_check_name_drops_an_empty_reason(self, fake: FakeHogtower) -> None:
        out = hogtower.request("GET", ORG, "database-name/check", params={"name": "acme"})

        assert (out.status_code, out.json()) == (200, {"name": "acme", "available": True})

    @_routes({("GET", "/database-names/acme"): (200, {"name": "acme", "available": True, "reason": ""})})
    @pytest.mark.parametrize("org_id, params", [(ORG, {"org_id": ORG}), ("", None)])
    def test_check_name_asks_for_the_calling_org(
        self, fake: FakeHogtower, org_id: str, params: dict[str, str] | None
    ) -> None:
        # hogtower treats a name the org's own warehouses carried as free only when told the org.
        hogtower.request("GET", org_id, "database-name/check", params={"name": "acme"})

        assert fake.calls[0]["params"] == params

    @_routes(
        {
            ("GET", f"{W}/monitoring/snapshot"): (200, {"sessions": 1}),
            ("GET", f"{W}/monitoring/series"): (200, {"points": []}),
            ("GET", f"{W}/monitoring/trino/snapshot"): (200, {"queries": []}),
            ("GET", f"{W}/monitoring/trino/series"): (200, {"points": []}),
        }
    )
    @pytest.mark.parametrize("engine", ["duckdb", "trino"])
    def test_monitoring_is_passed_through(self, fake: FakeHogtower, engine: str) -> None:
        prefix = "/monitoring/trino" if engine == "trino" else "/monitoring"
        snapshot: dict[str, object] = {"queries": []} if engine == "trino" else {"sessions": 1}
        response = _mapped("GET", f"{prefix}/snapshot")
        assert (response.status_code, response.json()) == (200, snapshot)
        params = {"metric": "query_rate", "window": "1h"}
        response = _mapped("GET", f"{prefix}/series", params=params)
        assert (response.status_code, response.json()) == (200, {"points": []})
        assert fake.paths == [("GET", f"{W}{prefix}/snapshot"), ("GET", f"{W}{prefix}/series")]
        assert fake.calls[1]["params"] == params


class TestTeamRoutes:
    @_routes({("GET", f"{W}/teams"): (200, {"teams": [_TEAM]}), ("GET", W): _detail()})
    def test_list_teams_carries_the_naming_version_from_the_warehouse(self, fake: FakeHogtower) -> None:
        out = _mapped("GET", "/teams")

        assert out.json() == {"teams": [_TEAM], "data_imports_table_naming_version": "copy_v1"}

    @_routes({("GET", f"{W}/teams"): (200, {"teams": [_TEAM], "data_imports_table_naming_version": "copy_v1"})})
    def test_list_teams_uses_one_call_when_v2_carries_the_naming_version(self, fake: FakeHogtower) -> None:
        assert _mapped("GET", "/teams").json()["data_imports_table_naming_version"] == "copy_v1"
        assert fake.paths == [("GET", f"{W}/teams")]

    @_routes({("GET", "/teams"): (200, {"teams": [{**_TEAM, "org_id": "", "warehouse_id": ORG}]})})
    def test_list_all_teams_keys_rows_by_org(self, fake: FakeHogtower) -> None:
        out = hogtower.request("GET", "", "teams")

        assert out.json()["teams"][0]["org_id"] == ORG

    @_routes({("PUT", f"{W}/teams/7"): (200, {"team": _TEAM})})
    def test_upsert_puts_the_team_and_unwraps_it(self, fake: FakeHogtower) -> None:
        body = {"team_id": 7, "schema_name": "acme_prod", "events_table_name": "events_acme_prod"}
        out = _mapped("POST", "/teams", json_body=body)

        assert fake.calls[0]["json"] == body
        assert (out.status_code, out.json()) == (200, _TEAM)

    @_routes({("GET", f"{W}/teams"): (200, {"teams": [_TEAM]}), ("PUT", f"{W}/teams/7"): (200, {"team": _TEAM})})
    def test_update_sends_only_the_given_fields_plus_the_current_schema(self, fake: FakeHogtower) -> None:
        out = _mapped("PUT", "/teams/7", json_body={"earliest_event_date": "2024-01-02"})

        assert out.status_code == 200
        assert fake.calls[1]["json"] == {"schema_name": "acme_prod", "earliest_event_date": "2024-01-02"}

    @_routes({("GET", f"{W}/teams"): (200, {"teams": [_TEAM]})})
    def test_update_of_an_unknown_team_is_a_404_and_creates_nothing(self, fake: FakeHogtower) -> None:
        out = _mapped("PUT", "/teams/8", json_body={"earliest_event_date": "2024-01-02"})

        assert out.status_code == 404
        assert fake.paths == [("GET", f"{W}/teams")]

    @_routes({("DELETE", f"{W}/teams/7"): (200, {"deleted": 7})})
    def test_delete_team(self, fake: FakeHogtower) -> None:
        out = _mapped("DELETE", "/teams/7")

        assert (out.status_code, out.json()) == (200, {"deleted": 7, "org": ORG})

    @_routes({("DELETE", f"{W}/teams/7"): (409, {"error": "cannot delete the warehouse's last team"})})
    def test_delete_last_team_conflict_is_preserved(self, fake: FakeHogtower) -> None:
        assert _mapped("DELETE", "/teams/7").status_code == 409


_TRINO_LIVE = {
    "enabled": True,
    "backend": "hoglake",
    "status": {
        "org": ORG,
        "state": "ready",
        "trino_catalog_name": "acme_catalog",
        "connection": {"host": "acme.trino.example", "port": 443, "username": "root"},
    },
}


class TestTrinoRoute:
    @_routes({("GET", f"{W}/trino"): (200, {"trino": {"org_id": ORG, "enabled": True}, "live": _TRINO_LIVE})})
    def test_live_detail_is_the_v1_body(self, fake: FakeHogtower) -> None:
        assert _mapped("GET", "/trino").json() == _TRINO_LIVE

    @_routes(
        {
            ("GET", f"{W}/trino"): (
                200,
                {
                    "trino": {"org_id": ORG, "enabled": True, "backend": "ducklake", "hoglake_initialized": False},
                    "live": _TRINO_LIVE,
                },
            )
        }
    )
    def test_live_detail_takes_the_backend_from_the_tenancy(self, fake: FakeHogtower) -> None:
        # duckgres's live body can't tell a hoglake catalog from a DuckLake one; hogtower's row can.
        body = _mapped("GET", "/trino").json()

        assert body["backend"] == "ducklake"
        assert body["hoglake_initialized"] is False
        assert body["status"] == _TRINO_LIVE["status"]

    @_routes(
        {
            ("GET", f"{W}/trino"): (
                200,
                {"trino": {"org_id": ORG, "enabled": True, "backend": "hoglake", "hoglake_initialized": True}},
            )
        }
    )
    def test_tenancy_alone_carries_hoglake_initialized(self, fake: FakeHogtower) -> None:
        body = _mapped("GET", "/trino").json()

        assert body["backend"] == "hoglake"
        assert body["hoglake_initialized"] is True

    @_routes({("GET", f"{W}/trino"): (200, {"trino": None})})
    def test_no_tenancy_is_disabled(self, fake: FakeHogtower) -> None:
        assert _mapped("GET", "/trino").json() == {"enabled": False}

    @_routes(
        {
            ("GET", f"{W}/trino"): (
                200,
                {"trino": {"org_id": ORG, "enabled": True, "backend": "hoglake", "tier": "", "state": "ready"}},
            )
        }
    )
    def test_tenancy_without_live_detail_is_never_ready_for_queries(self, fake: FakeHogtower) -> None:
        body = _mapped("GET", "/trino").json()

        assert body["enabled"] is True
        assert body["status"]["state"] == "ready"
        assert "connection" not in body["status"]
        assert get_ready_trino_catalog_name(ORG) is None
        assert get_ready_trino_connection_target(ORG) is None

    @_routes({("GET", f"{W}/trino"): (200, {"trino": {"org_id": ORG, "enabled": True}, "live": _TRINO_LIVE})})
    def test_trino_callers_read_the_ready_target(self, fake: FakeHogtower) -> None:
        assert get_ready_trino_catalog_name(ORG) == "acme_catalog"
        target = get_ready_trino_connection_target(ORG)
        assert target is not None
        assert (target.host, target.port, target.catalog, target.username) == (
            "acme.trino.example",
            443,
            "acme_catalog",
            "root",
        )


_CID = "svc_a1b2c3d4e5f60718293a4b5c"
_CREDENTIAL = {
    "credential_id": _CID,
    "credential_secret": _FAKE_SECRET,
    "secret_rotated": True,
    "expires_at": "2026-08-11T13:00:00Z",
    "connect": {"host": "acme.dw.us.postwh.com", "port": 5432, "database": "ducklake", "sslmode": "require"},
}


class TestServiceCredentials:
    @_routes({("POST", f"{W}/service-credentials"): (200, _CREDENTIAL)})
    def test_mint(self, fake: FakeHogtower) -> None:
        credential = mint_service_credential(ORG, 7, principal="dagster:events-backfill", ttl_seconds=900)

        assert credential.credential_id == _CID
        assert fake.calls[0]["json"] == {"principal": "dagster:events-backfill", "ttl_seconds": 900}

    @_routes({("POST", f"{W}/service-credentials/{_CID}/refresh"): (200, _CREDENTIAL)})
    def test_refresh_addresses_the_credential_in_the_path(self, fake: FakeHogtower) -> None:
        credential = refresh_service_credential(ORG, _CID, ttl_seconds=900)

        assert credential.credential_secret == _FAKE_SECRET
        assert fake.calls[0]["json"] == {"ttl_seconds": 900}

    @_routes(
        {
            ("POST", f"{W}/service-credentials/{_CID}/refresh"): (
                200,
                {**_CREDENTIAL, "credential_secret": "", "secret_rotated": False},
            )
        }
    )
    def test_renew_keeps_the_secret(self, fake: FakeHogtower) -> None:
        credential = renew_service_credential(ORG, _CID, credential_secret=_FAKE_SECRET, ttl_seconds=900)

        assert credential.credential_secret == _FAKE_SECRET
        assert fake.calls[0]["json"] == {"ttl_seconds": 900, "rotate_secret": False}

    @_routes({("DELETE", f"{W}/service-credentials/{_CID}"): (200, {"revoked": _CID})})
    def test_revoke_maps_the_v1_service_grant_delete(self, fake: FakeHogtower) -> None:
        out = _mapped("DELETE", f"/service-grants/{_CID}")

        assert (out.status_code, out.json()) == (200, {"revoked": _CID})
        assert fake.paths == [("DELETE", f"{W}/service-credentials/{_CID}")]
        assert fake.calls[0]["json"] is None

    def test_revoke_unknown_credential_passes_the_error_through(self, fake: FakeHogtower) -> None:
        out = _mapped("DELETE", "/service-grants/svc_gone")

        assert (out.status_code, out.json()) == (404, {"error": "not found"})
        assert fake.paths == [("DELETE", f"{W}/service-credentials/svc_gone")]


@patch("products.managed_warehouse.backend.presentation.views.is_enabled", return_value=True)
class TestViewsUseHogtower:
    @_routes({("GET", W): _detail(state="deleting")})
    def test_request_never_touches_duckgres(self, _enabled: MagicMock, fake: FakeHogtower) -> None:
        with patch("products.managed_warehouse.backend.presentation.views.internal_requests") as duckgres:
            resp = managed_warehouse.delete_org(ORG, triggered_by=PRINCIPAL)

        duckgres.request.assert_not_called()
        assert resp.status_code == 409

    def test_transport_errors_map_like_duckgres(self, _enabled: MagicMock) -> None:
        with (
            HOGTOWER,
            patch(
                "products.managed_warehouse.backend.presentation.hogtower.internal_requests.request",
                side_effect=requests.Timeout,
            ),
        ):
            resp = managed_warehouse.list_teams(ORG)

        assert (resp.status_code, resp.data) == (504, {"error": "Provisioning service timed out"})

    def test_unmapped_route_is_a_501_response(self, _enabled: MagicMock, fake: FakeHogtower) -> None:
        resp = managed_warehouse._request("GET", ORG, "/service-grants")

        assert (resp.status_code, resp.data) == (
            501,
            {"error": "not supported by the hogtower control plane: GET /service-grants"},
        )
        assert fake.calls == []

    @_routes({("GET", "/database-names/acme"): (200, {"name": "acme", "available": False, "reason": ""})})
    def test_check_name(self, _enabled: MagicMock, fake: FakeHogtower) -> None:
        resp = managed_warehouse.check_name(ORG, "acme")

        assert (resp.status_code, resp.data) == (200, {"name": "acme", "available": False})
        assert fake.calls[0]["params"] == {"org_id": ORG}

    @_routes(
        {
            ("GET", f"{W}/teams"): (200, {"teams": [_TEAM], "data_imports_table_naming_version": "copy_v1"}),
            ("PUT", f"{W}/teams/7"): (200, {"team": _TEAM}),
        }
    )
    def test_push_earliest_event_date(self, _enabled: MagicMock, fake: FakeHogtower) -> None:
        assert managed_warehouse.push_team_earliest_event_date(ORG, 7, date(2024, 1, 2)) is True
        assert fake.calls[-1]["json"] == {"schema_name": "acme_prod", "earliest_event_date": "2024-01-02"}

    @override_settings(CLOUD_DEPLOYMENT="US")
    @_routes({("GET", W): _detail(data_store={"kind": "external"})})
    def test_status_for_presents_the_connection(self, _enabled: MagicMock, fake: FakeHogtower) -> None:
        resp = managed_warehouse.status_for(ORG)

        assert resp.status_code == 200
        assert resp.data["connection"]["host"] == "acme.dw.us.postwh.com"
        assert resp.data["connection"]["database"] == "ducklake"


class TestCPTeamsUseHogtower:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        cp_teams.clear_cache()
        yield
        cp_teams.clear_cache()

    @_routes({("GET", f"{W}/teams"): (200, {"teams": [_TEAM], "data_imports_table_naming_version": "copy_v1"})})
    def test_org_rows(self, fake: FakeHogtower) -> None:
        teams = cp_teams.list_org_teams(ORG)

        assert teams is not None
        assert [(t.team_id, t.data_imports_table_naming_version) for t in teams] == [(7, "copy_v1")]

    @_routes(
        {
            ("GET", "/teams"): (200, {"teams": [{**_TEAM, "warehouse_id": ORG}]}),
            ("GET", "/discovery/warehouses"): (
                200,
                {
                    "warehouses": [
                        {"org_id": ORG, "state": "ready"},
                        {"org_id": str(uuid4()), "state": "resharding"},
                    ]
                },
            ),
        }
    )
    def test_enabled_backfills_use_teams_and_discovery(self, fake: FakeHogtower) -> None:
        teams = cp_teams.list_enabled_backfills()

        assert teams is not None
        assert [t.team_id for t in teams] == [7]
        assert set(fake.paths) == {("GET", "/teams"), ("GET", "/discovery/warehouses")}

    @_routes({("GET", f"{W}/teams"): (503, {"error": "unavailable"})})
    def test_unusable_answer_is_none(self, fake: FakeHogtower) -> None:
        assert cp_teams.list_org_teams(ORG) is None

    def test_transport_error_is_none(self) -> None:
        with (
            HOGTOWER,
            patch(
                "products.managed_warehouse.backend.presentation.hogtower.internal_requests.request",
                side_effect=requests.ConnectionError,
            ),
        ):
            assert cp_teams.list_org_teams(ORG) is None


_HLC = "hlc_0123456789abcdef01234567"
_HLC_ISSUED = {
    "client_id": _HLC,
    "client_secret": _FAKE_SECRET,
    "name": "laptop",
    "scope": "read",
    "expires_at": "2027-02-01T00:00:00Z",
}
_HLC_ROW = {
    "client_id": _HLC,
    "name": "laptop",
    "scope": "read",
    "created_at": "2026-11-01T00:00:00Z",
    "last_rotated_at": "2026-11-01T00:00:00Z",
    "expires_at": "2027-02-01T00:00:00Z",
}


class TestHoglakeCredentialRoutes:
    @_routes({("GET", f"{W}/hoglake-credentials"): (200, {"hoglake_credentials": [_HLC_ROW]})})
    def test_list(self, fake: FakeHogtower) -> None:
        out = _mapped("GET", "/hoglake-credentials")

        assert (out.status_code, out.json()) == (200, {"hoglake_credentials": [_HLC_ROW]})

    @_routes({("POST", f"{W}/hoglake-credentials"): (201, _HLC_ISSUED)})
    def test_create_passes_the_body(self, fake: FakeHogtower) -> None:
        out = _mapped("POST", "/hoglake-credentials", json_body={"name": "laptop", "scope": "read"})

        assert out.status_code == 201
        assert fake.calls[0]["json"] == {"name": "laptop", "scope": "read"}

    @_routes({("POST", f"{W}/hoglake-credentials/{_HLC}/rotate"): (200, _HLC_ISSUED)})
    def test_rotate(self, fake: FakeHogtower) -> None:
        out = _mapped("POST", f"/hoglake-credentials/{_HLC}/rotate")

        assert out.json()["client_secret"] == _FAKE_SECRET
        assert fake.calls[0]["json"] is None

    @_routes({("DELETE", f"{W}/hoglake-credentials/{_HLC}"): (200, {"revoked": _HLC})})
    def test_revoke(self, fake: FakeHogtower) -> None:
        out = _mapped("DELETE", f"/hoglake-credentials/{_HLC}")

        assert (out.status_code, out.json()) == (200, {"revoked": _HLC})

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", f"/hoglake-credentials/{_HLC}"),
            ("DELETE", f"/hoglake-credentials/{_HLC}/rotate"),
            ("PUT", "/hoglake-credentials"),
        ],
    )
    def test_other_methods_are_not_forwarded(self, fake: FakeHogtower, method: str, path: str) -> None:
        assert _mapped(method, path).status_code == 501
        assert fake.calls == []


@patch("products.managed_warehouse.backend.presentation.views.is_enabled", return_value=True)
class TestHoglakeCredentialViews:
    @pytest.fixture(autouse=True)
    def _public_token_url(self):
        with override_settings(HOGLAKE_OAUTH_TOKEN_URL="https://hogtower-oauth.example.test/oauth/token"):
            yield

    @_routes({("GET", f"{W}/hoglake-credentials"): (200, {"hoglake_credentials": [_HLC_ROW]})})
    def test_list_adds_where_to_connect(self, _enabled: MagicMock, fake: FakeHogtower) -> None:
        with override_settings(
            HOGLAKE_PUBLIC_URL="https://hoglake.example.test",
            HOGLAKE_OAUTH_TOKEN_URL="https://hogtower-oauth.example.test/oauth/token",
        ):
            resp = managed_warehouse.list_hoglake_credentials(ORG)

        assert resp.status_code == 200
        assert resp.data["connect"] == {
            "catalog": ORG,
            "hoglake_url": "https://hoglake.example.test",
            "token_url": "https://hogtower-oauth.example.test/oauth/token",
        }

    @_routes({("POST", f"{W}/hoglake-credentials"): (201, _HLC_ISSUED)})
    def test_create_logs_the_action_without_the_secret(self, _enabled: MagicMock, fake: FakeHogtower) -> None:
        with patch("products.managed_warehouse.backend.presentation.views.logger") as log:
            resp = managed_warehouse.create_hoglake_credential(
                ORG, name="laptop", scope="read", ttl_seconds=None, triggered_by=PRINCIPAL
            )

        assert (resp.status_code, resp.data["client_secret"]) == (201, _FAKE_SECRET)
        assert fake.calls[0]["json"] == {"name": "laptop", "scope": "read"}
        log.info.assert_any_call(
            "managed_warehouse_action",
            action="create_hoglake_credential",
            triggered_by=PRINCIPAL,
            organization_id=ORG,
            scope="read",
            credential_id=_HLC,
        )
        assert _FAKE_SECRET not in str(log.mock_calls)

    @_routes({("DELETE", f"{W}/hoglake-credentials/{_HLC}"): (404, {"error": "credential not found"})})
    def test_revoke_error_passes_through_unlogged(self, _enabled: MagicMock, fake: FakeHogtower) -> None:
        with patch("products.managed_warehouse.backend.presentation.views.logger") as log:
            resp = managed_warehouse.revoke_hoglake_credential(ORG, _HLC, triggered_by=PRINCIPAL)

        assert resp.status_code == 404
        assert not any(c.args[:1] == ("managed_warehouse_action",) for c in log.info.mock_calls)

    def test_without_hogtower_is_501_and_never_reaches_duckgres(self, _enabled: MagicMock) -> None:
        with (
            override_settings(HOGTOWER_API_URL=None, DUCKGRES_API_URL="http://duckgres.invalid"),
            patch("products.managed_warehouse.backend.presentation.views.internal_requests") as duckgres,
        ):
            resp = managed_warehouse.create_hoglake_credential(
                ORG, name="laptop", scope="read", ttl_seconds=None, triggered_by=PRINCIPAL
            )

        assert resp.status_code == 501
        duckgres.request.assert_not_called()

    def test_without_a_public_token_url_is_501(self, _enabled: MagicMock, fake: FakeHogtower) -> None:
        with override_settings(HOGLAKE_OAUTH_TOKEN_URL=None):
            resp = managed_warehouse.list_hoglake_credentials(ORG)

        assert (resp.status_code, resp.data) == (
            501,
            {"error": "Hoglake credentials are not available in this region yet"},
        )
        assert fake.calls == []


_TEAM_HLC = "hlc_fedcba9876543210fedcba98"
_TEAM_HLC_ROW = {**_HLC_ROW, "client_id": _TEAM_HLC, "kind": "team", "owner_user_uuid": str(uuid4()), "team_ids": [7]}


@patch("products.managed_warehouse.backend.presentation.views.is_enabled", return_value=True)
class TestHoglakeCredentialRotateByAdmin:
    @pytest.fixture(autouse=True)
    def _public_token_url(self):
        with override_settings(HOGLAKE_OAUTH_TOKEN_URL="https://hogtower-oauth.example.test/oauth/token"):
            yield

    @_routes(
        {
            ("GET", f"{W}/hoglake-credentials"): (200, {"hoglake_credentials": [{**_HLC_ROW, "kind": "org"}]}),
            ("POST", f"{W}/hoglake-credentials/{_HLC}/rotate"): (200, _HLC_ISSUED),
        }
    )
    def test_rotates_an_org_credential(self, _enabled: MagicMock, fake: FakeHogtower) -> None:
        resp = managed_warehouse.rotate_hoglake_credential(ORG, _HLC, triggered_by=PRINCIPAL)

        assert (resp.status_code, resp.data["client_secret"]) == (200, _FAKE_SECRET)

    @_routes(
        {
            ("GET", f"{W}/hoglake-credentials"): (200, {"hoglake_credentials": [_TEAM_HLC_ROW]}),
            ("POST", f"{W}/hoglake-credentials/{_TEAM_HLC}/rotate"): (200, _HLC_ISSUED),
        }
    )
    def test_never_rotates_a_members_personal_credential(self, _enabled: MagicMock, fake: FakeHogtower) -> None:
        resp = managed_warehouse.rotate_hoglake_credential(ORG, _TEAM_HLC, triggered_by=PRINCIPAL)

        assert resp.status_code == 403
        assert [c["method"] for c in fake.calls] == ["GET"]

    @_routes(
        {
            ("GET", f"{W}/hoglake-credentials"): (503, {"error": "unavailable"}),
            ("POST", f"{W}/hoglake-credentials/{_TEAM_HLC}/rotate"): (200, _HLC_ISSUED),
        }
    )
    def test_does_not_rotate_when_it_cannot_tell_the_kind(self, _enabled: MagicMock, fake: FakeHogtower) -> None:
        resp = managed_warehouse.rotate_hoglake_credential(ORG, _TEAM_HLC, triggered_by=PRINCIPAL)

        assert resp.status_code >= 500
        assert "client_secret" not in (resp.data or {})
        assert [c["method"] for c in fake.calls] == ["GET"]

    @_routes(
        {
            ("GET", f"{W}/hoglake-credentials"): (200, {"hoglake_credentials": [{**_HLC_ROW, "kind": "org"}]}),
            ("POST", f"{W}/hoglake-credentials/{_TEAM_HLC}/rotate"): (200, _HLC_ISSUED),
        }
    )
    def test_does_not_rotate_a_credential_it_does_not_list(self, _enabled: MagicMock, fake: FakeHogtower) -> None:
        resp = managed_warehouse.rotate_hoglake_credential(ORG, _TEAM_HLC, triggered_by=PRINCIPAL)

        assert resp.status_code == 404
        assert [c["method"] for c in fake.calls] == ["GET"]


@pytest.mark.django_db
def test_list_names_owners_only_from_the_organizations_members() -> None:
    from posthog.models import Organization, User

    org = Organization.objects.create(name="acme")
    member = User.objects.create_and_join(org, "member@acme.test", None, first_name="Mia")
    outsider = User.objects.create_and_join(Organization.objects.create(name="other"), "out@other.test", None)
    creds = [
        {"client_id": "hlc_1", "kind": "team", "owner_user_uuid": str(member.uuid)},
        {"client_id": "hlc_2", "kind": "team", "owner_user_uuid": str(outsider.uuid)},
        {"client_id": "hlc_3", "kind": "org"},
    ]

    managed_warehouse._add_owners(org.id, creds)

    assert (creds[0]["owner_name"], creds[0]["owner_email"]) == ("Mia", "member@acme.test")
    assert "owner_email" not in creds[1] and "owner_email" not in creds[2]


_MT = "products.managed_warehouse.backend.member_teams"


class TestHoglakeCredentialListOwnerFilter:
    @_routes({("GET", f"{W}/hoglake-credentials"): (200, {"hoglake_credentials": []})})
    def test_forwards_only_the_owner(self, fake: FakeHogtower) -> None:
        _mapped("GET", "/hoglake-credentials", params={"owner_user_uuid": "u-1", "kind": "org"})
        _mapped("GET", "/hoglake-credentials")

        assert [c["params"] for c in fake.calls] == [{"owner_user_uuid": "u-1"}, None]

    @_routes(
        {
            ("POST", f"{W}/hoglake-credentials/{_HLC}/rotate"): (200, _HLC_ISSUED),
            ("DELETE", f"{W}/hoglake-credentials/{_HLC}"): (200, {"revoked": _HLC}),
        }
    )
    def test_rotate_and_revoke_forward_only_the_acting_owner(self, fake: FakeHogtower) -> None:
        _mapped("POST", f"/hoglake-credentials/{_HLC}/rotate", json_body={"owner_user_uuid": "u-1", "ttl_seconds": 1})
        _mapped("POST", f"/hoglake-credentials/{_HLC}/rotate")
        _mapped("DELETE", f"/hoglake-credentials/{_HLC}", params={"owner_user_uuid": "u-1", "x": "y"})
        _mapped("DELETE", f"/hoglake-credentials/{_HLC}")

        assert [(c["json"], c["params"]) for c in fake.calls] == [
            ({"owner_user_uuid": "u-1"}, None),
            (None, None),
            (None, {"owner_user_uuid": "u-1"}),
            (None, None),
        ]


def _membership(team_id: int, *, enabled: bool) -> MagicMock:
    row = MagicMock()
    row.team_id, row.enabled = team_id, enabled
    return row


@pytest.mark.django_db
@patch("products.managed_warehouse.backend.presentation.views.is_enabled", return_value=True)
@patch(f"{_MT}.is_enabled", return_value=True)
class TestMyHoglakeCredentials:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from posthog.models import Organization, Team, User

        self.org = Organization.objects.create(id=ORG, name="acme")
        self.team = Team.objects.create(organization=self.org, name="Prod")
        self.user = User.objects.create_and_join(self.org, "mia@acme.test", None)
        self.mine = {**_TEAM_HLC_ROW, "owner_user_uuid": str(self.user.uuid), "team_ids": [self.team.id]}
        self.other = Team.objects.create(organization=self.org, name="Not in the warehouse")
        with (
            override_settings(
                HOGLAKE_OAUTH_TOKEN_URL="https://hogtower-oauth.example.test/oauth/token",
                HOGLAKE_TEAM_CREDENTIALS_ENABLED=True,
            ),
            patch(f"{_MT}.member_teams", return_value={self.team.id: "write", self.other.id: "write"}),
            patch(f"{_MT}.push_member") as self.push,
            patch(
                "products.managed_warehouse.backend.facade.cp_teams.list_org_team_memberships",
                return_value=[_membership(self.team.id, enabled=True), _membership(self.other.id, enabled=False)],
            ) as self.memberships,
        ):
            yield

    def _list_route(self, rows):
        return {("GET", f"{W}/hoglake-credentials"): (200, {"hoglake_credentials": rows})}

    @_routes({("GET", f"{W}/hoglake-credentials"): (200, {"hoglake_credentials": []})})
    def test_list_is_the_callers_own_with_their_projects(
        self, _push_on: MagicMock, _enabled: MagicMock, fake: FakeHogtower
    ) -> None:
        resp = managed_warehouse.list_my_hoglake_credentials(self.org, self.user)

        assert resp.status_code == 200
        assert fake.calls[0]["params"] == {"owner_user_uuid": str(self.user.uuid)}
        assert resp.data["projects"] == [{"id": self.team.id, "name": "Prod", "access": "write"}]
        assert resp.data["connect"]["catalog"] == ORG

    @_routes({("POST", f"{W}/hoglake-credentials"): (201, {**_HLC_ISSUED, "kind": "team"})})
    def test_create_owns_it_and_brings_hogtowers_copy_current_first(
        self, _push_on: MagicMock, _enabled: MagicMock, fake: FakeHogtower
    ) -> None:
        resp = managed_warehouse.create_my_hoglake_credential(
            self.org,
            self.user,
            name="laptop",
            scope="read",
            team_ids=[self.team.id, self.team.id],
            ttl_seconds=None,
            triggered_by=PRINCIPAL,
        )

        assert resp.status_code == 201
        self.push.assert_called_once_with(ORG, str(self.user.uuid))
        assert fake.calls[0]["json"] == {
            "name": "laptop",
            "scope": "read",
            "owner_user_uuid": str(self.user.uuid),
            "team_ids": [self.team.id],
        }

    @_routes({("POST", f"{W}/hoglake-credentials"): (201, _HLC_ISSUED)})
    def test_create_refuses_a_project_the_caller_cannot_see(
        self, _push_on: MagicMock, _enabled: MagicMock, fake: FakeHogtower
    ) -> None:
        resp = managed_warehouse.create_my_hoglake_credential(
            self.org,
            self.user,
            name="laptop",
            scope="read",
            team_ids=[self.team.id, 999999],
            ttl_seconds=None,
            triggered_by=PRINCIPAL,
        )

        assert resp.status_code == 403
        assert fake.calls == []
        self.push.assert_not_called()

    @_routes({("POST", f"{W}/hoglake-credentials"): (201, _HLC_ISSUED)})
    def test_create_goes_ahead_when_the_push_fails(
        self, _push_on: MagicMock, _enabled: MagicMock, fake: FakeHogtower
    ) -> None:
        from products.managed_warehouse.backend.member_teams import MemberTeamsPushError

        self.push.side_effect = MemberTeamsPushError("hogtower unreachable")
        resp = managed_warehouse.create_my_hoglake_credential(
            self.org,
            self.user,
            name="laptop",
            scope="read",
            team_ids=[self.team.id],
            ttl_seconds=None,
            triggered_by=PRINCIPAL,
        )

        assert resp.status_code == 201

    @pytest.mark.parametrize("action", ["rotate", "revoke"])
    def test_rotate_and_revoke_only_the_callers_own(
        self, _push_on: MagicMock, _enabled: MagicMock, action: str
    ) -> None:
        call = getattr(managed_warehouse, f"{action}_my_hoglake_credential")
        theirs = "hlc_00000000000000000000000a"
        routes = {
            **self._list_route([self.mine]),
            ("POST", f"{W}/hoglake-credentials/{_TEAM_HLC}/rotate"): (200, _HLC_ISSUED),
            ("DELETE", f"{W}/hoglake-credentials/{_TEAM_HLC}"): (200, {"revoked": _TEAM_HLC}),
        }
        fake = FakeHogtower(routes)
        with (
            HOGTOWER,
            patch(
                "products.managed_warehouse.backend.presentation.hogtower.internal_requests.request", side_effect=fake
            ),
        ):
            refused = call(self.org, self.user, theirs, triggered_by=PRINCIPAL)
            assert refused.status_code == 404
            assert [c["method"] for c in fake.calls] == ["GET"]

            done = call(self.org, self.user, _TEAM_HLC, triggered_by=PRINCIPAL)

        assert done.status_code == 200
        last = fake.calls[-1]
        assert last["method"] == ("POST" if action == "rotate" else "DELETE")
        # hogtower is told who is acting, and holds the call to their own credentials too.
        sent = last["json"] if action == "rotate" else last["params"]
        assert sent == {"owner_user_uuid": str(self.user.uuid)}

    @_routes({("POST", f"{W}/hoglake-credentials"): (201, _HLC_ISSUED)})
    def test_create_refuses_a_project_the_warehouse_does_not_serve(
        self, _push_on: MagicMock, _enabled: MagicMock, fake: FakeHogtower
    ) -> None:
        resp = managed_warehouse.create_my_hoglake_credential(
            self.org,
            self.user,
            name="laptop",
            scope="read",
            team_ids=[self.other.id],
            ttl_seconds=None,
            triggered_by=PRINCIPAL,
        )

        assert resp.status_code == 403
        assert fake.calls == []

    @_routes({("GET", f"{W}/hoglake-credentials"): (200, {"hoglake_credentials": []})})
    def test_projects_leave_out_ones_the_warehouse_does_not_serve(
        self, _push_on: MagicMock, _enabled: MagicMock, fake: FakeHogtower
    ) -> None:
        resp = managed_warehouse.list_my_hoglake_credentials(self.org, self.user)

        assert [p["id"] for p in resp.data["projects"]] == [self.team.id]

    @_routes({("GET", f"{W}/hoglake-credentials"): (200, {"hoglake_credentials": []})})
    def test_projects_are_all_visible_ones_when_the_control_plane_cannot_say(
        self, _push_on: MagicMock, _enabled: MagicMock, fake: FakeHogtower
    ) -> None:
        self.memberships.return_value = None

        resp = managed_warehouse.list_my_hoglake_credentials(self.org, self.user)

        assert sorted(p["id"] for p in resp.data["projects"]) == sorted([self.team.id, self.other.id])

    def test_off_without_the_setting(self, _push_on: MagicMock, _enabled: MagicMock) -> None:
        with override_settings(HOGLAKE_TEAM_CREDENTIALS_ENABLED=False):
            resp = managed_warehouse.list_my_hoglake_credentials(self.org, self.user)

        assert resp.status_code == 501

    def test_off_without_the_member_push(self, _push_on: MagicMock, _enabled: MagicMock) -> None:
        _push_on.return_value = False

        resp = managed_warehouse.list_my_hoglake_credentials(self.org, self.user)

        assert resp.status_code == 501
