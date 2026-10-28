import re
from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.braintree.braintree import (
    BRAINTREE_VERSION_2019_01_01,
    BRAINTREE_VERSION_2026_07_14,
    BRAINTREE_VERSION_2026_08_04,
    BRAINTREE_VERSION_2026_08_13,
    BRAINTREE_VERSION_2026_10_06,
    MAX_PAGE_SIZE,
    BraintreeGraphQLError,
    BraintreeResumeConfig,
    _base_url,
    _build_query,
    _format_created_at,
    _normalize_node,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braintree.settings import (
    BRAINTREE_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braintree.source import BraintreeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.braintree import (
    BraintreeSourceConfig,
)

_VERSION = BRAINTREE_VERSION_2026_07_14


def _driver() -> SourceDriver:
    return SourceDriver(
        BraintreeSource(),
        BraintreeSourceConfig(environment="production", public_key="pub", private_key="priv"),
    )


def _search_response(endpoint: str, edges: list[dict[str, Any]], has_next: bool = False) -> ScriptedResponse:
    config = BRAINTREE_ENDPOINTS[endpoint]
    payload: Any = {config.connection_field: {"pageInfo": {"hasNextPage": has_next}, "edges": edges}}
    for wrapper in reversed(config.query_path):
        payload = {wrapper: payload}

    return ScriptedResponse(json={"data": payload})


def _edge(node_id: str) -> dict[str, Any]:
    return {"cursor": f"cur-{node_id}", "node": {"id": node_id, "createdAt": "2024-01-01T00:00:00Z"}}


class TestBaseUrl:
    def test_invalid_environment_raises(self):
        with pytest.raises(ValueError):
            _base_url("evil")


class TestBuildQuery:
    @pytest.mark.parametrize(
        "endpoint, input_type",
        [
            ("transactions", "TransactionSearchInput"),
            ("refunds", "RefundSearchInput"),
            ("disputes", "DisputeSearchInput"),
            ("customers", "CustomerSearchInput"),
            ("recurring_billing_subscriptions", "RecurringBillingSubscriptionSearchInput"),
        ],
    )
    def test_query_uses_correct_input_type(self, endpoint, input_type):
        query = _build_query(BRAINTREE_ENDPOINTS[endpoint])
        # Braintree's search fields declare `input` as non-null; a nullable
        # declaration here fails GraphQL validation (VariableTypeMismatch).
        assert f"$input: {input_type}!" in query
        assert BRAINTREE_ENDPOINTS[endpoint].connection_field in query

    @pytest.mark.parametrize("field", ["price", "balance", "nextBillingPeriodAmount"])
    def test_subscription_amounts_are_selected_as_leaves(self, field):
        # These are Braintree's `Amount` scalar; a subselection fails validation
        # (SubselectionNotAllowed) and rejects the whole query.
        query = _build_query(BRAINTREE_ENDPOINTS["recurring_billing_subscriptions"])
        assert re.search(rf"\b{field}\b", query)
        assert not re.search(rf"\b{field}\s*{{", query)

    def test_query_nests_connection_under_its_wrappers(self):
        # `merchantAccounts` hangs off `viewer.merchant`, not the `search` root.
        query = _build_query(BRAINTREE_ENDPOINTS["merchant_accounts"])
        assert "viewer {" in query
        assert "merchant {" in query
        assert "search" not in query

    def test_query_omits_input_when_the_connection_takes_none(self):
        # `Merchant.merchantAccounts` declares `input` as nullable, so declaring an
        # unused non-null variable would fail validation on every request.
        query = _build_query(BRAINTREE_ENDPOINTS["merchant_accounts"])
        assert "$input" not in query
        assert "input:" not in query


class TestNormalizeNode:
    @pytest.mark.parametrize("node", [{"id": "s1"}, {"id": "s1", "timeline": None}, {"id": "s1", "timeline": {}}])
    def test_leaves_node_untouched_when_the_nested_timestamp_is_missing(self, node):
        # A null timestamp must not seed a `createdAt` column holding None for every row.
        config = BRAINTREE_ENDPOINTS["recurring_billing_subscriptions"]
        assert "createdAt" not in _normalize_node(node, config)


class TestFormatCreatedAt:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_created_at(value) == expected


class TestValidateCredentials:
    def test_valid_on_pong(self) -> None:
        with scripted_network([ScriptedResponse(json={"data": {"ping": "pong"}})]) as network:
            assert validate_credentials("production", "pub", "priv", _VERSION) is True

        assert network.requests_log[0].path == "/graphql"
        assert network.requests_log[0].json() == {"query": "query { ping }", "variables": {}}

    def test_invalid_on_graphql_error(self) -> None:
        with scripted_network([ScriptedResponse(json={"errors": [{"message": "Invalid API key"}]})]) as network:
            assert validate_credentials("production", "pub", "priv", _VERSION) is False

        assert network.requests_log[0].path == "/graphql"


class TestGetRows:
    def test_paginates_via_relay_cursors(self) -> None:
        result = _driver().run(
            "transactions",
            [
                _search_response("transactions", [_edge("t1"), _edge("t2")], has_next=True),
                _search_response("transactions", [_edge("t3")], has_next=False),
            ],
            api_version=_VERSION,
        )

        assert result.raised is None
        assert [item["id"] for item in result.rows] == ["t1", "t2", "t3"]
        assert result.saved_states == [BraintreeResumeConfig(after="cur-t2")]
        assert result.committed_states == [BraintreeResumeConfig(after="cur-t2")]
        second_vars = result.requests[1].json()["variables"]
        assert second_vars["after"] == "cur-t2"

        # Braintree rejects `first` above its cap on the very first page, so assert
        # against the vendor ceiling rather than echoing our own page size back.
        for request in result.requests:
            requested = request.json()["variables"]["first"]
            assert 0 < requested <= MAX_PAGE_SIZE

    @pytest.mark.parametrize("endpoint", ["transactions", "refunds", "customers", "recurring_billing_subscriptions"])
    def test_incremental_search_input_has_gte_filter(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [_search_response(endpoint, [])],
            api_version=_VERSION,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert result.raised is None
        variables = result.requests[0].json()["variables"]
        assert variables["input"] == {"createdAt": {"greaterThanOrEqualTo": "2024-01-02T00:00:00Z"}}

    def test_reads_rows_nested_under_the_connection_wrappers(self) -> None:
        result = _driver().run(
            "merchant_accounts",
            [_search_response("merchant_accounts", [{"cursor": "c1", "node": {"id": "ma1"}}])],
            api_version=_VERSION,
        )

        assert result.raised is None
        assert [item["id"] for item in result.rows] == ["ma1"]
        # A connection taking no search input must not send an `input` variable the
        # query never declares.
        assert "input" not in result.requests[0].json()["variables"]

    def test_yields_subscriptions_with_a_root_level_created_at(self) -> None:
        result = _driver().run(
            "recurring_billing_subscriptions",
            [
                _search_response(
                    "recurring_billing_subscriptions",
                    [{"cursor": "c1", "node": {"id": "s1", "timeline": {"createdAt": "2024-01-02T03:04:05Z"}}}],
                )
            ],
            api_version=_VERSION,
        )

        # The partition key and the incremental cursor both read `createdAt` off the row.
        assert result.raised is None
        assert result.rows[0]["createdAt"] == "2024-01-02T03:04:05Z"

    def test_incremental_omits_filter_when_search_input_lacks_created_at(self) -> None:
        result = _driver().run(
            "disputes",
            [_search_response("disputes", [])],
            api_version=_VERSION,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        # `DisputeSearchInput` declares no createdAt field, so filtering on it fails
        # GraphQL validation and takes the whole sync down.
        assert result.raised is None
        variables = result.requests[0].json()["variables"]
        assert variables["input"] == {}

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "transactions",
            [_search_response("transactions", [])],
            resume_state=BraintreeResumeConfig(after="cur-resume"),
            api_version=_VERSION,
        )

        assert result.raised is None
        variables = result.requests[0].json()["variables"]
        assert variables["after"] == "cur-resume"

    def test_graphql_error_raises(self) -> None:
        result = _driver().run(
            "transactions",
            [ScriptedResponse(json={"errors": [{"message": "validation error"}]})],
            api_version=_VERSION,
        )

        assert isinstance(result.raised, BraintreeGraphQLError)

    @pytest.mark.parametrize(
        "api_version",
        [
            BRAINTREE_VERSION_2019_01_01,
            BRAINTREE_VERSION_2026_07_14,
            BRAINTREE_VERSION_2026_08_04,
            BRAINTREE_VERSION_2026_08_13,
            BRAINTREE_VERSION_2026_10_06,
        ],
    )
    def test_session_uses_basic_auth_and_version_header(self, api_version: str) -> None:
        result = _driver().run("transactions", [_search_response("transactions", [])], api_version=api_version)

        assert result.raised is None
        assert result.requests[0].headers["authorization"] == "Basic cHViOnByaXY="
        assert result.requests[0].headers["braintree-version"] == api_version


class TestBraintreeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = BRAINTREE_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_search_response(endpoint, [])], api_version=_VERSION)
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        # Search ordering is undocumented — watermark commits only at run end.
        assert response.sort_mode == "desc"

        if config.partition_key is None:
            # Partitioning on a column the nodes never carry writes every row to a
            # partition keyed on null.
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
