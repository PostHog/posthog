from collections.abc import Callable
from datetime import date
from typing import Any, Literal

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.drata.drata import (
    REGION_BASE_URLS,
    DrataResumeConfig,
    base_url_for_region,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.drata.settings import DRATA_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.drata.source import DrataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.drata import DrataSourceConfig

US_BASE_URL = REGION_BASE_URLS["US"]


def _driver(region: Literal["US", "EU", "APAC"] = "US") -> SourceDriver:
    return SourceDriver(DrataSource(), DrataSourceConfig(api_key="drata_key", region=region))


def _page(rows: list[dict[str, Any]], cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": rows, "pagination": {"cursor": cursor}})


class TestTopLevelCursorPagination:
    @staticmethod
    def _pages(request: RecordedRequest) -> ScriptedResponse:
        if request.param("cursor") == "c2":
            return _page([{"id": 2}])
        return _page([{"id": 1}], "c2")

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run("users", self._pages, resume_state=DrataResumeConfig(cursor="c2"))
        assert result.raised is None
        # The first page must never be re-fetched on resume.
        assert result.rows == [{"id": 2}]
        assert result.requests[0].param("cursor") == "c2"

    @parameterized.expand([("US",), ("EU",), ("APAC",)])
    def test_requests_hit_the_selected_region_host(self, region: Literal["US", "EU", "APAC"]) -> None:
        result = _driver(region).run("users", [_page([])])
        assert result.raised is None
        request = result.requests[0]
        assert request.origin + request.path == f"{REGION_BASE_URLS[region]}/users"


class TestEventsIncremental:
    @staticmethod
    def _pages(request: RecordedRequest) -> ScriptedResponse:
        if request.param("cursor") is None:
            return _page([{"id": "e1"}], "c2")
        return _page([{"id": "e2"}])

    def test_date_watermark_formatted_as_utc_datetime(self) -> None:
        result = _driver().run(
            "events",
            self._pages,
            db_incremental_field_last_value=date(2026, 1, 2),
            incremental_field="createdAt",
        )
        assert result.raised is None
        assert result.requests[0].param("createdAtStartDate") == "2026-01-02T00:00:00.000Z"

    def test_unknown_incremental_field_raises(self) -> None:
        result = _driver().run(
            "events",
            [],
            db_incremental_field_last_value="2026-01-01",
            incremental_field="updatedAt",
        )
        assert isinstance(result.raised, ValueError)
        assert "no server-side filter" in str(result.raised)

    @parameterized.expand(
        [
            ("incremental_disabled", False, "2026-01-01"),
            ("no_last_value", True, None),
        ]
    )
    def test_no_filter_param_without_watermark(self, _name: str, should_use: bool, last_value: Any) -> None:
        result = _driver().run(
            "events",
            self._pages,
            should_use_incremental_field=should_use,
            db_incremental_field_last_value=last_value,
            incremental_field="createdAt" if should_use else None,
        )
        assert result.raised is None
        assert result.requests[0].param("createdAtStartDate") is None


class TestWorkspaceFanOut:
    @staticmethod
    def _pages(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("/workspaces"):
            return _page([{"id": 10}, {"id": 20}])
        if request.path.endswith("/workspaces/10/controls"):
            if request.param("cursor") is None:
                return _page([{"id": 1}], "w10c2")
            return _page([{"id": 2}])
        if request.path.endswith("/workspaces/20/controls"):
            return _page([{"id": 1}])
        raise AssertionError(f"unexpected path {request.path}")

    def test_walks_every_workspace_and_injects_workspace_id(self) -> None:
        result = _driver().run("controls", self._pages)
        assert result.raised is None
        # Control id 1 appears in both workspaces; the injected workspaceId keeps the
        # ["workspaceId", "id"] primary key unique table-wide.
        assert result.rows == [
            {"id": 1, "workspaceId": 10},
            {"id": 2, "workspaceId": 10},
            {"id": 1, "workspaceId": 20},
        ]

    def test_deleted_bookmark_parent_starts_over(self) -> None:
        result = _driver().run(
            "controls",
            self._pages,
            resume_state=DrataResumeConfig(
                fanout_state={
                    "completed": ["/workspaces/999/controls"],
                    "current": None,
                    "child_state": None,
                }
            ),
        )
        assert result.raised is None
        assert len(result.rows) == 3

    def test_parent_403_fails_the_sync(self) -> None:
        result = _driver().run(
            "controls",
            route({"/workspaces": [_page([{"id": 10}])], "/workspaces/10/controls": [ScriptedResponse(status=403)]}),
        )
        assert isinstance(result.raised, requests.HTTPError)

    @parameterized.expand(
        [
            ("risks", "risks", "/risk-registers", "/risk-registers/5/risks", "riskRegisterId"),
            ("assigned_policies", "user_assigned_policies", "/users", "/users/5/assigned-policies", "userId"),
        ]
    )
    def test_children_of_other_parents_inject_their_own_parent_column(
        self,
        _name: str,
        endpoint: str,
        parent_path: str,
        child_path: str,
        parent_column: str,
    ) -> None:
        result = _driver().run(
            endpoint,
            route({parent_path: [_page([{"id": 5}])], child_path: [_page([{"id": 1}])]}),
        )
        assert result.raised is None
        assert result.rows == [{"id": 1, parent_column: 5}]


class TestControlJunctionFanOut:
    """Control junctions hang two fan-out levels deep: workspaces -> controls -> junction."""

    @staticmethod
    def _route(child_segment: str) -> Callable[[RecordedRequest], ScriptedResponse]:
        return route(
            {
                "/workspaces": [_page([{"id": 10}])],
                "/workspaces/10/controls": [_page([{"id": 88}])],
                f"/workspaces/10/controls/88/{child_segment}": [_page([{"id": 4}])],
            }
        )

    @parameterized.expand(
        [
            ("requirements", "control_requirements", "requirements"),
            ("owners", "control_owners", "owners"),
        ]
    )
    def test_binds_control_id_and_carries_both_ancestor_ids(self, _name: str, endpoint: str, segment: str) -> None:
        result = _driver().run(endpoint, self._route(segment))
        assert result.raised is None
        assert result.requests[-1].origin + result.requests[-1].path == (
            f"{US_BASE_URL}/workspaces/10/controls/88/{segment}"
        )
        # Both junctions repeat their `id` across controls — a requirement is mapped by many
        # controls, an owner owns many — so the control id has to be part of the key.
        assert result.rows == [{"id": 4, "controlId": 88, "workspaceId": 10}]


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        result = _driver().run("users", always(ScriptedResponse(status=status, json={})))
        assert isinstance(result.raised, RESTClientRetryableError)

    @parameterized.expand(
        [
            ("unauthorized", 401, "Unauthorized"),
            ("forbidden", 403, "Forbidden"),
            ("terms", 412, "Precondition Failed"),
        ]
    )
    def test_client_errors_raise_http_error_matchable_by_host_prefix(
        self, _name: str, status: int, _reason: str
    ) -> None:
        result = _driver().run("users", [ScriptedResponse(status=status, json={})])
        assert isinstance(result.raised, requests.HTTPError)
        # The base host prefix stays intact so `get_non_retryable_errors()` can still match it.
        assert "for url: https://public-api" in str(result.raised)

    @parameterized.expand(
        [
            ("bare_list", b'[{"id": 1}]'),
            ("missing_data", b'{"pagination": {}}'),
            ("data_is_object", b'{"data": {"id": 1}}'),
        ]
    )
    def test_unexpected_payload_is_retryable(self, _name: str, raw: bytes) -> None:
        result = _driver().run("users", always(ScriptedResponse(body=raw)))
        assert isinstance(result.raised, RESTClientRetryableError)


class TestCredentialValidation:
    @parameterized.expand(
        [
            # A genuine token without the workspaces read scope must not block source creation —
            # custom-scoped keys may only grant the endpoints the user wants to sync.
            ("forbidden_scope", 403, True, None),
            (
                "terms_not_accepted",
                412,
                False,
                "You must accept the Drata API terms and conditions in your Drata account before connecting",
            ),
        ]
    )
    def test_validate_credentials_status_mapping(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("drata_key", "US") == (expected_valid, expected_message)
        assert network.requests_log[0].path == "/public/v2/workspaces"

    @parameterized.expand(
        [("lowercase", "eu", "EU"), ("unknown_falls_back_to_us", "atlantis", "US"), ("none", None, "US")]
    )
    def test_base_url_for_region_normalizes(self, _name: str, region: str | None, expected: str) -> None:
        assert base_url_for_region(region) == REGION_BASE_URLS[expected]


class TestDrataSourceResponse:
    @staticmethod
    def _response(endpoint: str) -> SourceResponse:
        result = _driver().run(endpoint, always(_page([])))
        assert result.raised is None
        assert result.response is not None
        return result.response

    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_primary_keys_match_endpoint_config(self, endpoint: str) -> None:
        response = self._response(endpoint)
        assert response.name == endpoint
        assert response.primary_keys == DRATA_ENDPOINTS[endpoint].primary_keys

    @parameterized.expand(
        [
            ("controls",),
            ("monitoring_tests",),
            ("evidence_library",),
            ("frameworks",),
            ("framework_requirements",),
            ("tasks",),
            ("audits",),
        ]
    )
    def test_workspace_children_use_composite_primary_key(self, endpoint: str) -> None:
        # Child ids aren't documented as unique beyond their workspace; a bare ["id"] key would
        # multi-match on merge and duplicate rows across workspaces.
        assert self._response(endpoint).primary_keys == ["workspaceId", "id"]

    @parameterized.expand([(e,) for e in ENDPOINTS if e != "events"])
    def test_full_refresh_endpoints_declare_asc(self, endpoint: str) -> None:
        assert self._response(endpoint).sort_mode == "asc"
