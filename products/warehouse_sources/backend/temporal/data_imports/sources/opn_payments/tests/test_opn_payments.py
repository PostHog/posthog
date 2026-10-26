from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opnpayments import (
    OpnPaymentsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.opn_payments import (
    OpnPaymentsResumeConfig,
    _to_iso8601,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.source import OpnPaymentsSource


def _envelope(data: list[dict[str, Any]], offset: int, total: int, limit: int = 100) -> dict[str, Any]:
    return {"object": "list", "data": data, "offset": offset, "limit": limit, "total": total}


def _page(size: int, start_id: int = 0) -> list[dict[str, Any]]:
    return [{"id": f"chrg_{start_id + i}"} for i in range(size)]


def _driver() -> SourceDriver:
    return SourceDriver(OpnPaymentsSource(), OpnPaymentsSourceConfig(secret_key="skey_test_123"))


class TestToIso8601:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        assert _to_iso8601(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (200, True, None),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool, expected_message: str | None) -> None:
        answer = ScriptedResponse(status=status_code, json={})
        script = always(answer) if status_code == 500 else [answer]
        with scripted_network(script) as network:
            valid, message = validate_credentials("skey_test_123", "2019-05-29")

        assert valid is expected_valid
        assert message == expected_message
        assert {request.path for request in network.requests_log} == {"/account"}

    def test_swallows_request_exceptions(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            valid, message = validate_credentials("skey_test_123", "2019-05-29")

        assert valid is False
        assert message == "Could not reach the Opn Payments API."
        assert {request.path for request in network.requests_log} == {"/account"}


class TestOpnPaymentsSourcePagination:
    def test_walks_full_pages_by_offset_until_a_short_page(self) -> None:
        result = _driver().run(
            "Charges",
            [
                ScriptedResponse(json=_envelope(_page(100), offset=0, total=150)),
                ScriptedResponse(json=_envelope(_page(50, start_id=100), offset=100, total=150)),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == 150
        assert result.params("offset") == ["0", "100"]
        assert result.params("limit") == ["100", "100"]


class TestOpnPaymentsSourceIncremental:
    def test_full_refresh_never_sends_from_filter(self) -> None:
        result = _driver().run(
            "Charges",
            [ScriptedResponse(json=_envelope([{"id": "chrg_1"}], offset=0, total=1))],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("from") is None

    def test_incremental_defaults_to_epoch_on_first_sync(self) -> None:
        result = _driver().run(
            "Charges",
            [ScriptedResponse(json=_envelope([], offset=0, total=0))],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert result.raised is None
        assert result.requests[0].param("from") == "1970-01-01T00:00:00Z"


class TestOpnPaymentsSourceResume:
    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "Charges",
            [ScriptedResponse(json=_envelope([{"id": "9"}], offset=200, total=201))],
            resume_state=OpnPaymentsResumeConfig(offset=200),
        )

        assert result.raised is None
        assert result.params("offset") == ["200"]
