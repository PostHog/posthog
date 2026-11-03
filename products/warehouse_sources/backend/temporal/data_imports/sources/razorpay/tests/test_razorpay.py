from datetime import datetime
from typing import Any, Optional

import pytest
from unittest.mock import patch

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
    MISSING_ACCOUNT_NUMBER_ERROR,
    RECON_TIMEZONE,
    RazorpayResumeConfig,
    ReconMonth,
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
    account_number: Optional[str] = None,
    **inputs: Any,
) -> DriveResult:
    config = RazorpaySourceConfig(key_id="rzp_test_key", key_secret="secret", razorpayx_account_number=account_number)
    return SourceDriver(RazorpaySource(), config).run(endpoint, responses, **inputs)


def _ist_timestamp(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=RECON_TIMEZONE).timestamp())


def _recon_items(count: int) -> list[dict[str, Any]]:
    return [{"entity_id": f"pay_{i}", "settlement_id": "setl_1", "created_at": 1_750_000_000} for i in range(count)]


def _current_month(year: int, month: int) -> Any:
    return patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.razorpay._current_recon_month",
        return_value=ReconMonth(year=year, month=month),
    )


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


class TestRazorpaySettlementRecon:
    def test_walks_each_month_page_by_page_up_to_the_current_month(self) -> None:
        with _current_month(2026, 2):
            result = _drive(
                [
                    _collection_response(_recon_items(PAGE_SIZE)),
                    _collection_response(_recon_items(2)),
                    _collection_response([]),
                ],
                endpoint="SettlementRecon",
                incremental_field="settled_at",
                db_incremental_field_last_value=_ist_timestamp(2026, 1, 20),
            )

        assert result.raised is None
        assert result.paths == ["/v1/settlements/recon/combined"] * 3
        assert list(zip(result.params("year"), result.params("month"), result.params("skip"))) == [
            ("2026", "1", "0"),
            ("2026", "1", str(PAGE_SIZE)),
            ("2026", "2", "0"),
        ]
        assert len(result.rows) == PAGE_SIZE + 2
        assert result.committed_states[-1] == RazorpayResumeConfig(skip=0, recon_year=2026, recon_month=3)

    @pytest.mark.parametrize(
        ("current_month", "inputs", "expected_first_request"),
        [
            ((2014, 1), {}, ("2014", "1", "0")),
            (
                (2026, 2),
                {"incremental_field": "settled_at", "db_incremental_field_last_value": _ist_timestamp(2026, 3, 2)},
                ("2026", "2", "0"),
            ),
            (
                (2025, 6),
                {"resume_state": RazorpayResumeConfig(skip=200, recon_year=2025, recon_month=6)},
                ("2025", "6", "200"),
            ),
        ],
    )
    def test_start_month(
        self, current_month: tuple[int, int], inputs: dict[str, Any], expected_first_request: tuple[str, str, str]
    ) -> None:
        with _current_month(*current_month):
            result = _drive([_collection_response([])], endpoint="SettlementRecon", **inputs)

        assert result.raised is None
        assert (result.params("year")[0], result.params("month")[0], result.params("skip")[0]) == expected_first_request


class TestRazorpayPaymentLinks:
    def test_pages_through_links_with_count_and_skip(self) -> None:
        links = [{"id": f"plink_{i}", "created_at": 1_750_000_000} for i in range(PAGE_SIZE + 1)]

        result = _drive(
            [
                ScriptedResponse(json={"payment_links": links[:PAGE_SIZE]}),
                ScriptedResponse(json={"payment_links": links[PAGE_SIZE:]}),
            ],
            endpoint="PaymentLinks",
        )

        assert result.raised is None
        assert result.params("skip") == ["0", str(PAGE_SIZE)]
        assert result.params("count") == [str(PAGE_SIZE)] * 2
        assert len(result.rows) == PAGE_SIZE + 1


class TestRazorpayXTransactions:
    def test_sends_account_number_on_every_page(self) -> None:
        result = _drive(
            [
                _collection_response(_items(PAGE_SIZE)),
                _collection_response(_items(1, start=PAGE_SIZE)),
            ],
            endpoint="RazorpayXTransactions",
            account_number="7878780080316316",
            incremental_field="created_at",
            db_incremental_field_last_value=1_750_000_000,
        )

        assert result.params("account_number") == ["7878780080316316", "7878780080316316"]
        assert "7878780080316316" in result.session_options[0]["redact_values"]
        assert result.params("from") == [str(1_750_000_000 - INCREMENTAL_LOOKBACK_SECONDS)] * 2

    def test_fails_without_an_account_number(self) -> None:
        result = _drive([], endpoint="RazorpayXTransactions")

        assert result.requests == []
        assert result.raised is not None
        assert MISSING_ACCOUNT_NUMBER_ERROR in str(result.raised)


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
