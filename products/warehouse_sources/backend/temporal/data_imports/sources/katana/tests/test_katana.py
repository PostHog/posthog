from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.katana import KatanaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.katana.katana import (
    PAGE_SIZE,
    KatanaResumeConfig,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.katana.source import KatanaSource

_SECRET_KEY = "katana-secret-key-abcdef123456"


def _driver(api_key: str = "k") -> SourceDriver:
    return SourceDriver(KatanaSource(), KatanaSourceConfig(api_key=api_key))


def _page(items: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items})


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "cursor-value", "cursor-value"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestPagination:
    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run("customers", [_page([{"id": 1}])], resume_state=KatanaResumeConfig(page=4))

        assert result.raised is None
        assert result.rows == [{"id": 1}]
        # The first (and only) request must start at the resumed page, not page 1.
        assert result.params("page") == ["4"]


class TestIncrementalFilter:
    def test_filter_sent_on_every_page(self) -> None:
        full_page = [{"id": i} for i in range(PAGE_SIZE)]
        result = _driver().run(
            "customers",
            [_page(full_page), _page([])],
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="updated_at",
        )

        assert result.raised is None
        assert len(result.requests) == 2
        assert result.params("updated_at_min") == ["2026-01-01T00:00:00.000Z"] * 2

    def test_first_sync_has_no_filter(self) -> None:
        result = _driver().run("customers", [_page([{"id": 1}])], incremental_field="updated_at")

        assert result.raised is None
        assert result.params("updated_at_min") == [None]

    def test_full_refresh_endpoint_never_filters(self) -> None:
        result = _driver().run(
            "inventory",
            [_page([{"variant_id": 1, "location_id": 2}])],
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="updated_at",
        )

        assert result.raised is None
        assert result.queries == [{"page": ("1",), "limit": (str(PAGE_SIZE),)}]


class TestErrorHandling:
    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    def test_4xx_raises_matchable_http_error_without_leaking_key(self, _name: str, status: int, reason: str) -> None:
        # A redirect echoes the key into the final URL. The error must keep its stable status prefix.
        result = _driver(_SECRET_KEY).run(
            "customers",
            [
                ScriptedResponse(
                    status=302,
                    headers={"Location": f"https://api.katanamrp.com/v1/customers?token={_SECRET_KEY}"},
                ),
                ScriptedResponse(status=status),
            ],
        )

        assert isinstance(result.raised, HTTPError)
        message = str(result.raised)
        assert _SECRET_KEY not in message
        assert message.startswith(f"{status} Client Error: {reason} for url: https://api.katanamrp.com/v1/customers")

    @parameterized.expand([("missing_data_key", {"items": []}), ("not_a_dict", [1, 2, 3])])
    def test_malformed_2xx_envelope_is_retried(self, _name: str, body: Any) -> None:
        # A 200 body without a list `data` key must NOT silently end the sync as an empty page — it's
        # reissued (retryable), then the valid page is read.
        result = _driver().run("customers", [ScriptedResponse(json=body), _page([{"id": 7}])])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [7]
        assert len(result.requests) == 2

    @parameterized.expand([("server_error", 503), ("rate_limited", 429)])
    def test_transient_status_is_retried(self, _name: str, status: int) -> None:
        headers = {"Retry-After": "1"} if status == 429 else {}
        result = _driver().run("customers", [ScriptedResponse(status=status, headers=headers), _page([{"id": 5}])])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [5]
        assert len(result.requests) == 2


class TestKatanaSourceResponse:
    @parameterized.expand(
        [
            ("customers", ["id"], "created_at"),
            ("inventory", ["variant_id", "location_id"], None),
            ("price_lists", ["id"], None),
            ("inventory_movements", ["id"], "created_at"),
            ("sales_order_rows", ["id"], "created_at"),
            ("manufacturing_order_productions", ["id"], "created_at"),
            ("bom_rows", ["id"], "created_at"),
            ("sales_order_fulfillments", ["id"], "created_at"),
            ("manufacturing_order_operation_rows", ["id"], "created_at"),
            ("sales_return_rows", ["id"], "created_at"),
        ]
    )
    def test_source_response_shape(self, endpoint: str, expected_pk: list[str], partition_key: str | None) -> None:
        result = _driver().run(endpoint, [_page([])])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode == "desc"
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand([("unauthorized", 401)])
    def test_invalid_key(self, _name: str, status: int) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("bad-key") is False

        assert [request.path for request in network.requests_log] == ["/v1/user_info"]
