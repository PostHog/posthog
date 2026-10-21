from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tremendous import (
    TremendousSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.settings import (
    ENDPOINTS,
    TREMENDOUS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.source import TremendousSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.tremendous import (
    TremendousResumeConfig,
    _balance_transaction_row_id,
    _to_iso_datetime,
    base_url_for_environment,
    validate_credentials,
)


def _response(items: list[dict[str, Any]], *, data_key: str = "orders") -> ScriptedResponse:
    return ScriptedResponse(json={data_key: items, "total_count": len(items)})


def _run(
    endpoint: str,
    script: Script,
    resume_state: TremendousResumeConfig | None = None,
    **kwargs: Any,
) -> DriveResult:
    driver = SourceDriver(TremendousSource(), TremendousSourceConfig(api_key="tremendous-key"))
    return driver.run(endpoint, script, resume_state=resume_state, **kwargs)


class TestPagination:
    def test_resumes_from_saved_offset(self) -> None:
        result = _run("orders", [_response([{"id": "X"}])], resume_state=TremendousResumeConfig(offset=1000))

        # The initial (offset=0) page must never be re-fetched on resume.
        assert result.params("offset") == ["1000"]

    @parameterized.expand([("orders",), ("balance_transactions",)])
    def test_incremental_watermark_sent_as_created_at_gte_on_every_page(self, endpoint: str) -> None:
        config = TREMENDOUS_ENDPOINTS[endpoint]
        full_page = [{"created_at": f"2026-01-03T00:00:{i:02d}Z"} for i in range(config.page_size)]

        result = _run(
            endpoint,
            [_response(full_page, data_key=config.data_key), _response([], data_key=config.data_key)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        assert len(result.requests) == 2
        assert result.params("created_at[gte]") == ["2026-01-02T03:04:05+00:00"] * 2

    def test_pins_redirects_off(self) -> None:
        # Redirect-following would replay the Bearer key to whatever host Tremendous redirects to.
        result = _run(
            "orders",
            always(ScriptedResponse(status=302, headers={"Location": "https://attacker.example/steal"})),
        )

        assert result.raised is not None
        assert {request.origin for request in result.requests} == {"https://www.tremendous.com"}

    def test_unexpected_payload_is_retryable(self) -> None:
        # A 200 whose body isn't the expected {data_key: [...]} shape is retried, then re-raised.
        result = _run("orders", always(ScriptedResponse(json={"total_count": 0})))

        assert isinstance(result.raised, RESTClientRetryableError)

    @parameterized.expand(
        [
            ("non_dict_body", [{"id": "A"}]),
            ("missing_data_key", {"total_count": 0}),
            ("data_key_not_a_list", {"orders": {"id": "A"}}),
        ]
    )
    def test_unexpected_payload_shapes_are_retryable(self, _name: str, body: Any) -> None:
        result = _run("orders", always(ScriptedResponse(json=body)))

        assert isinstance(result.raised, RESTClientRetryableError)


class TestHelpers:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05+00:00"),
            ("naive_datetime", datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05+00:00"),
            ("date", date(2026, 1, 2), "2026-01-02T00:00:00+00:00"),
            ("string_passthrough", "2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z"),
            ("none", None, None),
            ("empty_string", "", None),
        ]
    )
    def test_to_iso_datetime(self, _name: str, value: Any, expected: str | None) -> None:
        assert _to_iso_datetime(value) == expected

    @parameterized.expand(
        [
            ("production", "https://www.tremendous.com/api/v2"),
            ("sandbox", "https://testflight.tremendous.com/api/v2"),
            # Unknown values fall back to production rather than building a bad URL.
            ("bogus", "https://www.tremendous.com/api/v2"),
        ]
    )
    def test_base_url_for_environment(self, environment: str, expected: str) -> None:
        assert base_url_for_environment(environment) == expected


def _bt_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "created_at": "2026-01-02T03:04:05Z",
        "amount": 25.0,
        "currency_code": "USD",
        "action": "Order",
        "description": "Order payment",
        "balance": 975.0,
        "order": {"id": "ORDER123", "external_id": None, "payment": {"subtotal": 25.0, "total": 25.0, "fees": 0.0}},
    }
    row.update(overrides)
    return row


class TestBalanceTransactionRowId:
    @parameterized.expand(
        [
            # `balance` may be backfilled late (null -> value); re-keying on it would duplicate
            # every backfilled row on the next incremental fetch.
            ("balance_backfilled", {"balance": None}, {"balance": 975.0}, True),
            # The embedded order payment grows a refund block once an order is canceled.
            (
                "order_refund_added",
                {},
                {
                    "order": {
                        "id": "ORDER123",
                        "payment": {"total": 25.0, "refund": {"total": 25.0, "currency_code": "USD"}},
                    }
                },
                True,
            ),
            # int/float representation drift must not re-key existing rows.
            ("amount_int_vs_float", {"amount": 25}, {"amount": 25.0}, True),
            # Dropping any discriminator from the hash would collapse distinct ledger rows.
            ("different_created_at", {}, {"created_at": "2026-01-02T03:04:06Z"}, False),
            ("different_amount", {}, {"amount": 26.0}, False),
            ("different_currency", {}, {"currency_code": "EUR"}, False),
            ("different_action", {}, {"action": "Refund"}, False),
            ("different_description", {}, {"description": "Something else"}, False),
            ("different_order_id", {}, {"order": {"id": "ORDER999"}}, False),
            ("order_absent", {}, {"order": None}, False),
        ]
    )
    def test_id_tracks_stable_fields_only(
        self, _name: str, left: dict[str, Any], right: dict[str, Any], same: bool
    ) -> None:
        left_id = _balance_transaction_row_id(_bt_row(**left))["id"]
        right_id = _balance_transaction_row_id(_bt_row(**right))["id"]
        assert (left_id == right_id) is same


class TestValidateCredentials:
    def test_pins_redirects_off(self) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            validate_credentials("tremendous-key", "production")
        assert network.session_options
        assert all(options["allow_redirects"] is False for options in network.session_options)


class TestTremendousSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _run(endpoint, []).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Tremendous lists are creation-date DESC; declaring asc would corrupt the incremental watermark.
        assert response.sort_mode == "desc"
        if TREMENDOUS_ENDPOINTS[endpoint].partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["created_at"]
        else:
            assert response.partition_mode is None

    def test_partition_keys_are_stable_creation_timestamps(self) -> None:
        # Partition keys must never be updated_at-style fields, which rewrite partitions every sync.
        assert {c.partition_key for c in TREMENDOUS_ENDPOINTS.values()} == {"created_at", None}
