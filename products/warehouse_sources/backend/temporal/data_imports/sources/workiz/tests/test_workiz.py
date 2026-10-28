from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.workiz import WorkizSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.workiz.settings import PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.workiz.source import WorkizSource
from products.warehouse_sources.backend.temporal.data_imports.sources.workiz.workiz import (
    WorkizResumeConfig,
    get_resource,
    validate_credentials,
)


def _job(uuid: str) -> dict[str, Any]:
    return {"flag": True, "data": {"UUID": uuid, "Status": "Submitted"}}


def _driver() -> SourceDriver:
    return SourceDriver(WorkizSource(), WorkizSourceConfig(api_token="tok"))


class TestPagination:
    def test_paginates_and_progresses_offset(self) -> None:
        full_page = [{"UUID": str(i)} for i in range(PAGE_SIZE)]
        result = _driver().run(
            "Leads",
            [ScriptedResponse(json=full_page), ScriptedResponse(json=[{"UUID": "last"}])],
        )

        assert [r["UUID"] for r in result.rows] == [*(str(i) for i in range(PAGE_SIZE)), "last"]
        assert result.requests[0].param("offset") == "0"
        assert result.requests[0].param("records") == str(PAGE_SIZE)
        assert result.requests[1].param("offset") == str(PAGE_SIZE)
        assert result.saved_states == [WorkizResumeConfig(offset=PAGE_SIZE)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "Leads",
            [ScriptedResponse(json=[{"UUID": "x"}])],
            resume_state=WorkizResumeConfig(offset=PAGE_SIZE),
        )

        assert result.requests[0].param("offset") == str(PAGE_SIZE)

    @parameterized.expand([("Team",), ("TimeOff",)])
    def test_unpaginated_endpoints_send_one_request_with_no_offset(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[{"id": "1"}])])

        assert len(result.rows) == 1
        assert len(result.requests) == 1
        assert result.requests[0].param("offset") is None
        assert result.requests[0].param("records") is None

    def test_jobs_unwraps_flag_data_wrapper(self) -> None:
        # Workiz's OpenAPI spec wraps each job/all item as {"flag": bool, "data": Job}.
        result = _driver().run("Jobs", [ScriptedResponse(json=[_job("a"), _job("b")])])

        assert [r["UUID"] for r in result.rows] == ["a", "b"]
        assert all("flag" not in r and "data" not in r for r in result.rows)


class TestIncrementalParams:
    def test_incremental_sync_uses_last_synced_date(self) -> None:
        import datetime

        result = _driver().run(
            "Leads",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.datetime(2024, 3, 15, 9, 0, 0),
        )

        assert result.requests[0].param("start_date") == "2024-03-15"

    @parameterized.expand([("Team",), ("TimeOff",)])
    def test_unpaginated_endpoints_have_no_start_date_param(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False, incremental_field=None)
        resource_endpoint = resource["endpoint"]
        assert isinstance(resource_endpoint, dict)
        assert resource_endpoint.get("params") is None


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status: int) -> None:
        result = _driver().run(
            "Leads",
            [ScriptedResponse(status=status), ScriptedResponse(json=[{"UUID": "ok"}])],
        )

        assert [r["UUID"] for r in result.rows] == ["ok"]
        assert len(result.requests) == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_error_status_raises(self, _name: str, status: int) -> None:
        result = _driver().run("Leads", [ScriptedResponse(status=status)])

        assert isinstance(result.raised, HTTPError)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            (
                "unauthorized",
                401,
                False,
                "Invalid API token. Check Settings > Integrations > Developer in Workiz and try again.",
            ),
            (
                "forbidden",
                403,
                False,
                "Invalid API token. Check Settings > Integrations > Developer in Workiz and try again.",
            ),
            ("server_error", 500, False, "Workiz returned HTTP 500."),
        ]
    )
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))):
            assert validate_credentials("tok") == (expected_valid, expected_message)
