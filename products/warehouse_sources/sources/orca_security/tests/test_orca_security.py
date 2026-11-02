from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.orcasecurity import (
    OrcaSecuritySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.orca_security import (
    OrcaResumeConfig,
    _format_datetime,
    _host,
    _normalize_item,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.settings import PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.source import OrcaSecuritySource


def _response(items: list[dict[str, Any]], *, next_token: int | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"next_page_token": next_token}
    body["data"] = items
    return ScriptedResponse(json=body)


def _page(ids: list[str], *, next_token: int | None = None) -> ScriptedResponse:
    return _response(
        [{"id": i, "type": "Alert", "data": {"AlertId": {"value": i}}} for i in ids], next_token=next_token
    )


def _driver() -> SourceDriver:
    return SourceDriver(OrcaSecuritySource(), OrcaSecuritySourceConfig(api_token="tok", region="us"))


class TestHost:
    @parameterized.expand(
        [
            ("global", "https://api.orcasecurity.io/api"),
            ("us", "https://app.us.orcasecurity.io/api"),
            ("eu", "https://app.eu.orcasecurity.io/api"),
            ("", "https://api.orcasecurity.io/api"),
            ("unknown", "https://api.orcasecurity.io/api"),
        ]
    )
    def test_host_mapping(self, region: str, expected: str) -> None:
        assert _host(region) == expected


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("aware", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "cursor", "cursor"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestNormalizeItem:
    def test_keeps_unwrapped_field(self) -> None:
        assert _normalize_item({"id": "x", "data": {"Raw": {"nested": 1}}})["Raw"] == {"nested": 1}


class TestPagination:
    def test_advances_by_page_length_without_token(self) -> None:
        # A full page with no token advances by the number of rows returned.
        result = _driver().run("alerts", [_page([str(n) for n in range(PAGE_SIZE)]), _page(["x"])])

        assert result.raised is None
        assert [request.json()["start_at_index"] for request in result.requests] == [0, PAGE_SIZE]

    def test_stops_on_empty_page_without_checkpoint(self) -> None:
        result = _driver().run("alerts", [_response([])])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run("alerts", [_page(["r"])], resume_state=OrcaResumeConfig(start_at_index=PAGE_SIZE))

        # First fetch continues from the saved offset rather than 0.
        assert result.raised is None
        assert result.requests[0].json()["start_at_index"] == PAGE_SIZE


class TestIncrementalBody:
    def test_filter_in_body_only_when_incremental_used(self) -> None:
        result = _driver().run(
            "alerts",
            [_page(["a"])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].json()["query"]["with"]["values"][0]["values"] == ["2026-01-01T00:00:00+00:00"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True),
        ]
    )
    def test_status_mapping(self, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            ok, _err = validate_credentials("tok", "us")

        assert ok is expected
        assert network.requests_log[0].path == "/api/serving-layer/query"
