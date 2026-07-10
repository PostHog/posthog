import functools
from typing import Any, cast

import pytest
from unittest import mock
from unittest.mock import MagicMock, patch

import stripe as stripe_lib
from stripe import ListObject

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    StripeAuthMethodConfig,
    StripeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe import stripe as stripe_module
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
    CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
    CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    RESOURCE_TO_STRIPE_WEBHOOK_EVENT,
    STRIPE_API_VERSION_ACACIA,
    SUBSCRIPTION_RESOURCE_NAME,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source import StripeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe import (
    SUBSCRIPTION_PAGE_LIMIT,
    StripeAuthenticationError,
    StripeNestedResource,
    StripeResource,
    _all_known_webhook_events,
    _coerce_incremental_cursor,
    _is_non_list_stripe_response,
    _is_truncated_stripe_list_response,
    _RateLimitRetryingRequestsClient,
    get_rows,
)

_COMPLETE_LIST_BODY = b'{\n  "object": "list",\n  "data": [],\n  "has_more": false\n}'
# A list page cut off mid-string — what Stripe later fails to decode as "Invalid response body".
_TRUNCATED_LIST_BODY = (
    b'{\n  "object": "list",\n  "data": [\n    {\n      "id": "in_1",\n      "description": "a value that got cut'
)
# Webhook write responses are single objects, not lists — must never trigger the read-only retry.
_TRUNCATED_WEBHOOK_BODY = b'{\n  "object": "webhook_endpoint",\n  "id": "we_1",\n  "url": "https://example.com/cut'
# A truncated single object whose head contains the tokens "object" and "list" without being a
# list response (here `"type": "list.updated"`) — must not be mistaken for a truncated list.
_TRUNCATED_NON_LIST_WITH_LIST_TOKEN = (
    b'{\n  "object": "event",\n  "type": "list.updated",\n  "data": {\n    "id": "evt_1'
)
# A complete 2xx body returned where a list read expected `{"object": "list", ...}` — the SDK
# builds a plain StripeObject and auto_paging_iter crashes on the missing `is_empty` property.
_COMPLETE_NON_LIST_BODY = b'{\n  "object": "customer",\n  "id": "cus_1"\n}'


def _list_object(items):
    obj = MagicMock()
    obj.auto_paging_iter.return_value = iter(items)
    return obj


class _FakeStripeList:
    def __init__(self, objects):
        self._objects = objects

    def auto_paging_iter(self):
        return iter(self._objects)


class TestStripeGetRowsIncrementalCursor:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (1700000000, 1700000000),
            (1700000000.0, 1700000000),
            # The persisted watermark is read back from JSON config as a numeric string.
            ("1700000000", 1700000000),
            (None, None),
            ("not-a-timestamp", None),
            (True, None),
        ],
    )
    def test_coerce_incremental_cursor(self, value, expected):
        assert _coerce_incremental_cursor(value) == expected

    def test_get_rows_handles_string_incremental_watermark(self):
        # Stripe object timestamps are ints, but the stored watermark can come back as a numeric
        # string. The cursor comparison must not crash with `'<=' not supported between instances
        # of 'int' and 'str'`, and must still stop once it reaches an object at/under the watermark.
        objects = [
            {"id": "ch_2", "created": 1700000100},
            {"id": "ch_1", "created": 1700000040},
        ]
        resource = StripeResource(method=lambda params: cast(ListObject[Any], _FakeStripeList(objects)))
        resumable_source_manager = mock.MagicMock()
        resumable_source_manager.can_resume.return_value = False

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe._build_resources",
            return_value={"charge": resource},
        ):
            tables = list(
                get_rows(
                    api_key="sk_test_123",
                    endpoint="charge",
                    account_id=None,
                    db_incremental_field_last_value="1700000050",
                    db_incremental_field_earliest_value=None,
                    logger=mock.MagicMock(),
                    resumable_source_manager=resumable_source_manager,
                    api_version=STRIPE_API_VERSION_ACACIA,
                    should_use_incremental_field=True,
                )
            )

        rows = [row for table in tables for row in table.to_pylist()]
        assert [row["id"] for row in rows] == ["ch_2"]

    def test_backfill_branch_yields_all_earlier_objects_in_bounded_chunks(self):
        # The created[lt] backfill must yield every earlier object AND batch them into bounded chunks:
        # each yielded chunk is what makes the pipeline persist the `earliest` watermark, so a large
        # backfill checkpoints progress mid-attempt instead of restarting the whole scan on a
        # heartbeat timeout. A single giant batch (the previous behaviour) never checkpoints.
        objects = [{"id": f"ch_{i}", "created": 1700000000 - i} for i in range(5)]
        resource = StripeResource(method=lambda params: cast(ListObject[Any], _FakeStripeList(objects)))
        resumable_source_manager = mock.MagicMock()
        resumable_source_manager.can_resume.return_value = False

        with (
            mock.patch.object(stripe_module, "STRIPE_CHUNK_SIZE", 2),
            mock.patch.object(stripe_module, "_build_resources", return_value={"charge": resource}),
        ):
            tables = list(
                get_rows(
                    api_key="sk_test_123",
                    endpoint="charge",
                    account_id=None,
                    db_incremental_field_last_value=None,
                    db_incremental_field_earliest_value=1700000100,
                    logger=mock.MagicMock(),
                    resumable_source_manager=resumable_source_manager,
                    api_version=STRIPE_API_VERSION_ACACIA,
                    should_use_incremental_field=True,
                )
            )

        rows = [row for table in tables for row in table.to_pylist()]
        assert [row["id"] for row in rows] == [f"ch_{i}" for i in range(5)]
        assert len(tables) > 1


class TestStripeSource:
    def setup_method(self):
        self.source = StripeSource()

    @pytest.mark.parametrize(
        "observed_error",
        [
            # 403 raised mid-sync — `str(StripeError)` is "Request <id>: <message>", with no class
            # name, so these are matched on the stable message text rather than "PermissionError".
            "Request req_Zb0EgUuheEd4gf: Permission denied. The provided key 'rk_live_***j4va7j' does not have the required permissions for this endpoint on account 'acct_123'. Enabling \"Prices Read\" ('plan_read') permissions on this key would allow this request to continue.",
            "Request req_abc123: Only Stripe Connect platforms can work with other accounts. If you specified a client_id parameter, make sure it's correct.",
            # 401/403 surfaced as a requests HTTPError keep matching the existing URL-based keys.
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "403 Client Error: Forbidden for url: https://api.stripe.com/v1/prices",
            # IP allowlist rejection — matched on the stable phrase, ignoring the appended IP address.
            "The API key provided does not allow requests from your IP address.",
            "The API key provided does not allow requests from your IP address (1.2.3.4).",
            # account_invalid: key not authorized for the configured account, or revoked app access.
            # Raised mid-sync as stripe.PermissionError, matched on the stable phrase (key/account redacted).
            "The provided key 'sk_test_***qPsl' does not have access to account 'stripe_s***less' (or that account does not exist). Application access may have been revoked.",
        ],
    )
    def test_non_retryable_errors_match_permission_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            # Transient/infra errors must stay retryable.
            "HTTPSConnectionPool(host='api.stripe.com', port=443): Read timed out.",
            "500 Server Error: Internal Server Error for url: https://api.stripe.com/v1/charges",
            "Connection reset by peer",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "config,expected_message",
        [
            # OAuth selected but the integration was never linked (or was deleted): `_get_api_key`
            # raises ValueError("Missing Stripe integration ID"), an internal string the user can't
            # act on. validate_credentials must translate it to the reconnect guidance.
            (
                StripeSourceConfig(auth_method=StripeAuthMethodConfig(selection="oauth", stripe_integration_id=None)),
                "Stripe integration ID is not configured. Please reconnect your Stripe account.",
            ),
            (
                StripeSourceConfig(auth_method=StripeAuthMethodConfig(selection="api_key", stripe_secret_key=None)),
                "Stripe API key is not configured. Please update the source configuration.",
            ),
        ],
    )
    def test_validate_credentials_missing_config_returns_friendly_message(self, config, expected_message):
        ok, message = self.source.validate_credentials(config, team_id=1)

        assert ok is False
        assert message == expected_message

    def test_validate_credentials_does_not_echo_rejected_key(self):
        # Stripe's 401 body echoes the submitted key verbatim; here the user pasted a password into
        # the key field. The validation message must not leak it into the toast or analytics event.
        pasted_secret = "Ammgad1979@"
        config = StripeSourceConfig(
            auth_method=StripeAuthMethodConfig(selection="api_key", stripe_secret_key=pasted_secret)
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.validate_stripe_credentials",
            side_effect=StripeAuthenticationError(f"Invalid API Key provided: {pasted_secret}"),
        ):
            ok, message = self.source.validate_credentials(config, team_id=1)

        assert ok is False
        assert message is not None
        assert pasted_secret not in message
        assert message.startswith("Stripe rejected the API key.")

    @pytest.mark.parametrize(
        "body,expected",
        [
            (_TRUNCATED_LIST_BODY, True),
            (_TRUNCATED_LIST_BODY.decode(), True),  # str bodies behave the same as bytes
            (_COMPLETE_LIST_BODY, False),  # complete responses always close with "}"
            (_TRUNCATED_WEBHOOK_BODY, False),  # truncated, but a single object — not a list read
            # truncated non-list whose head still contains the "object" and "list" tokens
            (_TRUNCATED_NON_LIST_WITH_LIST_TOKEN, False),
            (b'{\n  "object": "webhook_endpoint",\n  "id": "we_1"\n}', False),
            (b"", False),
            (None, False),
        ],
    )
    def test_is_truncated_stripe_list_response(self, body, expected):
        assert _is_truncated_stripe_list_response(body) is expected

    @pytest.mark.parametrize(
        "response,num_retries,expected",
        [
            # 2xx with a truncated list body is retried while budget remains...
            ((_TRUNCATED_LIST_BODY, 200, {}), 0, True),
            # ...but not once the network-retry budget is exhausted.
            ((_TRUNCATED_LIST_BODY, 200, {}), 2, False),
            # A complete 2xx list body is not retried.
            ((_COMPLETE_LIST_BODY, 200, {}), 0, False),
            # A truncated single-object (webhook write) body is not retried.
            ((_TRUNCATED_WEBHOOK_BODY, 200, {}), 0, False),
            # A truncated non-list body that merely mentions "list" is not retried.
            ((_TRUNCATED_NON_LIST_WITH_LIST_TOKEN, 200, {}), 0, False),
            # 429s stay retryable (regression guard for the existing rate-limit handling).
            ((b'{\n  "error": {}\n}', 429, {}), 0, True),
        ],
    )
    def test_rate_limit_client_should_retry(self, response, num_retries, expected):
        client = _RateLimitRetryingRequestsClient()
        assert client._should_retry(response, None, num_retries=num_retries, max_network_retries=2) is expected

    @pytest.mark.parametrize(
        "body,expected",
        [
            (_COMPLETE_NON_LIST_BODY, True),
            (_COMPLETE_NON_LIST_BODY.decode(), True),  # str bodies behave the same as bytes
            (b"{}", True),  # a bare object with no marker is still not a list
            (_COMPLETE_LIST_BODY, False),  # a genuine list carries "object": "list"
            (_TRUNCATED_LIST_BODY, False),  # unclosed — handled by the truncation check instead
            (_TRUNCATED_WEBHOOK_BODY, False),  # unclosed single object, not a complete body
            (b"", False),
            (None, False),
        ],
    )
    def test_is_non_list_stripe_response(self, body, expected):
        assert _is_non_list_stripe_response(body) is expected

    @pytest.mark.parametrize(
        "method,num_retries,expected",
        [
            # A GET (list read) that returns a complete non-list body is retried while budget remains.
            ("get", 0, True),
            # ...but not once the network-retry budget is exhausted.
            ("get", 2, False),
            # A write's single-object response must never be retried on shape alone.
            ("post", 0, False),
        ],
    )
    def test_rate_limit_client_retries_non_list_read_only_for_gets(self, method, num_retries, expected):
        client = _RateLimitRetryingRequestsClient()
        client._last_request_method = method
        response: tuple[bytes, int, dict[str, str]] = (_COMPLETE_NON_LIST_BODY, 200, {})
        assert client._should_retry(response, None, num_retries=num_retries, max_network_retries=2) is expected

    def test_request_records_method_for_scoping(self):
        client = _RateLimitRetryingRequestsClient()
        with patch.object(stripe_lib.RequestsClient, "request", return_value=(b"{}", 200, {})):
            client.request("GET", "https://api.stripe.com/v1/customers", {})
        assert client._last_request_method == "get"


def _run_nested_get_rows(nested_method, parent_objects=None, parent_has_nested=None):
    if parent_objects is None:
        parent_objects = [{"id": "cus_ok1"}, {"id": "cus_gone"}, {"id": "cus_ok2"}]
    parent = StripeResource(method=lambda **kwargs: _list_object(parent_objects))
    resource = StripeNestedResource(
        method=nested_method,
        nested_parent_param="customer",
        parent_id="id",
        parent=parent,
        parent_name=CUSTOMER_RESOURCE_NAME,
        parent_has_nested=parent_has_nested,
    )

    resumable_source_manager = MagicMock()
    resumable_source_manager.can_resume.return_value = False

    with (
        patch.object(stripe_module, "StripeClient"),
        patch.object(
            stripe_module,
            "_build_resources",
            return_value={CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME: resource},
        ),
    ):
        rows: list[dict] = []
        for table in get_rows(
            api_key="sk_test_123",
            endpoint=CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
            account_id=None,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            logger=MagicMock(),
            resumable_source_manager=resumable_source_manager,
            api_version=STRIPE_API_VERSION_ACACIA,
        ):
            rows.extend(table.to_pylist())
    return rows


class TestStripeNestedResourceGetRows:
    def test_skips_parent_deleted_mid_sync(self):
        def nested_method(customer=None, params=None):
            if customer == "cus_gone":
                raise stripe_lib.InvalidRequestError(
                    f"No such customer: '{customer}'", "customer", code="resource_missing", http_status=404
                )
            return _list_object([{"id": f"cbt_{customer}", "amount": 100}])

        rows = _run_nested_get_rows(nested_method)

        assert {row["customer"] for row in rows} == {"cus_ok1", "cus_ok2"}

    def test_other_invalid_request_errors_still_raise(self):
        def nested_method(customer=None, params=None):
            raise stripe_lib.InvalidRequestError("Invalid string", "expand", code="parameter_unknown", http_status=400)

        with pytest.raises(stripe_lib.InvalidRequestError):
            _run_nested_get_rows(nested_method)

    def test_parent_has_nested_skips_filtered_parents_without_calling(self):
        called_for: list[str] = []

        def nested_method(customer=None, params=None):
            called_for.append(customer)
            return _list_object([{"id": f"cbt_{customer}", "amount": 100}])

        # Only customers with a non-zero balance should trigger the nested call.
        rows = _run_nested_get_rows(
            nested_method,
            parent_objects=[
                {"id": "cus_zero", "balance": 0},
                {"id": "cus_credit", "balance": -500},
                {"id": "cus_owed", "balance": 1500},
            ],
            parent_has_nested=stripe_module._customer_might_have_balance_transactions,
        )

        # cus_zero is skipped entirely — no API call, no rows.
        assert called_for == ["cus_credit", "cus_owed"]
        assert {row["customer"] for row in rows} == {"cus_credit", "cus_owed"}


class TestSubscriptionPageSize:
    def test_build_resources_caps_subscription_page_size(self):
        # Subscriptions expand discounts at two levels, so a full DEFAULT_LIMIT page can grow past the
        # size that transfers intact and arrives truncated mid-stream. The endpoint must request a
        # smaller page than the default to keep each response transferable.
        resources = stripe_module._build_resources(MagicMock(), logger=None)

        subscription = resources[SUBSCRIPTION_RESOURCE_NAME]
        assert subscription.params["limit"] == SUBSCRIPTION_PAGE_LIMIT
        assert SUBSCRIPTION_PAGE_LIMIT < stripe_module.DEFAULT_LIMIT

    def test_get_rows_sends_resource_limit_over_default(self):
        # A resource's own `limit` must win over DEFAULT_LIMIT in the merged params — otherwise the
        # reduced subscription page size would be clobbered back up to 100.
        captured: dict = {}

        def capturing_list(params):
            captured.update(params)
            return _FakeStripeList([])

        resource = StripeResource(method=capturing_list, params={"limit": SUBSCRIPTION_PAGE_LIMIT})
        resumable_source_manager = MagicMock()
        resumable_source_manager.can_resume.return_value = False

        with patch.object(stripe_module, "_build_resources", return_value={SUBSCRIPTION_RESOURCE_NAME: resource}):
            list(
                get_rows(
                    api_key="sk_test_123",
                    endpoint=SUBSCRIPTION_RESOURCE_NAME,
                    account_id=None,
                    db_incremental_field_last_value=None,
                    db_incremental_field_earliest_value=None,
                    logger=MagicMock(),
                    resumable_source_manager=resumable_source_manager,
                    api_version=STRIPE_API_VERSION_ACACIA,
                )
            )

        assert captured["limit"] == SUBSCRIPTION_PAGE_LIMIT


class TestStripeBatcherDrainsSplitChunks:
    def test_flat_resource_drains_all_split_chunks_per_batch(self):
        # A single batch() can split a flushed buffer into several ready chunks (large rows over the
        # per-table byte cap). get_rows must drain every chunk before batching the next object,
        # otherwise the following batch() raises "Batcher already has a table ready to yield."
        objects = [{"id": f"ch_{i}", "description": "x" * 10} for i in range(6)]
        resource = StripeResource(method=lambda params: cast(ListObject[Any], _FakeStripeList(objects)))

        resumable_source_manager = MagicMock()
        resumable_source_manager.can_resume.return_value = False

        # Tiny caps force every 2-row buffer flush to split into single-row chunks.
        splitting_batcher = functools.partial(stripe_module.Batcher, max_table_bytes=1, max_column_offset_bytes=1)

        with (
            patch.object(stripe_module, "StripeClient"),
            patch.object(stripe_module, "STRIPE_CHUNK_SIZE", 2),
            patch.object(stripe_module, "Batcher", splitting_batcher),
            patch.object(stripe_module, "_build_resources", return_value={"charge": resource}),
        ):
            rows: list[dict] = []
            for table in get_rows(
                api_key="sk_test_123",
                endpoint="charge",
                account_id=None,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                logger=MagicMock(),
                resumable_source_manager=resumable_source_manager,
                api_version=STRIPE_API_VERSION_ACACIA,
            ):
                rows.extend(table.to_pylist())

        assert [row["id"] for row in rows] == [f"ch_{i}" for i in range(6)]

    def test_nested_resource_drains_all_split_chunks_per_batch(self):
        nested_objects = [{"id": f"cbt_{i}", "amount": 100, "note": "y" * 10} for i in range(6)]

        def nested_method(customer=None, params=None):
            return _list_object(nested_objects)

        splitting_batcher = functools.partial(stripe_module.Batcher, max_table_bytes=1, max_column_offset_bytes=1)

        with (
            patch.object(stripe_module, "STRIPE_CHUNK_SIZE", 2),
            patch.object(stripe_module, "Batcher", splitting_batcher),
        ):
            rows = _run_nested_get_rows(nested_method, parent_objects=[{"id": "cus_1"}])

        assert [row["id"] for row in rows] == [f"cbt_{i}" for i in range(6)]

    def test_final_incomplete_chunk_drain_splits(self):
        # The final drain takes a different path: get_table() flushes the leftover buffer and can
        # itself produce multiple chunks. A large chunk_size keeps every row in the buffer until the
        # end, so all rows go through that final drain — which must drain every split chunk.
        objects = [{"id": f"ch_{i}", "description": "z" * 10} for i in range(4)]
        resource = StripeResource(method=lambda params: cast(ListObject[Any], _FakeStripeList(objects)))

        resumable_source_manager = MagicMock()
        resumable_source_manager.can_resume.return_value = False

        splitting_batcher = functools.partial(stripe_module.Batcher, max_table_bytes=1, max_column_offset_bytes=1)

        with (
            patch.object(stripe_module, "StripeClient"),
            patch.object(stripe_module, "STRIPE_CHUNK_SIZE", 100),
            patch.object(stripe_module, "Batcher", splitting_batcher),
            patch.object(stripe_module, "_build_resources", return_value={"charge": resource}),
        ):
            rows: list[dict] = []
            for table in get_rows(
                api_key="sk_test_123",
                endpoint="charge",
                account_id=None,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                logger=MagicMock(),
                resumable_source_manager=resumable_source_manager,
                api_version=STRIPE_API_VERSION_ACACIA,
            ):
                rows.extend(table.to_pylist())

        assert [row["id"] for row in rows] == [f"ch_{i}" for i in range(4)]


class TestCustomerMightHaveBalanceTransactions:
    @pytest.mark.parametrize(
        "customer,expected",
        [
            ({"balance": 0}, False),
            ({"balance": -500}, True),
            ({"balance": 1500}, True),
            # Missing balance is an unexpected payload shape — fetch rather than silently drop data.
            ({}, True),
            ({"balance": None}, True),
        ],
    )
    def test_predicate(self, customer, expected):
        assert stripe_module._customer_might_have_balance_transactions(customer) is expected


class TestWebhookEventMapping:
    def test_customer_balance_transaction_has_no_webhook_event(self):
        # Customer balance transactions have no Stripe webhook event, so the resource must not be in
        # the event map — otherwise we'd subscribe the source webhook to unrelated events.
        assert CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME not in RESOURCE_TO_STRIPE_WEBHOOK_EVENT

    def test_no_billing_events_subscribed(self):
        # The removed "billing" mapping was the only thing pulling in billing.* events (credit
        # grants, meters, alerts) — none of which can populate any table we sync.
        assert not any(e.startswith("billing.") or e.startswith("billing_") for e in _all_known_webhook_events())

    def test_payment_method_events_still_subscribed(self):
        # CustomerPaymentMethod keeps its mapping, so payment_method.* events stay subscribed.
        assert RESOURCE_TO_STRIPE_WEBHOOK_EVENT[CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME] == "payment_method"
        assert any(e.startswith("payment_method.") for e in _all_known_webhook_events())


class TestSchemaWebhookCapability:
    def setup_method(self):
        self.source = StripeSource()
        config = StripeSourceConfig(
            auth_method=StripeAuthMethodConfig(selection="api_key", stripe_secret_key="sk_test_123")
        )
        self.by_name = {s.name: s for s in self.source.get_schemas(config, team_id=1)}

    def test_webhook_capability_matches_event_map(self):
        # supports_webhooks must track the webhook-event map exactly (plus webhook-only tables),
        # so the capability and the actual event subscription never drift apart.
        for name, schema in self.by_name.items():
            expected = name in RESOURCE_TO_STRIPE_WEBHOOK_EVENT or schema.webhook_only
            assert schema.supports_webhooks is expected, name
