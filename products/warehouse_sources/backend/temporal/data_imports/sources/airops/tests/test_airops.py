import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.airops.airops import (
    AIROPS_BASE_URL,
    BRAND_KIT_LIST_PATH,
    BRAND_KITS_PATH,
    _make_session,
    airops_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.airops.source import AirOpsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.airops import AirOpsSourceConfig

APPS_URL = f"{AIROPS_BASE_URL}/public_api/airops_apps"
BRAND_KITS_URL = f"{AIROPS_BASE_URL}/{BRAND_KIT_LIST_PATH}"


def _driver() -> SourceDriver:
    return SourceDriver(AirOpsSource(), AirOpsSourceConfig(api_key="k"))


def _source(endpoint: str) -> SourceResponse:
    return airops_source(api_key="k", endpoint=endpoint, team_id=1, job_id="j")


class TestMakeSession:
    def test_disables_sample_capture_and_redirects(self) -> None:
        # Executions carry free-form inputs/output that can hold user secrets the name-based
        # scrubbers can't recognise, so response capture must stay off; redirects stay pinned off
        # so a credentialed request can't be replayed against another host.
        with scripted_network([]) as network:
            _make_session("secret-key")

        assert network.session_options == [
            {
                "capture": False,
                "allow_redirects": False,
                "redact_values": ("secret-key",),
                "headers": {"Accept": "application/json"},
            }
        ]


class TestApps:
    def test_non_list_body_fails_loud(self) -> None:
        # The documented shape is a bare array; a 200 with anything else means the response shape
        # changed — fail loud rather than silently syncing 0 (or garbage) rows.
        result = _driver().run("apps", [ScriptedResponse(json={"data": [{"id": 1}]})])

        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestExecutions:
    def test_fans_out_over_apps_and_paginates(self) -> None:
        result = _driver().run(
            "executions",
            [
                ScriptedResponse(json=[{"id": 10}, {"id": 20}]),  # apps
                ScriptedResponse(
                    json={"data": [{"id": "e1"}], "meta": {"has_more": True, "cursor": "c1"}}
                ),  # app 10 page 1
                ScriptedResponse(
                    json={"data": [{"id": "e2"}], "meta": {"has_more": False, "cursor": None}}
                ),  # app 10 page 2
                ScriptedResponse(json={"data": [{"id": "e3"}], "meta": {"has_more": False}}),  # app 20 page 1
            ],
        )

        # Every execution row is stamped with its parent app id so the flattened table can be joined
        # back and the primary key stays meaningful table-wide.
        assert result.raised is None
        assert result.rows == [
            {"id": "e1", "airops_app_id": 10},
            {"id": "e2", "airops_app_id": 10},
            {"id": "e3", "airops_app_id": 20},
        ]
        # 1 apps call + 2 pages for app 10 + 1 page for app 20.
        assert len(result.requests) == 4
        assert result.urls == [
            APPS_URL,
            f"{APPS_URL}/10/executions?items=100",
            f"{APPS_URL}/10/executions?items=100&cursor=c1",
            f"{APPS_URL}/20/executions?items=100",
        ]
        # Page size is pinned to the endpoint's cap; the second page carries the cursor returned by
        # the first, and a fresh parent starts without one.
        assert result.queries[1:] == [
            {"items": ("100",)},
            {"items": ("100",), "cursor": ("c1",)},
            {"items": ("100",)},
        ]

    def test_stops_when_has_more_false_even_if_cursor_present(self) -> None:
        # An explicit has_more=false ends the app's pagination even when a cursor is echoed back,
        # so the last page isn't paid for twice.
        result = _driver().run(
            "executions",
            [
                ScriptedResponse(json=[{"id": 10}]),
                ScriptedResponse(json={"data": [{"id": "e1"}], "meta": {"has_more": False, "cursor": "c1"}}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "e1", "airops_app_id": 10}]
        assert len(result.requests) == 2

    def test_fails_when_app_missing_id(self) -> None:
        # A missing app id must fail loudly rather than silently dropping that app's executions.
        result = _driver().run("executions", [ScriptedResponse(json=[{"name": "no id"}])])

        assert isinstance(result.raised, ValueError)
        assert "field 'id'" in str(result.raised)


class TestBrandKits:
    def test_missing_data_key_fails_loud(self) -> None:
        # A 200 whose body drops the `data` array means the response shape changed — fail loud
        # instead of silently syncing 0 rows.
        result = _driver().run("brand_kits", [ScriptedResponse(json={"meta": {"total_pages": 1}})])

        assert isinstance(result.raised, Exception)
        assert "data" in str(result.raised)


class TestBrandKitFanout:
    @pytest.mark.parametrize("endpoint", ["prompts", "citations"])
    def test_fans_out_over_brand_kits_and_stamps_parent_id(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={"data": [{"id": 10}, {"id": 20}], "meta": {"total_pages": 1}}),
                ScriptedResponse(json={"data": [{"url": "a"}], "meta": {"total_pages": 1}}),  # kit 10
                ScriptedResponse(json={"data": [{"url": "b"}], "meta": {"total_pages": 1}}),  # kit 20
            ],
        )

        # Every child row is stamped with its parent brand kit id so the flattened table's composite
        # key stays unique across brand kits.
        assert result.raised is None
        assert result.rows == [{"url": "a", "brand_kit_id": 10}, {"url": "b", "brand_kit_id": 20}]
        assert result.urls == [
            BRAND_KITS_URL,
            f"{AIROPS_BASE_URL}/{BRAND_KITS_PATH}/10/{endpoint}/list",
            f"{AIROPS_BASE_URL}/{BRAND_KITS_PATH}/20/{endpoint}/list",
        ]

    @pytest.mark.parametrize("endpoint", ["prompts", "citations"])
    def test_skips_brand_kit_without_aeo_configured(self, endpoint: str) -> None:
        # A brand kit that hasn't configured AEO answers the child endpoint with 412; that brand kit
        # is skipped rather than failing the whole table, and its siblings still sync.
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={"data": [{"id": 10}, {"id": 20}], "meta": {"total_pages": 1}}),
                ScriptedResponse(status=412, json={"error": "AEO not configured"}),  # kit 10
                ScriptedResponse(json={"data": [{"url": "b"}], "meta": {"total_pages": 1}}),  # kit 20
            ],
        )

        assert result.raised is None
        assert result.rows == [{"url": "b", "brand_kit_id": 20}]
        assert len(result.requests) == 3

    @pytest.mark.parametrize("endpoint", ["prompts", "citations"])
    def test_fails_when_brand_kit_missing_id(self, endpoint: str) -> None:
        # A brand kit without an `id` can't be fanned out — fail loud rather than dropping its rows.
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={"data": [{"name": "no id"}], "meta": {"total_pages": 1}})],
        )

        assert isinstance(result.raised, ValueError)
        assert "missing its 'id'" in str(result.raised)


class TestErrorHandling:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_retry_then_raise(self, status: int) -> None:
        # 429/5xx are retried by the framework client; once attempts are exhausted the last
        # retryable error is reraised.
        result = _driver().run("apps", [ScriptedResponse(status=status, json={}) for _ in range(5)])

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5

    @pytest.mark.parametrize(
        "status, reason",
        [(400, "Bad Request"), (401, "Unauthorized"), (403, "Forbidden"), (404, "Not Found")],
    )
    def test_client_errors_propagate_as_httperror(self, status: int, reason: str) -> None:
        # 4xx (bad/expired credentials, missing app) must surface as HTTPError so
        # get_non_retryable_errors can match and permanently fail the sync.
        result = _driver().run("apps", [ScriptedResponse(status=status, json={"error": "nope"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert f"{status} Client Error: {reason}" in str(result.raised)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (200, True),
        ],
    )
    def test_maps_status_to_bool(self, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("key") is expected

        assert len(network.requests_log) == 1
        assert network.requests_log[0].url == APPS_URL
        assert network.requests_log[0].headers["authorization"] == "Bearer key"


class TestAirOpsSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "partition_key", "primary_keys"),
        [
            ("apps", "created_at", ["id"]),
            # Executions are keyed by (app id, id) because execution ids are scoped per app.
            ("executions", "createdAt", ["airops_app_id", "id"]),
            ("brand_kits", "created_at", ["id"]),
            # Fan-out children carry the parent brand kit id in the composite key so rows from two
            # brand kits never collide (which would seed duplicate rows and slow every merge).
            ("prompts", "created_at", ["brand_kit_id", "id"]),
        ],
    )
    def test_partition_and_primary_keys(self, endpoint: str, partition_key: str, primary_keys: list[str]) -> None:
        # Partition on a STABLE creation timestamp (never updated_at), which differs per endpoint.
        response = _source(endpoint)
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
