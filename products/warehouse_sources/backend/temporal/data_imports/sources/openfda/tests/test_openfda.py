from datetime import date, datetime
from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openfda import (
    OpenFDASourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openfda.openfda import (
    PAGE_SIZE,
    OpenFDAResumeConfig,
    _build_params,
    _format_date_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openfda.settings import OPENFDA_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.openfda.source import OpenFDASource


def _driver() -> SourceDriver:
    return SourceDriver(OpenFDASource(), OpenFDASourceConfig())


def _page(results: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
    return ScriptedResponse(json={"meta": {}, "results": results}, headers=headers)


class TestFormatDateValue:
    @parameterized.expand(
        [
            ("datetime", datetime(2020, 1, 2, 3, 4, 5), "20200102"),
            ("date", date(2020, 1, 2), "20200102"),
            ("yyyymmdd_string", "20200102", "20200102"),
            ("dashed_string", "2020-01-02", "20200102"),
        ]
    )
    def test_formats_to_yyyymmdd(self, _name: str, value: Any, expected: str) -> None:
        # The openFDA search date range only accepts YYYYMMDD; a mis-formatted watermark silently
        # matches nothing (404) and wedges the incremental sync.
        assert _format_date_value(value) == expected


class TestBuildParams:
    def test_incremental_endpoint_bounds_by_date_and_sorts_ascending(self) -> None:
        params = _build_params(
            OPENFDA_ENDPOINTS["drug_enforcement"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2020, 1, 1),
            incremental_field=None,
        )
        # The server-side date filter must survive: without it every "incremental" sync re-scans the
        # whole dataset. Ascending sort keeps the pipeline watermark advancing monotonically.
        assert params["search"] == "report_date:[20200101 TO 99991231]"
        assert params["sort"] == "report_date:asc"
        assert params["limit"] == PAGE_SIZE


class TestPagination:
    def test_follows_link_cursor_across_pages(self) -> None:
        result = _driver().run(
            "drug_enforcement",
            [
                _page([{"recall_number": "D-1"}], next_url="https://api.fda.gov/p2"),
                _page([{"recall_number": "D-2"}]),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"recall_number": "D-1"}, {"recall_number": "D-2"}]
        # The first request carries the page size; the second follows the self-contained next link.
        assert result.paths == ["/drug/enforcement.json", "/p2"]
        assert result.params("limit") == [str(PAGE_SIZE), None]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "drug_enforcement",
            [_page([{"recall_number": "D-2"}])],
            resume_state=OpenFDAResumeConfig(next_url="https://api.fda.gov/p2"),
        )
        # Resume must start at the saved cursor, not rebuild the initial URL (which would re-pull page
        # 1) — so the seeded next-page URL replaces the initial params entirely.
        assert result.raised is None
        assert result.rows == [{"recall_number": "D-2"}]
        assert result.paths == ["/p2"]
        assert result.queries == [{}]

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_is_retried(self, _name: str, status: int) -> None:
        result = _driver().run(
            "drug_enforcement",
            [ScriptedResponse(status=status), _page([{"recall_number": "D-1"}])],
        )
        # 429 / 5xx are transient — the client backs off and retries rather than failing the sync.
        assert result.raised is None
        assert result.rows == [{"recall_number": "D-1"}]
        assert result.paths == ["/drug/enforcement.json", "/drug/enforcement.json"]

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_auth_error_raises(self, _name: str, status: int) -> None:
        result = _driver().run("drug_enforcement", [ScriptedResponse(status=status, json={"error": {}})])
        # 401/403 (bad or over-quota key) can never be fixed by retrying — they surface as an error.
        assert isinstance(result.raised, HTTPError)
        assert result.paths == ["/drug/enforcement.json"]

    def test_missing_results_key_raises_loudly(self) -> None:
        result = _driver().run("drug_enforcement", [ScriptedResponse(json={"meta": {}})])
        # openFDA guarantees `results` on a 200; an unexpected shape must surface, not silently look
        # like an empty page.
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)

    @parameterized.expand(
        [
            ("off_host", "https://evil.example.com/next"),
            ("insecure_scheme", "http://api.fda.gov/next"),
            ("subdomain_spoof", "https://api.fda.gov.evil.example.com/next"),
        ]
    )
    def test_off_host_next_cursor_is_rejected(self, _name: str, next_url: str) -> None:
        # A poisoned `Link` header would send the API key (Basic auth) off-host or hit an internal
        # address. Following it must fail loudly, not be saved and requested.
        result = _driver().run("drug_enforcement", [_page([], next_url=next_url)])
        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/drug/enforcement.json"]

    def test_off_host_resume_cursor_is_rejected(self) -> None:
        # Poisoned resume state must not be followed — it would leak the API key off-host.
        result = _driver().run(
            "drug_enforcement", [], resume_state=OpenFDAResumeConfig(next_url="https://evil.example.com/p2")
        )
        assert isinstance(result.raised, ValueError)
        assert result.requests == []


class TestOpenfdaSource:
    @parameterized.expand(
        [
            ("drug_enforcement", ["recall_number"], "report_date"),
            ("drug_ndc", ["product_id"], None),
            ("device_510k", ["k_number"], "decision_date"),
        ]
    )
    def test_source_response_carries_endpoint_config(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        result = _driver().run(endpoint, [_page([])])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key is None:
            # Full-refresh endpoint: no sort requested, so arrival order is undefined.
            assert response.partition_mode is None
            assert response.sort_mode is None
        else:
            # Incremental endpoint: ascending sort must be declared so the pipeline checkpoints the
            # watermark correctly, and the stable date field partitions the table.
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
            assert response.sort_mode == "asc"


class TestValidateCredentials:
    def test_failure(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]) as network:
            assert validate_credentials("key") is False
        assert [request.path for request in network.requests_log] == ["/drug/enforcement.json"]
