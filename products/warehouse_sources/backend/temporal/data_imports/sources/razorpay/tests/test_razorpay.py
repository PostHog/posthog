from typing import Any, Optional

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.razorpay import (
    RazorpaySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.razorpay import (
    INCREMENTAL_LOOKBACK_SECONDS,
    MIN_FROM_TIMESTAMP,
    RazorpayResumeConfig,
    build_from_param,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.settings import PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.source import RazorpaySource


def _collection_response(items: list[dict[str, Any]], status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json={"entity": "collection", "count": len(items), "items": items})


def _items(count: int, start: int = 0) -> list[dict[str, Any]]:
    return [{"id": f"pay_{start + i}", "created_at": 1_750_000_000 + start + i} for i in range(count)]


def _drive(
    responses: list[ScriptedResponse | BaseException],
    endpoint: str = "Payments",
    **inputs: Any,
) -> DriveResult:
    config = RazorpaySourceConfig(key_id="rzp_test_key", key_secret="secret")
    return SourceDriver(RazorpaySource(), config).run(endpoint, responses, **inputs)


class TestRazorpayPagination:
    def test_resume_seeds_skip_from_saved_state(self) -> None:
        result = _drive([_collection_response(_items(1))], resume_state=RazorpayResumeConfig(skip=200))

        assert result.params("skip") == ["200"]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _drive([_collection_response(_items(1))])

        assert result.params("skip") == ["0"]


class TestRazorpayIncremental:
    def test_incremental_sync_sends_lookback_adjusted_from_on_every_page(self) -> None:
        watermark = 1_750_000_000

        result = _drive(
            [
                _collection_response(_items(PAGE_SIZE)),
                _collection_response(_items(2, start=PAGE_SIZE)),
            ],
            incremental_field="created_at",
            db_incremental_field_last_value=watermark,
        )

        expected_from = str(watermark - INCREMENTAL_LOOKBACK_SECONDS)
        assert result.params("from") == [expected_from, expected_from]

    def test_full_refresh_endpoint_never_sends_from(self) -> None:
        # Disputes doesn't document `from`/`to`; sending unknown params risks a 400 from
        # Razorpay's strict param validation.
        result = _drive(
            [_collection_response(_items(1))],
            endpoint="Disputes",
            incremental_field="created_at",
            db_incremental_field_last_value=1_750_000_000,
        )

        assert result.params("from") == [None]

    @pytest.mark.parametrize(
        ("last_value", "expected"),
        [
            (None, None),
            (1_750_000_000, 1_750_000_000 - INCREMENTAL_LOOKBACK_SECONDS),
            ("1750000000", 1_750_000_000 - INCREMENTAL_LOOKBACK_SECONDS),
            (MIN_FROM_TIMESTAMP + 10, MIN_FROM_TIMESTAMP),
            ("not-a-timestamp", None),
        ],
    )
    def test_build_from_param(self, last_value: Any, expected: Optional[int]) -> None:
        assert build_from_param(last_value) == expected


class TestRazorpayValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (200, True),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            assert validate_credentials("rzp_test_key", "secret") is expected

        assert network.requests_log[0].path == "/v1/payments"
        assert network.requests_log[0].param("count") == "1"
