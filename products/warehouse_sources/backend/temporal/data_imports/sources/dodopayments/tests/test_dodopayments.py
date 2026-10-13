from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.dodopayments import (
    DodoPaymentsResumeConfig,
    to_iso8601,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.settings import (
    DODOPAYMENTS_ENDPOINTS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.source import DodoPaymentsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dodopayments import (
    DodoPaymentsSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(DodoPaymentsSource(), DodoPaymentsSourceConfig(api_key="test-api-key", mode="live"))


def _response(items: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"items": items})


def _page(size: int, start: int = 0) -> ScriptedResponse:
    return _response([{"payment_id": f"pay_{start + i}", "created_at": "2024-05-01T00:00:00Z"} for i in range(size)])


class TestToIso8601:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (True, None),
            # A datetime watermark must not be str()'d: "2024-05-01 10:00:00+00:00" is not
            # ISO-8601 and the date filters reject it.
            (datetime(2024, 5, 1, 10, tzinfo=UTC), "2024-05-01T10:00:00Z"),
            (datetime(2024, 5, 1, 10), "2024-05-01T10:00:00Z"),
            (datetime(2024, 5, 1, 12, tzinfo=UTC).astimezone(UTC), "2024-05-01T12:00:00Z"),
            (date(2024, 5, 1), "2024-05-01T00:00:00Z"),
            ("2024-05-01T10:00:00Z", "2024-05-01T10:00:00Z"),
            ("2024-05-01T12:00:00+02:00", "2024-05-01T10:00:00Z"),
            (1714557600, "2024-05-01T10:00:00Z"),
            ("not-a-date", None),
            (object(), None),
        ],
    )
    def test_values(self, value, expected):
        assert to_iso8601(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "mode, expected_url",
        [
            ("live", "https://live.dodopayments.com/customers?page_size=1"),
            ("test", "https://test.dodopayments.com/customers?page_size=1"),
        ],
    )
    def test_probe_targets_the_host_for_the_mode(self, mode: str, expected_url: str) -> None:
        # A live key probed against the test host (or vice versa) always 401s, so the mode has to
        # reach the probe URL.
        with scripted_network([ScriptedResponse()]) as network:
            assert validate_credentials("key", mode) == (True, 200)

        assert network.requests_log[0].url == expected_url
        assert network.requests_log[0].headers["authorization"] == "Bearer key"


class TestPagination:
    def test_full_page_then_empty_page_terminates(self) -> None:
        result = _driver().run("payments", [_page(PAGE_SIZE), _page(0)])

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE
        assert result.params("page_number") == ["0", "1"]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run("payments", [_page(2, start=400)], resume_state=DodoPaymentsResumeConfig(page_number=4))

        assert result.raised is None
        assert [row["payment_id"] for row in result.rows] == ["pay_400", "pay_401"]
        assert result.params("page_number") == ["4"]


class TestRequestParams:
    @pytest.mark.parametrize(
        "endpoint, expected_param",
        [
            ("payments", "created_at_gte"),
            ("subscriptions", "created_at_gte"),
            ("balance_ledger_entries", "created_at_gte"),
            # Usage events filter on `start`, not `created_at_gte`.
            ("events", "start"),
        ],
    )
    def test_incremental_sync_sends_the_endpoints_date_filter(self, endpoint: str, expected_param: str) -> None:
        result = _driver().run(
            endpoint,
            [_page(1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, 10, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param(expected_param) == "2024-05-01T10:00:00Z"

    def test_unparseable_watermark_drops_the_filter(self) -> None:
        # Sending a value the API rejects would fail the whole sync; a full walk is the safe fallback.
        result = _driver().run(
            "payments", [_page(1)], should_use_incremental_field=True, db_incremental_field_last_value="garbage"
        )

        assert result.raised is None
        assert result.requests[0].param("created_at_gte") is None

    def test_catalog_endpoint_never_gets_a_date_filter(self) -> None:
        # `/products` exposes no date filter; sending one would be rejected.
        result = _driver().run(
            "products",
            [_response([{"product_id": "prod_1"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert set(result.requests[0].query) == {"page_size", "page_number"}


class TestSourceResponseMetadata:
    def test_framework_incremental_injection_is_not_used(self) -> None:
        # The date filter is baked into the request params, so letting the framework inject its own
        # incremental param too would send a second, differently named filter.
        result = _driver().run(
            "payments",
            [_page(1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert set(result.requests[0].query) == {"page_size", "page_number", "created_at_gte"}


class TestEndpointCatalog:
    def test_every_incremental_endpoint_declares_a_server_side_filter(self):
        # Without a server-side filter an "incremental" sync would still fetch every page.
        for name, config in DODOPAYMENTS_ENDPOINTS.items():
            assert bool(config.incremental_fields) == (config.start_param is not None), name

    def test_incremental_cursor_matches_the_partition_key(self):
        # The cursor and the partition key must both be creation timestamps that never change.
        for name, config in DODOPAYMENTS_ENDPOINTS.items():
            if not config.incremental_fields:
                continue
            assert [f["field"] for f in config.incremental_fields] == [config.partition_key], name
