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

    def test_unmapped_route_fails_without_calling_hogtower(self, fake: FakeHogtower) -> None:
        out = _mapped("PATCH", "/teams")

        assert out.status_code == 500
        assert fake.calls == []

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

    @_routes(
        {
            ("GET", f"{W}/monitoring/snapshot"): (200, {"sessions": 1}),
            ("GET", f"{W}/monitoring/series"): (200, {"points": []}),
        }
    )
    def test_monitoring_is_passed_through(self, fake: FakeHogtower) -> None:
        assert _mapped("GET", "/monitoring/snapshot").json() == {"sessions": 1}
        params = {"metric": "query_rate", "window": "1h"}
        assert _mapped("GET", "/monitoring/series", params=params).json() == {"points": []}
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

    @_routes({("GET", "/database-names/acme"): (200, {"name": "acme", "available": False, "reason": ""})})
    def test_check_name(self, _enabled: MagicMock, fake: FakeHogtower) -> None:
        resp = managed_warehouse.check_name(ORG, "acme")

        assert (resp.status_code, resp.data) == (200, {"name": "acme", "available": False})

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
