from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.descope.descope import (
    DescopeResumeConfig,
    _audit_body,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.descope.settings import (
    ENDPOINTS,
    PARTITION_KEYS,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.descope.source import DescopeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.descope import (
    DescopeSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(DescopeSource(), DescopeSourceConfig(project_id="P2abc", management_key="mgmt-key"))


def _response(payload: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json=payload)


class TestAuditBody:
    def test_incremental_body_sets_from(self) -> None:
        body = _audit_body(should_use_incremental_field=True, db_incremental_field_last_value=1700000000000)
        assert body == {"from": 1700000000000}


class TestValidateCredentials:
    def test_sends_bearer_token(self) -> None:
        with scripted_network([_response({})]) as network:
            assert validate_credentials("P2abc", "mgmt-key")

        assert network.requests_log[0].path == "/v1/mgmt/projects/list"
        assert network.requests_log[0].headers["authorization"] == "Bearer P2abc:mgmt-key"


class TestUsersPagination:
    def test_paginates_via_page_number_in_json_body(self) -> None:
        full_page = [{"userId": f"u{i}"} for i in range(100)]
        # PageNumberPaginator only stops on a fully empty page, so a short (but non-empty)
        # second page still triggers a third, empty request before pagination ends.
        result = _driver().run(
            "Users",
            [
                _response({"users": full_page}),
                _response({"users": [{"userId": "last"}]}),
                _response({"users": []}),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == 101
        assert [request.json()["page"] for request in result.requests] == [0, 1, 2]
        # Checkpoint saved after each page with a next page pending.
        assert result.saved_states == [DescopeResumeConfig(page=1), DescopeResumeConfig(page=2)]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run("Users", [_response({"users": []})], resume_state=DescopeResumeConfig(page=3))

        assert result.raised is None
        assert result.requests[0].json()["page"] == 3

    def test_incremental_body_carries_watermark(self) -> None:
        result = _driver().run(
            "Users",
            [_response({"users": []})],
            should_use_incremental_field=True,
            incremental_field="modifiedTime",
            db_incremental_field_last_value=1700000000000,
        )

        assert result.raised is None
        assert result.requests[0].json()["fromModifiedTime"] == 1700000000000
        assert result.requests[0].json()["sort"] == [{"field": "modifiedTime", "desc": False}]


class TestAuditFetch:
    def test_single_fetch_synthesizes_row_id(self) -> None:
        result = _driver().run(
            "Audit", [_response({"audits": [{"userId": "u1", "action": "login", "occurred": 1700000000000}]})]
        )

        assert result.raised is None
        assert len(result.requests) == 1
        assert "id" in result.rows[0]


class TestDescopeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        selector = {
            "Users": "users",
            "Audit": "audits",
            "Tenants": "tenants",
            "Roles": "roles",
            "AccessKeys": "keys",
            "Permissions": "permissions",
            "Analytics": "analytics",
            "Groups": "tenants",
            "UserHistory": "users",
        }[endpoint]
        result = _driver().run(endpoint, [_response({selector: []})])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == PRIMARY_KEYS[endpoint]
        assert result.response.sort_mode == "asc"
        # Permissions, Groups and Analytics carry no timestamp, so they sync unpartitioned;
        # partitioning them on a field their rows lack would fail the write.
        partition_key = PARTITION_KEYS.get(endpoint)
        assert result.response.partition_mode == ("datetime" if partition_key else None)
        assert result.response.partition_keys == ([partition_key] if partition_key else None)


class TestGroupsFanOut:
    def test_loads_groups_per_tenant_and_stamps_the_tenant_id(self) -> None:
        result = _driver().run(
            "Groups",
            [
                _response({"tenants": [{"id": "T1"}, {"id": "T2"}]}),
                _response({"groups": [{"id": "g1", "display": "Engineering"}]}),
                _response({"groups": [{"id": "g1", "display": "Support"}]}),
            ],
        )

        assert result.raised is None
        # The group id repeats across tenants, which is why the tenant has to ride on the row —
        # the primary key is ["tenantId", "id"].
        assert result.rows == [
            {"id": "g1", "display": "Engineering", "tenantId": "T1"},
            {"id": "g1", "display": "Support", "tenantId": "T2"},
        ]
        assert result.requests[1].json() == {"tenantId": "T1"}
        assert result.requests[2].json() == {"tenantId": "T2"}


class TestUserHistoryFanOut:
    def test_posts_each_user_page_and_checkpoints_after_it(self) -> None:
        result = _driver().run(
            "UserHistory",
            [
                _response({"users": [{"userId": "u1"}, {"userId": "u2"}]}),
                _response({"usersAuthHistory": [{"userId": "u1", "loginTime": 1700000000}]}),
                _response({"users": []}),
            ],
        )

        assert result.raised is None
        assert result.requests[0].json()["page"] == 0
        assert result.requests[1].json() == {"userIds": ["u1", "u2"]}
        assert result.requests[2].json()["page"] == 1
        assert len(result.rows) == 1
        assert len(result.rows[0]["id"]) == 64
        # Saved only once the page's history rows were yielded, so a resume cannot skip them.
        assert result.saved_states == [DescopeResumeConfig(page=1), DescopeResumeConfig(page=2)]

    def test_resumes_from_the_saved_user_page(self) -> None:
        result = _driver().run("UserHistory", [_response({"users": []})], resume_state=DescopeResumeConfig(page=4))

        assert result.raised is None
        assert result.requests[0].json()["page"] == 4


class TestAnalyticsFetch:
    def test_synthesizes_a_row_id_per_grouping_bucket(self) -> None:
        result = _driver().run(
            "Analytics",
            [
                _response(
                    {
                        "analytics": [
                            {"created": "2026-09-01", "action": "login", "method": "otp", "cnt": "12"},
                            {"created": "2026-09-01", "action": "login", "method": "oauth", "cnt": "3"},
                        ]
                    }
                )
            ],
        )

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.rows[0]["id"] != result.rows[1]["id"]
