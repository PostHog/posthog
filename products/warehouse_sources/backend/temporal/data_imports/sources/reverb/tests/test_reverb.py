from datetime import UTC, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.reverb import ReverbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.reverb import (
    ReverbResumeConfig,
    _format_datetime,
    _inject_payout_id,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.settings import PER_PAGE
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.source import ReverbSource


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("string_passthrough", "not-a-date", "not-a-date"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestInjectPayoutId:
    @parameterized.expand(
        [
            (
                "well_formed_href",
                {"_links": {"line_items": {"href": "https://api.reverb.com/api/my/payouts/54/line_items"}}},
                54,
            ),
            ("missing_links", {}, None),
            ("missing_line_items", {"_links": {}}, None),
            ("malformed_href", {"_links": {"line_items": {"href": "not-a-url"}}}, None),
        ]
    )
    def test_id_extraction(self, _name: str, row: dict[str, Any], expected_id: int | None) -> None:
        result = _inject_payout_id(dict(row))
        assert result.get("id") == expected_id


def _response(
    response_key: str,
    items: list[dict[str, Any]] | None,
    *,
    current_page: int | None = None,
    total_pages: int | None = None,
    drop_key: bool = False,
) -> ScriptedResponse:
    body: dict[str, Any] = {}
    if not drop_key:
        body[response_key] = items or []
    if current_page is not None:
        body["current_page"] = current_page
    if total_pages is not None:
        body["total_pages"] = total_pages
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(ReverbSource(), ReverbSourceConfig(api_token="token"))


class TestReverbSourceOrders:
    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "Orders",
            [_response("orders", [{"order_number": "2"}], current_page=2, total_pages=2)],
            resume_state=ReverbResumeConfig(next_page=2),
        )

        assert [r["order_number"] for r in result.rows] == ["2"]
        assert len(result.requests) == 1
        assert result.requests[0].param("page") == "2"

    def test_missing_metadata_full_page_continues(self) -> None:
        full_page = [{"order_number": str(i)} for i in range(PER_PAGE)]
        result = _driver().run(
            "Orders", [_response("orders", full_page), _response("orders", [{"order_number": "last"}])]
        )

        assert len(result.rows) == PER_PAGE + 1
        assert len(result.requests) == 2


class TestReverbSourcePayouts:
    def test_incremental_window_uses_created_date_params(self) -> None:
        result = _driver().run(
            "Payouts",
            [_response("payouts", [], total_pages=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert result.requests[0].param("created_start_date") == "2026-03-04T00:00:00Z"
        assert result.requests[0].param("created_end_date") is not None


class TestValidateCredentials:
    def test_ok(self) -> None:
        with scripted_network([ScriptedResponse(json={})]):
            assert validate_credentials("token", "3.0") == (True, 200)
