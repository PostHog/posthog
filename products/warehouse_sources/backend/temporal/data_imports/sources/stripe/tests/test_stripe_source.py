import functools
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from unittest import mock
from unittest.mock import MagicMock, patch

from django.conf import settings

import orjson
import stripe as stripe_lib
import pyarrow as pa
import deltalake
from parameterized import parameterized
from stripe import ListObject
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.fanout_telemetry import (
    FANOUT_PARENT_ROWS_CONSUMED,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent import (
    ParentTableRef,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.stripe import (
    StripeAuthMethodConfig,
    StripeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe import stripe as stripe_module
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
    APPLICATION_FEE_RESOURCE_NAME,
    BILLING_CREDIT_BALANCE_SUMMARY_RESOURCE_NAME,
    BILLING_CREDIT_BALANCE_TRANSACTION_RESOURCE_NAME,
    BILLING_CREDIT_GRANT_RESOURCE_NAME,
    BILLING_METER_EVENT_SUMMARY_RESOURCE_NAME,
    BILLING_METER_RESOURCE_NAME,
    CHARGE_RESOURCE_NAME,
    CHECKOUT_SESSION_RESOURCE_NAME,
    CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
    CUSTOMER_PAYMENT_METHOD_HISTORY_RESOURCE_NAME,
    CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    DISCOUNT_RESOURCE_NAME,
    EARLY_FRAUD_WARNING_RESOURCE_NAME,
    ENTITLEMENTS_ACTIVE_ENTITLEMENT_RESOURCE_NAME,
    ENTITLEMENTS_FEATURE_RESOURCE_NAME,
    EVENT_RESOURCE_NAME,
    HISTORY_CAPTURED_AT_COLUMN,
    HISTORY_EVENT_ID_COLUMN,
    HISTORY_EVENT_TYPE_COLUMN,
    HISTORY_PREVIOUS_ATTRIBUTES_COLUMN,
    HISTORY_SNAPSHOT_EVENT_TYPE,
    INVOICE_PAYMENT_RESOURCE_NAME,
    PAYMENT_INTENT_RESOURCE_NAME,
    PAYMENT_LINK_RESOURCE_NAME,
    PAYMENT_METHOD_HISTORY_MAPPING_KEY,
    PLAN_RESOURCE_NAME,
    PROMOTION_CODE_RESOURCE_NAME,
    QUOTE_RESOURCE_NAME,
    RESOURCE_TO_STRIPE_OBJECT_TYPE,
    RESOURCE_TO_STRIPE_WEBHOOK_EVENT,
    REVIEW_RESOURCE_NAME,
    SETUP_ATTEMPT_RESOURCE_NAME,
    SETUP_INTENT_RESOURCE_NAME,
    SHIPPING_RATE_RESOURCE_NAME,
    STRIPE_API_VERSION_ACACIA,
    SUBSCRIPTION_ITEM_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
    SUBSCRIPTION_SCHEDULE_RESOURCE_NAME,
    TAX_ID_RESOURCE_NAME,
    TAX_RATE_RESOURCE_NAME,
    TOPUP_RESOURCE_NAME,
    TRANSFER_RESOURCE_NAME,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.custom import InvoiceListWithAllLines
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.settings import (
    ENDPOINTS,
    NON_PARTITIONED_ENDPOINTS,
    WEBHOOK_ONLY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source import PERMISSIONS, StripeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe import (
    DEFAULT_LIMIT,
    SUBSCRIPTION_PAGE_LIMIT,
    StripeAuthenticationError,
    StripeNestedResource,
    StripeResource,
    StripeTransientError,
    _all_known_webhook_events,
    _coerce_incremental_cursor,
    _is_non_list_stripe_response,
    _is_truncated_stripe_list_response,
    _RateLimitRetryingRequestsClient,
    _scrub_client_secrets,
    _webhook_history_table_transformer,
    check_endpoint_permissions,
    create_webhook,
    get_rows,
    validate_credentials as validate_stripe_credentials,
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
            # A publishable key was used where a secret/restricted key is required — matched on the
            # stable message text, ignoring the request id prefix.
            "Request req_abc123: This API call cannot be made with a publishable API key. Please use a secret API key. You can find a list of your API keys at https://dashboard.stripe.com/account/apikeys.",
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
            # Rate limits are transient (Retry-After-bounded) — must never disable the source.
            "Request req_abc123: Request rate limit exceeded. You can learn more about rate limits here https://stripe.com/docs/rate-limits.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "observed_error",
        [
            # A RateLimitError that survives _RateLimitRetryingRequestsClient's in-process backoff
            # still gets retried by Temporal at the activity level; it must be classified as
            # retryable so it's logged as a warning rather than tracked as an exception.
            "Request req_abc123: Request rate limit exceeded. You can learn more about rate limits here "
            "https://stripe.com/docs/rate-limits.",
            # A generic backend APIError that survives the SDK's own in-process 5xx retries, one of at
            # least two known server-generated phrasings for the same "our fault, try again" condition.
            "Request req_abc123: Error while communicating with one of our backends.  Sorry about "
            "that!  We have been notified of the problem.  If you have any questions, we can help "
            "at https://support.stripe.com/.",
            "Request req_abc123: Sorry, something went wrong. We've already been notified of the "
            "problem, but if you need any help, you can reach us at https://support.stripe.com/contact.",
            # Stripe's generic message for a 5xx it can't attribute to a specific cause, arriving
            # without the "notified of the problem" boilerplate. The SDK's own retry loop already
            # exhausted `max_network_retries` before this reaches us, so it's the same self-recovering
            # shape as an exhausted rate limit.
            "Request req_hOaEpFmCP1VADa: An unknown error occurred",
        ],
    )
    def test_retryable_errors_match_transient_stripe_errors(self, observed_error):
        # Matched via the same case-insensitive helper the production path uses
        # (`_handle_import_error`), not a case-sensitive substring check.
        retryable_errors = self.source.get_retryable_errors()
        assert error_message_matches(observed_error, retryable_errors)

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

    def test_validate_credentials_transient_error_returns_retry_message(self):
        # A Stripe-side 5xx during the probe is transient and unrelated to the key. The user must
        # get a retry hint, not Stripe's internal text reported as a permanent validation failure.
        config = StripeSourceConfig(
            auth_method=StripeAuthMethodConfig(selection="api_key", stripe_secret_key="rk_live_x")
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.validate_stripe_credentials",
            side_effect=StripeTransientError("Error while communicating with one of our backends. Sorry about that!"),
        ):
            ok, message = self.source.validate_credentials(config, team_id=1)

        assert ok is False
        assert message is not None
        assert "try again" in message.lower()
        assert "one of our backends" not in message
        assert "validation failed" not in message.lower()

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


def _recording_nested_method(missing=()):
    """A nested list method that records the parents it was called for.

    A real function rather than a mock: the sweep routes the parent id by inspecting the
    method's signature, so a signature-less mock would receive it inside `params` instead and
    the test would not exercise the path production takes.
    """
    probed: list[str] = []

    def _nested(customer, params):
        probed.append(customer)
        if customer in missing:
            raise stripe_lib.InvalidRequestError("No such customer", param="customer", code="resource_missing")
        return _list_object([{"id": f"cbt_{customer}"}])

    return _nested, probed


def _write_customer_parent_table(tmp_path, customers) -> str:
    """The parent schema's synced Delta table, as the warehouse path would find it."""
    uri = str(tmp_path / "stripe_customer")
    deltalake.write_deltalake(
        uri,
        pa.table(
            {
                "id": [customer["id"] for customer in customers],
                "balance": [customer.get("balance") for customer in customers],
            }
        ),
    )
    return uri


def _run_nested_get_rows(
    nested_method,
    parent_objects=None,
    parent_has_nested=None,
    resumable_source_manager=None,
    warehouse_parent=None,
    parent_method=None,
    can_resume=False,
    logger: FilteringBoundLogger | None = None,
):
    if parent_objects is None:
        parent_objects = [{"id": "cus_ok1"}, {"id": "cus_gone"}, {"id": "cus_ok2"}]
    parent = StripeResource(method=parent_method or (lambda **kwargs: _list_object(parent_objects)))
    resource = StripeNestedResource(
        method=nested_method,
        nested_parent_param="customer",
        parent_id="id",
        parent=parent,
        parent_name=CUSTOMER_RESOURCE_NAME,
        parent_has_nested=parent_has_nested,
    )

    if resumable_source_manager is None:
        resumable_source_manager = MagicMock()
    resumable_source_manager.can_resume.return_value = can_resume

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
            logger=logger or MagicMock(),
            resumable_source_manager=resumable_source_manager,
            api_version=STRIPE_API_VERSION_ACACIA,
            warehouse_parent=warehouse_parent,
        ):
            rows.extend(table.to_pylist())
    return rows


class TestValidateCredentialsTransientClassification:
    @pytest.mark.parametrize(
        "error",
        [
            stripe_lib.APIError("Error while communicating with one of our backends. Sorry about that!"),
            stripe_lib.APIConnectionError("Unexpected error communicating with Stripe."),
            stripe_lib.RateLimitError("Too many requests."),
        ],
    )
    def test_probe_backend_failure_raises_transient_not_validation(self, error):
        # These are Stripe-unavailable failures, not credential problems: the probe must raise
        # StripeTransientError so the caller offers a retry rather than a validation failure.
        def boom(params=None):
            raise error

        resource = StripeResource(method=boom)
        with patch.object(stripe_module, "_build_resources", return_value={CUSTOMER_RESOURCE_NAME: resource}):
            with pytest.raises(StripeTransientError):
                validate_stripe_credentials("rk_live_x", endpoints=None)

    def test_check_endpoint_permissions_records_transient_without_raising(self):
        # The schema-selection permissions map must stay whole during a Stripe outage: a transient
        # error is recorded as the endpoint's reason, not raised out of check_endpoint_permissions.
        def boom(params=None):
            raise stripe_lib.APIError("Error while communicating with one of our backends. Sorry about that!")

        resource = StripeResource(method=boom)
        with patch.object(stripe_module, "_build_resources", return_value={CUSTOMER_RESOURCE_NAME: resource}):
            results = check_endpoint_permissions("rk_live_x", [CUSTOMER_RESOURCE_NAME])

        assert results[CUSTOMER_RESOURCE_NAME] is not None


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

    def test_sparse_sweep_checkpoints_by_parent_count(self):
        # A nested resource where no parent has data (CustomerPaymentMethod over customers with no
        # stored payment method) never fills a chunk, so the row-driven checkpoint never fires and
        # a killed run restarted the whole customer walk. Position must be recorded by parents
        # walked, regardless of how few rows come back.
        def nested_method(customer=None, params=None):
            return _list_object([])

        manager = MagicMock()
        logger = MagicMock()
        with patch.object(stripe_module, "NESTED_SWEEP_CHECKPOINT_PARENTS", 3):
            rows = _run_nested_get_rows(
                nested_method,
                parent_objects=[{"id": f"cus_{i}"} for i in range(8)],
                resumable_source_manager=manager,
                logger=logger,
            )

        assert rows == []
        # Checkpointed after the 3rd and 6th parent; the 7th and 8th are still in flight.
        assert [call.args[0].starting_after for call in manager.save_state.call_args_list] == ["cus_2", "cus_5"]
        # The pipeline kills this loop mid-sweep on a worker shutdown, so every checkpoint carries
        # the running fan-out size instead of leaving the attempt's only line until after the loop.
        assert [call.kwargs["rows_total"] for call in logger.info.call_args_list] == [3, 6, 8]

    def test_query_param_service_receives_parent_in_params(self):
        # Flat Stripe services with a required filter (e.g. entitlements.active_entitlements.list)
        # expose the parent only inside `params`, not as a method keyword — passing it as a kwarg
        # raised TypeError: unexpected keyword argument.
        seen_customers: list[str] = []

        def nested_method(params=None):
            seen_customers.append(params["customer"])
            return _list_object([{"id": f"ent_{params['customer']}"}])

        rows = _run_nested_get_rows(nested_method, parent_objects=[{"id": "cus_a"}, {"id": "cus_b"}])

        assert seen_customers == ["cus_a", "cus_b"]
        assert {row["customer"] for row in rows} == {"cus_a", "cus_b"}


class TestInvoiceListWithAllLines:
    def test_skips_lines_for_invoice_deleted_mid_sync(self):
        invoices = [
            SimpleNamespace(id="in_gone", lines=SimpleNamespace(has_more=True, data=[], url="orig")),
            SimpleNamespace(id="in_ok", lines=SimpleNamespace(has_more=True, data=[], url="orig")),
        ]

        def line_items_list(invoice=None, params=None):
            if invoice == "in_gone":
                raise stripe_lib.InvalidRequestError(
                    f"No such invoice: '{invoice}'", "invoice", code="resource_missing", http_status=404
                )
            return _list_object([{"id": "il_1"}])

        client = MagicMock()
        client.invoices.list.return_value = _list_object(invoices)
        client.invoices.line_items.list.side_effect = line_items_list

        result = list(InvoiceListWithAllLines(client, params={}, logger=MagicMock()).auto_paging_iter())

        assert [inv.id for inv in result] == ["in_gone", "in_ok"]
        # The deleted invoice keeps its original (incomplete) lines rather than crashing the sync.
        assert result[0].lines.has_more is True
        # The still-existing invoice gets its lines fully expanded.
        assert result[1].lines.has_more is False
        assert result[1].lines.data == [{"id": "il_1"}]

    def test_other_invalid_request_errors_still_raise(self):
        invoices = [SimpleNamespace(id="in_1", lines=SimpleNamespace(has_more=True, data=[], url="orig"))]

        def line_items_list(invoice=None, params=None):
            raise stripe_lib.InvalidRequestError("Invalid string", "expand", code="parameter_unknown", http_status=400)

        client = MagicMock()
        client.invoices.list.return_value = _list_object(invoices)
        client.invoices.line_items.list.side_effect = line_items_list

        with pytest.raises(stripe_lib.InvalidRequestError):
            list(InvoiceListWithAllLines(client, params={}, logger=MagicMock()).auto_paging_iter())


class TestScrubClientSecrets:
    @parameterized.expand(
        [
            # PaymentIntent / SetupIntent expose client_secret at the top level.
            (
                {"id": "pi_1", "client_secret": "pi_1_secret_abc", "amount": 500},
                {"id": "pi_1", "amount": 500},
            ),
            # A Checkout Session nests the flow's client_secret alongside other fields.
            (
                {"id": "cs_1", "client_secret": "cs_1_secret", "url": "https://checkout"},
                {"id": "cs_1", "url": "https://checkout"},
            ),
            # Event objects embed a full copy of the resource under data.object AND the pre-change
            # values under data.previous_attributes — both must be scrubbed.
            (
                {
                    "id": "evt_1",
                    "type": "payment_intent.succeeded",
                    "data": {
                        "object": {"id": "pi_2", "client_secret": "pi_2_secret", "status": "succeeded"},
                        "previous_attributes": {"client_secret": "pi_2_secret", "status": "processing"},
                    },
                },
                {
                    "id": "evt_1",
                    "type": "payment_intent.succeeded",
                    "data": {
                        "object": {"id": "pi_2", "status": "succeeded"},
                        "previous_attributes": {"status": "processing"},
                    },
                },
            ),
            # Secrets buried inside a list are reached too.
            (
                {"id": "obj_1", "items": [{"client_secret": "leak", "keep": 1}]},
                {"id": "obj_1", "items": [{"keep": 1}]},
            ),
            # Nothing to scrub — the object passes through unchanged.
            (
                {"id": "cus_1", "email": "a@b.com"},
                {"id": "cus_1", "email": "a@b.com"},
            ),
        ]
    )
    def test_removes_client_secret_everywhere(self, obj, expected):
        assert _scrub_client_secrets(obj) == expected

    def test_get_rows_scrubs_client_secret_from_flat_resource(self):
        # Wiring guard: PaymentIntent/SetupIntent/CheckoutSession rows flow through the flat get_rows
        # path, so a dropped scrub there would persist the secret to the warehouse table.
        objects = [{"id": "pi_1", "created": 1700000000, "client_secret": "pi_1_secret_abc", "amount": 500}]
        resource = StripeResource(method=lambda params: cast(ListObject[Any], _FakeStripeList(objects)))
        resumable_source_manager = MagicMock()
        resumable_source_manager.can_resume.return_value = False

        with patch.object(stripe_module, "_build_resources", return_value={PAYMENT_INTENT_RESOURCE_NAME: resource}):
            tables = list(
                get_rows(
                    api_key="sk_test_123",
                    endpoint=PAYMENT_INTENT_RESOURCE_NAME,
                    account_id=None,
                    db_incremental_field_last_value=None,
                    db_incremental_field_earliest_value=None,
                    logger=MagicMock(),
                    resumable_source_manager=resumable_source_manager,
                    api_version=STRIPE_API_VERSION_ACACIA,
                )
            )

        rows = [row for table in tables for row in table.to_pylist()]
        assert rows == [{"id": "pi_1", "created": 1700000000, "amount": 500}]


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

    def test_billing_alert_events_not_subscribed(self):
        # Narrowed from a blanket "no billing.* events" assertion now that BillingMeter,
        # BillingCreditGrant and BillingCreditBalanceTransaction are real tables. The original bug
        # it guards against was subscribing to billing.* events nothing could consume, and
        # billing.alert.* is the remaining example: there is no BillingAlert table.
        subscribed = _all_known_webhook_events()
        assert not any(e.startswith("billing.alert.") for e in subscribed)
        assert any(e.startswith("billing.meter.") for e in subscribed)

    def test_every_subscribed_event_can_populate_a_table(self):
        # The general form of the bug above: an event the endpoint subscribes to but whose object
        # type no table claims is pure inbound traffic the HogFunction drops. Each subscribed event
        # must be prefixed by a resource that also has a routing entry.
        routable_prefixes = {
            RESOURCE_TO_STRIPE_WEBHOOK_EVENT[resource]
            for resource in RESOURCE_TO_STRIPE_WEBHOOK_EVENT
            if resource in RESOURCE_TO_STRIPE_OBJECT_TYPE
        }
        unroutable = [
            event
            for event in _all_known_webhook_events()
            if not any(event.startswith(f"{prefix}.") for prefix in routable_prefixes)
        ]
        assert unroutable == []

    def test_payment_method_events_still_subscribed(self):
        # CustomerPaymentMethod keeps its mapping, so payment_method.* events stay subscribed.
        assert RESOURCE_TO_STRIPE_WEBHOOK_EVENT[CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME] == "payment_method"
        assert any(e.startswith("payment_method.") for e in _all_known_webhook_events())

    @parameterized.expand(
        [
            (PAYMENT_INTENT_RESOURCE_NAME, "payment_intent", "payment_intent"),
            (CHECKOUT_SESSION_RESOURCE_NAME, "checkout.session", "checkout.session"),
            (SUBSCRIPTION_SCHEDULE_RESOURCE_NAME, "subscription_schedule", "subscription_schedule"),
            (PROMOTION_CODE_RESOURCE_NAME, "promotion_code", "promotion_code"),
            (PLAN_RESOURCE_NAME, "plan", "plan"),
            (TAX_RATE_RESOURCE_NAME, "tax_rate", "tax_rate"),
            # Event prefix and object type diverge for this one.
            (TAX_ID_RESOURCE_NAME, "customer.tax_id", "tax_id"),
            (QUOTE_RESOURCE_NAME, "quote", "quote"),
            (BILLING_METER_RESOURCE_NAME, "billing.meter", "billing.meter"),
            (BILLING_CREDIT_GRANT_RESOURCE_NAME, "billing.credit_grant", "billing.credit_grant"),
            (
                BILLING_CREDIT_BALANCE_TRANSACTION_RESOURCE_NAME,
                "billing.credit_balance_transaction",
                "billing.credit_balance_transaction",
            ),
            (INVOICE_PAYMENT_RESOURCE_NAME, "invoice_payment", "invoice_payment"),
            (SETUP_INTENT_RESOURCE_NAME, "setup_intent", "setup_intent"),
            (PAYMENT_LINK_RESOURCE_NAME, "payment_link", "payment_link"),
            (TRANSFER_RESOURCE_NAME, "transfer", "transfer"),
            (APPLICATION_FEE_RESOURCE_NAME, "application_fee", "application_fee"),
            (TOPUP_RESOURCE_NAME, "topup", "topup"),
            (REVIEW_RESOURCE_NAME, "review", "review"),
            (EARLY_FRAUD_WARNING_RESOURCE_NAME, "radar.early_fraud_warning", "radar.early_fraud_warning"),
        ]
    )
    def test_new_resource_is_webhook_routable(self, resource: str, event_prefix: str, object_type: str) -> None:
        # Both halves are needed: the event map drives what the endpoint subscribes to, the object
        # map drives where the HogFunction writes the payload. One without the other is a no-op.
        assert RESOURCE_TO_STRIPE_WEBHOOK_EVENT[resource] == event_prefix
        assert RESOURCE_TO_STRIPE_OBJECT_TYPE[resource] == object_type
        assert any(e.startswith(f"{event_prefix}.") for e in _all_known_webhook_events())

    @parameterized.expand(
        [
            (SUBSCRIPTION_ITEM_RESOURCE_NAME,),
            (SETUP_ATTEMPT_RESOURCE_NAME,),
            (SHIPPING_RATE_RESOURCE_NAME,),
            (EVENT_RESOURCE_NAME,),
            (BILLING_CREDIT_BALANCE_SUMMARY_RESOURCE_NAME,),
            (BILLING_METER_EVENT_SUMMARY_RESOURCE_NAME,),
            (ENTITLEMENTS_FEATURE_RESOURCE_NAME,),
            (ENTITLEMENTS_ACTIVE_ENTITLEMENT_RESOURCE_NAME,),
        ]
    )
    def test_resource_without_stripe_event_stays_api_sweep_only(self, resource: str) -> None:
        # Stripe emits no event carrying these objects, so mapping them would only subscribe the
        # endpoint to traffic that can never populate the table.
        assert resource not in RESOURCE_TO_STRIPE_WEBHOOK_EVENT
        assert resource not in RESOURCE_TO_STRIPE_OBJECT_TYPE


class TestWebhookOnlyResponseWiring:
    def _make_manager(self, enabled: bool) -> MagicMock:
        manager = MagicMock(spec=WebhookSourceManager)
        manager.webhook_enabled = mock.AsyncMock(return_value=enabled)
        return manager

    def _source(self, endpoint: str, manager: MagicMock) -> Any:
        return stripe_module.stripe_source(
            api_key="sk_test_123",
            account_id=None,
            endpoint=endpoint,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            logger=MagicMock(adebug=mock.AsyncMock()),
            resumable_source_manager=MagicMock(can_resume=MagicMock(return_value=False)),
            webhook_source_manager=manager,
            api_version=STRIPE_API_VERSION_ACACIA,
        )

    def test_discount_response_is_webhook_only(self) -> None:
        # Discount has no list endpoint, so its SourceResponse must carry webhook_only=True —
        # otherwise a re-enable reset wipes the table with no poll able to rebuild it (data loss).
        manager = self._make_manager(enabled=False)
        response = self._source(DISCOUNT_RESOURCE_NAME, manager)
        assert response.webhook_only is True
        manager.webhook_enabled.assert_awaited_once_with(webhook_only=True)

    def test_pollable_response_is_not_webhook_only(self) -> None:
        manager = self._make_manager(enabled=False)
        response = self._source(CUSTOMER_RESOURCE_NAME, manager)
        assert response.webhook_only is False
        manager.webhook_enabled.assert_awaited_once_with(webhook_only=False)

    def test_discount_partitions_on_start_not_created(self) -> None:
        # Discount objects carry `start`/`end`, not `created`. If the incremental-field entry is
        # dropped the partition key falls back to "created" and the Delta partitioner KeyErrors on
        # the first real customer.discount.* webhook event, failing the whole sync.
        manager = self._make_manager(enabled=True)
        response = self._source(DISCOUNT_RESOURCE_NAME, manager)
        assert response.partition_keys == ["start"]


def _event_row(
    event_id: str, event_type: str, created: int, obj: dict, previous_attributes: dict | None = None
) -> dict[str, Any]:
    data: dict[str, Any] = {"object": obj}
    if previous_attributes is not None:
        data["previous_attributes"] = previous_attributes
    return {"id": event_id, "object": "event", "type": event_type, "created": created, "data": data}


class TestCustomerPaymentMethodHistory:
    def _make_manager(self, enabled: bool) -> MagicMock:
        manager = MagicMock(spec=WebhookSourceManager)
        manager.webhook_enabled = mock.AsyncMock(return_value=enabled)
        return manager

    def _source(self, endpoint: str, manager: MagicMock) -> Any:
        return stripe_module.stripe_source(
            api_key="sk_test_123",
            account_id=None,
            endpoint=endpoint,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            logger=MagicMock(adebug=mock.AsyncMock()),
            resumable_source_manager=MagicMock(can_resume=MagicMock(return_value=False)),
            webhook_source_manager=manager,
            api_version=STRIPE_API_VERSION_ACACIA,
        )

    @parameterized.expand(
        [
            # History must stay opt-in (should_sync_default=False, or one-shot setup force-enables
            # a per-customer sweep) and webhook-sync-only (webhook_only=True, or the UI offers full
            # refresh, which truncates the captured history on every scheduled run).
            (CUSTOMER_PAYMENT_METHOD_HISTORY_RESOURCE_NAME, True, False),
            # The existing upsert table must keep its behavior — the history flags must not leak.
            (CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME, False, True),
        ]
    )
    def test_schema_flags(self, endpoint: str, webhook_only: bool, should_sync_default: bool) -> None:
        source = StripeSource()
        config = StripeSourceConfig(
            auth_method=StripeAuthMethodConfig(selection="api_key", stripe_secret_key="sk_test_123")
        )
        schema = next(s for s in source.get_schemas(config, team_id=1) if s.name == endpoint)
        assert schema.webhook_only is webhook_only
        assert schema.should_sync_default is should_sync_default
        assert schema.supports_webhooks is True
        assert schema.supports_incremental is False
        assert schema.supports_append is False

    def test_history_mapping_key_cannot_collide_with_object_routing(self) -> None:
        # schema_mapping routes one schema per key. If the history table resolved to the bare
        # "payment_method" key, whichever schema registered last would silently steal the other's
        # events — so it must use the suffixed key, and that key must not equal any object type.
        source = StripeSource()
        assert (
            source.webhook_mapping_key(CUSTOMER_PAYMENT_METHOD_HISTORY_RESOURCE_NAME)
            == PAYMENT_METHOD_HISTORY_MAPPING_KEY
        )
        assert source.webhook_mapping_key(CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME) == "payment_method"
        assert PAYMENT_METHOD_HISTORY_MAPPING_KEY not in RESOURCE_TO_STRIPE_OBJECT_TYPE.values()

    def test_history_response_keys_on_the_observation_and_still_polls(self) -> None:
        # primary_keys=["id"] would collapse a payment method's whole history to one row on merge;
        # webhook_only=True on the response would skip the seed sweep, leaving the table empty
        # until the first webhook event.
        manager = self._make_manager(enabled=False)
        response = self._source(CUSTOMER_PAYMENT_METHOD_HISTORY_RESOURCE_NAME, manager)
        assert response.primary_keys == [HISTORY_EVENT_ID_COLUMN]
        assert response.webhook_only is False
        assert response.partition_keys == ["created"]
        manager.webhook_enabled.assert_awaited_once_with(webhook_only=False)

    @parameterized.expand(
        [
            # The history endpoint must keep both events; the upsert transformer would collapse
            # them to the latest state, silently dropping the intermediate observations the table
            # exists to record.
            (CUSTOMER_PAYMENT_METHOD_HISTORY_RESOURCE_NAME, 2),
            (CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME, 1),
        ]
    )
    def test_webhook_transformer_choice_controls_event_collapsing(self, endpoint: str, expected_rows: int) -> None:
        events = table_from_py_list(
            [
                _event_row(
                    "evt_1",
                    "payment_method.attached",
                    1700000100,
                    {"id": "pm_1", "object": "payment_method", "created": 1700000000, "customer": "cus_1"},
                ),
                _event_row(
                    "evt_2",
                    "payment_method.detached",
                    1700000200,
                    {"id": "pm_1", "object": "payment_method", "created": 1700000000, "customer": None},
                    previous_attributes={"customer": "cus_1"},
                ),
            ]
        )
        manager = self._make_manager(enabled=True)
        response = self._source(endpoint, manager)
        response.items()
        transformer = manager.get_items.call_args.kwargs["table_transformer"]
        assert transformer(events).num_rows == expected_rows

    def test_history_transformer_stamps_observation_columns(self) -> None:
        # The detached event's row must keep the event's identity and the detached-from customer
        # (via previous_attributes) — without them "which customer had this card on file, when?"
        # is unanswerable once the payment method is gone from the live list.
        events = table_from_py_list(
            [
                _event_row(
                    "evt_1",
                    "payment_method.attached",
                    1700000100,
                    {"id": "pm_1", "object": "payment_method", "created": 1700000000, "customer": "cus_1"},
                ),
                _event_row(
                    "evt_2",
                    "payment_method.detached",
                    1700000200,
                    {"id": "pm_1", "object": "payment_method", "created": 1700000000, "customer": None},
                    previous_attributes={"customer": "cus_1"},
                ),
            ]
        )
        rows = {row[HISTORY_EVENT_ID_COLUMN]: row for row in _webhook_history_table_transformer(events).to_pylist()}

        attached = rows["evt_1"]
        assert attached["customer"] == "cus_1"
        assert attached[HISTORY_EVENT_TYPE_COLUMN] == "payment_method.attached"
        assert attached[HISTORY_CAPTURED_AT_COLUMN] == 1700000100
        assert attached[HISTORY_PREVIOUS_ATTRIBUTES_COLUMN] is None

        detached = rows["evt_2"]
        assert detached["customer"] is None
        assert detached[HISTORY_EVENT_TYPE_COLUMN] == "payment_method.detached"
        assert detached[HISTORY_CAPTURED_AT_COLUMN] == 1700000200
        assert orjson.loads(detached[HISTORY_PREVIOUS_ATTRIBUTES_COLUMN]) == {"customer": "cus_1"}

    def test_history_transformer_dedupes_redelivered_events(self) -> None:
        # Stripe redelivers events on retry. Two copies of the same event in one drained batch
        # must land as one row — duplicates on the merge key make every later merge multi-match.
        obj = {"id": "pm_1", "object": "payment_method", "created": 1700000000, "customer": "cus_1"}
        events = table_from_py_list(
            [
                _event_row("evt_1", "payment_method.attached", 1700000100, obj),
                _event_row("evt_1", "payment_method.attached", 1700000100, obj),
            ]
        )
        assert _webhook_history_table_transformer(events).num_rows == 1

    def test_history_transformer_skips_malformed_rows_without_raising(self) -> None:
        # The S3 batch files are only deleted after a successful yield, so a transformer that
        # raises on one malformed payload (only reachable with the signature check bypassed)
        # would replay the same poison batch on every sync, wedging the schema forever.
        events = table_from_py_list(
            [
                # No event id — cannot be keyed.
                {
                    "object": "event",
                    "created": 1700000100,
                    "data": {"object": {"id": "pm_1", "object": "payment_method"}},
                },
                # No object id — cannot be attributed to a payment method.
                _event_row("evt_2", "payment_method.updated", 1700000200, {"object": "payment_method"}),
                _event_row(
                    "evt_3",
                    "payment_method.updated",
                    1700000300,
                    {"id": "pm_1", "object": "payment_method", "created": 1700000000, "customer": "cus_1"},
                ),
            ]
        )
        # The `type` column is present here; drop it to also cover a batch missing a column outright.
        events = events.drop_columns(["type"])
        rows = _webhook_history_table_transformer(events).to_pylist()
        assert [row[HISTORY_EVENT_ID_COLUMN] for row in rows] == ["evt_3"]
        assert rows[0][HISTORY_EVENT_TYPE_COLUMN] is None

    @parameterized.expand(
        [
            (CUSTOMER_PAYMENT_METHOD_HISTORY_RESOURCE_NAME, True),
            (CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME, False),
        ]
    )
    def test_seed_sweep_stamps_snapshot_rows_only_for_history(self, endpoint: str, expect_stamped: bool) -> None:
        # The sweep rows need a stable snapshot key: without it they have no merge key (the
        # table's primary key column would be missing), and a fallback re-sweep would duplicate
        # instead of refresh them. The same sweep feeding CustomerPaymentMethod must stay unstamped.
        def payment_methods_list(customer=None, params=None):
            return _list_object(
                [{"id": f"pm_{customer}", "object": "payment_method", "created": 1700000000, "customer": customer}]
            )

        resumable_source_manager = MagicMock()
        resumable_source_manager.can_resume.return_value = False

        with patch.object(stripe_module, "StripeClient") as client_cls:
            client = client_cls.return_value
            client.customers.list = lambda params: _list_object([{"id": "cus_1"}])
            client.customers.payment_methods.list = payment_methods_list
            rows: list[dict] = []
            for table in get_rows(
                api_key="sk_test_123",
                endpoint=endpoint,
                account_id=None,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                logger=MagicMock(),
                resumable_source_manager=resumable_source_manager,
                api_version=STRIPE_API_VERSION_ACACIA,
            ):
                rows.extend(table.to_pylist())

        assert [row["id"] for row in rows] == ["pm_cus_1"]
        row = rows[0]
        assert row["customer"] == "cus_1"
        if expect_stamped:
            assert row[HISTORY_EVENT_ID_COLUMN] == f"{HISTORY_SNAPSHOT_EVENT_TYPE}:pm_cus_1:cus_1"
            assert row[HISTORY_EVENT_TYPE_COLUMN] == HISTORY_SNAPSHOT_EVENT_TYPE
            assert isinstance(row[HISTORY_CAPTURED_AT_COLUMN], int)
        else:
            assert HISTORY_EVENT_ID_COLUMN not in row


class TestEndpointCatalogWiring:
    def setup_method(self):
        self.resources = stripe_module._build_resources(MagicMock(), logger=None)

    @pytest.mark.parametrize("endpoint", [e for e in ENDPOINTS if e not in WEBHOOK_ONLY_ENDPOINTS])
    def test_every_pollable_endpoint_has_a_resource(self, endpoint):
        # get_rows raises "Stripe endpoint does not exist" for anything listed in ENDPOINTS but not
        # wired into _build_resources, failing the sync for that table only once a user enables it.
        assert endpoint in self.resources

    def test_nested_resources_declare_a_registered_parent(self):
        # _resolve_to_flat looks the parent up in the same map to pick the endpoint it probes for
        # permissions, so an unregistered parent name KeyErrors during credential validation.
        for name, resource in self.resources.items():
            if isinstance(resource, StripeNestedResource):
                assert resource.parent_name in self.resources, name


class TestPartitioningAndColumnHints:
    def _source(self, endpoint: str) -> Any:
        manager = MagicMock(spec=WebhookSourceManager)
        manager.webhook_enabled = mock.AsyncMock(return_value=False)
        return stripe_module.stripe_source(
            api_key="sk_test_123",
            account_id=None,
            endpoint=endpoint,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            logger=MagicMock(adebug=mock.AsyncMock()),
            resumable_source_manager=MagicMock(can_resume=MagicMock(return_value=False)),
            webhook_source_manager=manager,
            api_version=STRIPE_API_VERSION_ACACIA,
        )

    @pytest.mark.parametrize("endpoint", NON_PARTITIONED_ENDPOINTS)
    def test_timestampless_endpoints_are_not_partitioned(self, endpoint):
        # These Stripe objects carry no timestamp at all. Partitioning them would fall back to
        # "created" and the datetime partitioner KeyErrors on the first row, killing the sync.
        response = self._source(endpoint)
        assert response.partition_keys is None
        assert response.partition_mode is None
        assert response.partition_count is None

    @pytest.mark.parametrize(
        "endpoint,expected_key",
        [
            (PAYMENT_INTENT_RESOURCE_NAME, "created"),
            (SUBSCRIPTION_ITEM_RESOURCE_NAME, "created"),
            (CUSTOMER_RESOURCE_NAME, "created"),
            # Meter event summaries carry no `created`. Without the declared `start_time` field the
            # partitioner falls back to `created` and KeyErrors on the first row.
            (BILLING_METER_EVENT_SUMMARY_RESOURCE_NAME, "start_time"),
        ],
    )
    def test_timestamped_endpoints_keep_weekly_partitioning(self, endpoint, expected_key):
        response = self._source(endpoint)
        assert response.partition_keys == [expected_key]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"

    def test_endpoint_without_managed_schema_gets_no_column_hints(self):
        # Only the original Stripe tables have a canonical schema in external_table_definitions.
        # Looking one up for a table that has none used to KeyError before the source ran a row.
        assert self._source(PAYMENT_INTENT_RESOURCE_NAME).column_hints == {}

    def test_endpoint_with_managed_schema_keeps_its_column_hints(self):
        column_hints = self._source(CHARGE_RESOURCE_NAME).column_hints
        assert column_hints
        assert column_hints["amount"] is not None

    def test_credit_balance_summary_keys_on_the_credit_grant(self):
        # The summary is a per-customer view rather than a stored object, so it has no `id`. Keying
        # it on "id" would merge every row onto a null key and collapse the table to one row.
        assert self._source(BILLING_CREDIT_BALANCE_SUMMARY_RESOURCE_NAME).primary_keys == ["credit_grant"]

    def test_other_endpoints_keep_the_id_primary_key(self):
        assert self._source(CHARGE_RESOURCE_NAME).primary_keys == ["id"]


class TestCreditBalanceSummaryFanout:
    def _run(self, grants: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
        retrieved: list[dict] = []

        def retrieve(params):
            retrieved.append(params)
            return {"object": "billing.credit_balance_summary", "customer": params["customer"], "balances": []}

        client = MagicMock()
        client.billing.credit_balance_summary.retrieve.side_effect = retrieve
        client.billing.credit_grants.list.return_value = _list_object(grants)

        resource = stripe_module._build_resources(client, logger=None)[BILLING_CREDIT_BALANCE_SUMMARY_RESOURCE_NAME]
        resumable_source_manager = MagicMock()
        resumable_source_manager.can_resume.return_value = False

        with (
            patch.object(stripe_module, "StripeClient"),
            patch.object(
                stripe_module,
                "_build_resources",
                return_value={BILLING_CREDIT_BALANCE_SUMMARY_RESOURCE_NAME: resource},
            ),
        ):
            rows: list[dict] = []
            for table in get_rows(
                api_key="sk_test_123",
                endpoint=BILLING_CREDIT_BALANCE_SUMMARY_RESOURCE_NAME,
                account_id=None,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                logger=MagicMock(),
                resumable_source_manager=resumable_source_manager,
                api_version=STRIPE_API_VERSION_ACACIA,
            ):
                rows.extend(table.to_pylist())
        return rows, retrieved

    def test_scopes_each_retrieve_to_its_grant_and_customer(self):
        # The retrieve needs the grant's customer as well as its id, so the fan-out has to read a
        # field off the parent object — passing the parent id alone would 400 on the missing filter.
        rows, retrieved = self._run([{"id": "credgr_1", "customer": "cus_1"}])

        assert retrieved == [
            {"customer": "cus_1", "filter": {"type": "credit_grant", "credit_grant": "credgr_1"}},
        ]
        assert [row["credit_grant"] for row in rows] == ["credgr_1"]
        assert [row["customer"] for row in rows] == ["cus_1"]

    def test_skips_grants_issued_to_an_account(self):
        # Grants made to an Account carry `customer_account` instead of `customer`; scoping the
        # summary on a missing customer would make Stripe reject the request.
        rows, retrieved = self._run(
            [
                {"id": "credgr_acct", "customer": None, "customer_account": "acct_1"},
                {"id": "credgr_cus", "customer": "cus_1"},
            ]
        )

        assert [params["filter"]["credit_grant"] for params in retrieved] == ["credgr_cus"]
        assert [row["credit_grant"] for row in rows] == ["credgr_cus"]


class TestCreditBalanceTransactionFanout:
    def _run(self, grants: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
        listed: list[dict] = []

        def list_transactions(params):
            listed.append(params)
            return _list_object([{"id": f"cbtxn_{params['credit_grant']}", "credit_grant": params["credit_grant"]}])

        client = MagicMock()
        client.billing.credit_balance_transactions.list.side_effect = list_transactions
        client.billing.credit_grants.list.return_value = _list_object(grants)

        resource = stripe_module._build_resources(client, logger=None)[BILLING_CREDIT_BALANCE_TRANSACTION_RESOURCE_NAME]
        resumable_source_manager = MagicMock()
        resumable_source_manager.can_resume.return_value = False

        with (
            patch.object(stripe_module, "StripeClient"),
            patch.object(
                stripe_module,
                "_build_resources",
                return_value={BILLING_CREDIT_BALANCE_TRANSACTION_RESOURCE_NAME: resource},
            ),
        ):
            rows: list[dict] = []
            for table in get_rows(
                api_key="sk_test_123",
                endpoint=BILLING_CREDIT_BALANCE_TRANSACTION_RESOURCE_NAME,
                account_id=None,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                logger=MagicMock(),
                resumable_source_manager=resumable_source_manager,
                api_version=STRIPE_API_VERSION_ACACIA,
            ):
                rows.extend(table.to_pylist())
        return rows, listed

    def test_scopes_each_list_call_to_its_grant_and_customer(self):
        # Stripe rejects `/v1/billing/credit_balance_transactions` outright without a `customer`
        # filter ("Must provide customer or customer_account") — calling it as an unscoped list, the
        # way every other top-level resource is called, 400s on every single sync.
        rows, listed = self._run([{"id": "credgr_1", "customer": "cus_1"}])

        assert listed == [{"customer": "cus_1", "limit": DEFAULT_LIMIT, "credit_grant": "credgr_1"}]
        assert [row["credit_grant"] for row in rows] == ["credgr_1"]

    def test_skips_grants_issued_to_an_account(self):
        # Grants made to an Account carry `customer_account` instead of `customer`; scoping the
        # request on a missing customer would make Stripe reject it the same way.
        rows, listed = self._run(
            [
                {"id": "credgr_acct", "customer": None, "customer_account": "acct_1"},
                {"id": "credgr_cus", "customer": "cus_1"},
            ]
        )

        assert [params["credit_grant"] for params in listed] == ["credgr_cus"]
        assert [row["credit_grant"] for row in rows] == ["credgr_cus"]


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


class TestSchemaSyncTypeCapability:
    def setup_method(self):
        config = StripeSourceConfig(
            auth_method=StripeAuthMethodConfig(selection="api_key", stripe_secret_key="sk_test_123")
        )
        self.by_name = {s.name: s for s in StripeSource().get_schemas(config, team_id=1)}

    @parameterized.expand(
        [
            # The meter sweep asks Stripe for a day range that starts on the newest day the table
            # already holds, and Stripe includes that day. An append never merges, so it would write
            # the day a second time on every sync and double what a sum of the usage totals reports.
            (BILLING_METER_EVENT_SUMMARY_RESOURCE_NAME, True, False),
            # Stripe applies `created[gt]` exclusively, so a created-filtered table never reads a row
            # it already holds and append stays the cheaper write.
            (CHARGE_RESOURCE_NAME, False, True),
        ]
    )
    def test_sync_type_capability(self, endpoint: str, incremental: bool, append: bool) -> None:
        schema = self.by_name[endpoint]
        assert (schema.supports_incremental, schema.supports_append) == (incremental, append)


class TestCreateWebhookPermissionErrorCopy:
    # Regression test: a permission-denied webhook creation used to always tell the user to add
    # the "Write" permission to their API key, even when the source was connected via OAuth and
    # has no API key to edit.
    @parameterized.expand(
        [
            ("api_key", "add the 'Write' permission for 'Webhook endpoints' to your API key"),
            ("oauth", "reconnect your Stripe integration"),
        ]
    )
    def test_permission_error_message_matches_auth_method(self, auth_method, expected_phrase):
        with patch.object(stripe_module, "StripeClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.webhook_endpoints.create.side_effect = stripe_lib.PermissionError("forbidden")

            result = create_webhook(
                api_key="sk_test_123",
                stripe_account_id=None,
                webhook_url="https://example.com/webhook",
                auth_method=auth_method,
            )

        assert result.success is False
        assert expected_phrase in (result.error or "")


class TestCreateWebhookLimitErrorCopy:
    # Regression test: hitting Stripe's webhook-endpoint cap used to surface Stripe's raw error
    # verbatim, so the user couldn't tell the account-wide limit was the cause or how to recover.
    def test_webhook_limit_error_gives_actionable_message(self):
        with patch.object(stripe_module, "StripeClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.webhook_endpoints.create.side_effect = stripe_lib.InvalidRequestError(
                "You have reached the maximum of 100 test webhook endpoints.", param=None
            )

            result = create_webhook(
                api_key="sk_test_123",
                stripe_account_id=None,
                webhook_url="https://example.com/webhook",
            )

        assert result.success is False
        assert "webhook endpoint limit" in (result.error or "")
        assert "manually" in (result.error or "")


class TestStripeAppManifestCoversSourcePermissions:
    # Regression test: PERMISSIONS drives the pre-filled restricted-key form, while the Stripe app
    # manifest drives what an OAuth connection is granted. The two drifted twice (rak_webhook_write
    # in April, rak_coupon_read in July), each time leaving OAuth users unable to create a webhook
    # or import coupons while the key path worked. The manifest is the checked-in source of truth
    # for the OAuth grant, so it must cover every scope the source asks a key for.
    def test_every_source_permission_is_requested_by_the_app(self):
        manifest_path = Path(settings.BASE_DIR) / "services" / "stripe-app" / "stripe-app.json"
        granted = {entry["permission"] for entry in orjson.loads(manifest_path.read_bytes())["permissions"]}

        # A restricted-key scope is the app permission name with a `rak_` prefix.
        required = {permission.removeprefix("rak_") for permission in PERMISSIONS}

        assert required, "PERMISSIONS is empty, so this assertion would pass vacuously"
        assert required - granted == set()


class TestStripeWarehouseParentFanout:
    """The `CustomerBalanceTransaction` sweep reading its parent from the warehouse."""

    @parameterized.expand(
        [
            (CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME, [CUSTOMER_RESOURCE_NAME]),
            (CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME, []),
            (CUSTOMER_PAYMENT_METHOD_HISTORY_RESOURCE_NAME, []),
            (ENTITLEMENTS_ACTIVE_ENTITLEMENT_RESOURCE_NAME, []),
            (BILLING_CREDIT_BALANCE_SUMMARY_RESOURCE_NAME, []),
            (CUSTOMER_RESOURCE_NAME, []),
        ]
    )
    def test_only_the_converted_child_declares_a_warehouse_parent(self, schema_name, expected):
        # The checked statement of which children opted in — the blast radius a reviewer reads.
        assert StripeSource().get_required_parent_schemas(schema_name) == expected

    def test_the_sweep_never_pages_the_customer_listing(self, tmp_path):
        # The silent-no-op guard. Declaring a parent without threading the flag and source id
        # leaves the sweep on the API path while the fan-out telemetry reports "warehouse", so
        # the test asserts the listing method is not merely unnecessary but never called.
        uri = _write_customer_parent_table(tmp_path, [{"id": "cus_1", "balance": -500}])
        parent_method = MagicMock(side_effect=AssertionError("the parent listing must not be paged"))
        nested_method = MagicMock(return_value=_list_object([{"id": "cbt_1"}]))

        rows = _run_nested_get_rows(
            nested_method,
            parent_method=parent_method,
            warehouse_parent=ParentTableRef(uri=uri, version=deltalake.DeltaTable(uri).version()),
        )

        parent_method.assert_not_called()
        assert [row["id"] for row in rows] == ["cbt_1"]

    def test_both_parent_paths_emit_identical_rows(self, tmp_path):
        # Parity is the property that matters: the child's output must not depend on where its
        # parent rows came from, including the parent id stamped onto every row.
        customers = [{"id": "cus_1", "balance": -500}, {"id": "cus_2", "balance": 250}]
        uri = _write_customer_parent_table(tmp_path, customers)

        api_method, _ = _recording_nested_method()
        warehouse_method, _ = _recording_nested_method()

        api_rows = _run_nested_get_rows(api_method, parent_objects=customers)
        warehouse_rows = _run_nested_get_rows(
            warehouse_method,
            warehouse_parent=ParentTableRef(uri=uri, version=deltalake.DeltaTable(uri).version()),
        )

        assert warehouse_rows == api_rows
        assert [row["customer"] for row in warehouse_rows] == ["cus_1", "cus_2"]

    def test_both_parent_paths_report_the_fan_out_size_and_where_it_came_from(self, tmp_path):
        # A webhook-maintained parent holds only what its drains delivered, so it can be missing
        # customers the API listing still returns. Comparing the fan-out size across the two parent
        # sources for one schema is the only signal for that, and it needs both a count and the
        # label naming which source produced it. `cus_zero` is ruled out by the skip predicate and
        # still counts, because the number has to mean the same thing on both sources.
        customers = [{"id": "cus_zero", "balance": 0}, {"id": "cus_credit", "balance": -500}]
        uri = _write_customer_parent_table(tmp_path, customers)
        api_logger = MagicMock()
        warehouse_logger = MagicMock()

        api_method, api_probed = _recording_nested_method()
        warehouse_method, warehouse_probed = _recording_nested_method()

        _run_nested_get_rows(
            api_method,
            parent_objects=customers,
            parent_has_nested=stripe_module._customer_might_have_balance_transactions,
            logger=api_logger,
        )
        _run_nested_get_rows(
            warehouse_method,
            parent_has_nested=stripe_module._customer_might_have_balance_transactions,
            warehouse_parent=ParentTableRef(uri=uri, version=deltalake.DeltaTable(uri).version()),
            logger=warehouse_logger,
        )

        assert api_probed == warehouse_probed == ["cus_credit"]
        api_logger.info.assert_called_once_with(
            FANOUT_PARENT_ROWS_CONSUMED, parent_source="api", rows_total=2, resumed=False
        )
        warehouse_logger.info.assert_called_once_with(
            FANOUT_PARENT_ROWS_CONSUMED, parent_source="warehouse", rows_total=2, resumed=False
        )

    def test_the_skip_predicate_reads_the_balance_off_the_warehouse_row(self, tmp_path):
        # The projected `balance` column is what makes this conversion worth doing: without it
        # every customer would be probed, turning a listing-dominated run into one call each.
        customers = [
            {"id": "cus_zero", "balance": 0},
            {"id": "cus_credit", "balance": -500},
            {"id": "cus_unknown", "balance": None},
        ]
        uri = _write_customer_parent_table(tmp_path, customers)
        nested_method, probed = _recording_nested_method()

        _run_nested_get_rows(
            nested_method,
            parent_has_nested=stripe_module._customer_might_have_balance_transactions,
            warehouse_parent=ParentTableRef(uri=uri, version=deltalake.DeltaTable(uri).version()),
        )

        assert probed == ["cus_credit", "cus_unknown"]

    def test_a_parent_deleted_since_the_snapshot_is_skipped(self, tmp_path):
        # The snapshot can name customers deleted upstream since the parent last synced. Their
        # child call 404s, and the sweep must carry on rather than failing the whole import.
        customers = [{"id": "cus_ok", "balance": -1}, {"id": "cus_gone", "balance": -1}]
        uri = _write_customer_parent_table(tmp_path, customers)

        nested_method, probed = _recording_nested_method(missing={"cus_gone"})

        rows = _run_nested_get_rows(
            nested_method,
            warehouse_parent=ParentTableRef(uri=uri, version=deltalake.DeltaTable(uri).version()),
        )

        assert [row["id"] for row in rows] == ["cbt_cus_ok"]
        assert probed == ["cus_ok", "cus_gone"]

    def test_resume_state_records_the_scan_position_not_a_stripe_cursor(self, tmp_path):
        # A Stripe cursor names a place in Stripe's list ordering, which a parquet scan does not
        # have. Saving one here would resume the next run somewhere arbitrary.
        uri = _write_customer_parent_table(tmp_path, [{"id": "cus_1", "balance": -500}])
        manager = MagicMock()
        manager.can_resume.return_value = False

        _run_nested_get_rows(
            MagicMock(return_value=_list_object([{"id": "cbt_1"}])),
            resumable_source_manager=manager,
            warehouse_parent=ParentTableRef(uri=uri, version=deltalake.DeltaTable(uri).version()),
        )

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved, "the sweep must checkpoint at least once"
        assert all(state.starting_after is None for state in saved)
        assert all(state.warehouse_table_uri == uri for state in saved)
        assert all(state.warehouse_fragment_index is not None for state in saved)

    @parameterized.expand(
        [
            ("api_cursor", {"starting_after": "cus_1"}),
            (
                "another_table",
                {
                    "warehouse_fragment_index": 0,
                    "warehouse_row_offset": 1,
                    "warehouse_table_uri": "s3://elsewhere",
                    "warehouse_version": 0,
                },
            ),
            ("another_version", {"warehouse_fragment_index": 0, "warehouse_row_offset": 1, "warehouse_version": 99}),
        ]
    )
    def test_unusable_resume_state_restarts_the_sweep(self, _name, state_kwargs, tmp_path=None):
        # Delta versions restart at 0 when a table is rebuilt, so a position from another table
        # or version would skip rows the scan has never read. Restarting is the safe answer.
        import tempfile

        directory = Path(tempfile.mkdtemp())
        customers = [{"id": "cus_1", "balance": -1}, {"id": "cus_2", "balance": -1}]
        uri = _write_customer_parent_table(directory, customers)
        if "warehouse_table_uri" in state_kwargs and state_kwargs["warehouse_table_uri"] != "s3://elsewhere":
            state_kwargs["warehouse_table_uri"] = uri
        elif "warehouse_version" in state_kwargs and "warehouse_table_uri" not in state_kwargs:
            state_kwargs["warehouse_table_uri"] = uri

        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = stripe_module.StripeResumeConfig(**state_kwargs)

        nested_method, _ = _recording_nested_method()
        rows = _run_nested_get_rows(
            nested_method,
            resumable_source_manager=manager,
            warehouse_parent=ParentTableRef(uri=uri, version=deltalake.DeltaTable(uri).version()),
            can_resume=True,
        )

        assert [row["id"] for row in rows] == ["cbt_cus_1", "cbt_cus_2"]

    def test_a_matching_position_resumes_after_the_parent_it_names(self, tmp_path):
        customers = [{"id": "cus_1", "balance": -1}, {"id": "cus_2", "balance": -1}, {"id": "cus_3", "balance": -1}]
        uri = _write_customer_parent_table(tmp_path, customers)
        version = deltalake.DeltaTable(uri).version()
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = stripe_module.StripeResumeConfig(
            warehouse_fragment_index=0,
            warehouse_row_offset=1,
            warehouse_table_uri=uri,
            warehouse_version=version,
        )

        nested_method, _ = _recording_nested_method()
        logger = MagicMock()
        rows = _run_nested_get_rows(
            nested_method,
            resumable_source_manager=manager,
            warehouse_parent=ParentTableRef(uri=uri, version=version),
            can_resume=True,
            logger=logger,
        )

        assert [row["id"] for row in rows] == ["cbt_cus_2", "cbt_cus_3"]
        # A resumed attempt counts only the parents it walked, so its fan-out size is partial. The
        # line has to say so, or it reads as a warehouse parent that is missing rows.
        assert logger.info.call_args.kwargs["resumed"] is True

    @parameterized.expand(
        [
            ("flag_off", False, CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME),
            ("unconverted_endpoint", True, CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME),
        ]
    )
    def test_resolve_returns_nothing_when_the_warehouse_path_does_not_apply(self, _name, flag, endpoint):
        assert stripe_module._resolve_warehouse_parent(endpoint, 1, "source-1", flag) is None

    def test_an_unusable_parent_table_falls_back_to_the_api_path(self):
        # A soft dependency: a parent that cannot be read costs this run the optimization, never
        # the sync itself.
        with patch.object(stripe_module, "try_resolve_parent_table", return_value=None, create=True):
            with patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.try_resolve_parent_table",
                return_value=None,
            ):
                assert (
                    stripe_module._resolve_warehouse_parent(
                        CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME, 1, "source-1", True
                    )
                    is None
                )


class TestStripeNestedSweepResume:
    @pytest.mark.parametrize("from_warehouse", [False, True], ids=["api", "warehouse"])
    @pytest.mark.parametrize(
        "first_parent_rows,expected",
        [
            (["txn_1", "txn_2", "txn_3"], ["txn_1", "txn_2", "txn_3", "txn_4"]),
            (["txn_1", "txn_2"], ["txn_1", "txn_2", "txn_4"]),
        ],
        ids=["chunk_splits_a_parent", "chunk_ends_on_a_boundary"],
    )
    def test_interrupted_sweep_resumes_without_losing_or_repeating_rows(
        self, from_warehouse, first_parent_rows, expected, tmp_path
    ):
        customers = [{"id": "cus_1", "balance": -500}, {"id": "cus_2", "balance": -500}]
        nested_rows = {
            "cus_1": [{"id": row_id} for row_id in first_parent_rows],
            "cus_2": [{"id": "txn_4"}],
        }

        def _after(rows, cursor):
            if cursor is None:
                return rows
            return rows[[row["id"] for row in rows].index(cursor) + 1 :]

        def parent_method(params=None, **kwargs):
            return _list_object(_after(customers, (params or {}).get("starting_after")))

        def nested_method(customer=None, params=None):
            return _list_object(_after(nested_rows[customer], (params or {}).get("starting_after")))

        warehouse_parent = None
        if from_warehouse:
            uri = _write_customer_parent_table(tmp_path, customers)
            warehouse_parent = ParentTableRef(uri=uri, version=deltalake.DeltaTable(uri).version())

        resource = StripeNestedResource(
            method=nested_method,
            nested_parent_param="customer",
            parent_id="id",
            parent=StripeResource(method=parent_method),
            parent_name=CUSTOMER_RESOURCE_NAME,
        )

        def run(manager):
            collected: list[dict] = []
            checkpoints: list[tuple[int, Any]] = []
            manager.save_state.side_effect = lambda state: checkpoints.append((len(collected), state))
            with (
                patch.object(stripe_module, "StripeClient"),
                patch.object(stripe_module, "STRIPE_CHUNK_SIZE", 2),
                patch.object(
                    stripe_module,
                    "_build_resources",
                    return_value={CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME: resource},
                ),
            ):
                for table in get_rows(
                    api_key="sk_test_123",
                    endpoint=CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
                    account_id=None,
                    db_incremental_field_last_value=None,
                    db_incremental_field_earliest_value=None,
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                    api_version=STRIPE_API_VERSION_ACACIA,
                    warehouse_parent=warehouse_parent,
                ):
                    collected.extend(table.to_pylist())
            return collected, checkpoints

        killed = MagicMock()
        killed.can_resume.return_value = False
        all_rows, checkpoints = run(killed)
        rows_written, crash_state = checkpoints[0]

        restarted = MagicMock()
        restarted.can_resume.return_value = True
        restarted.load_state.return_value = crash_state
        resumed_rows, _ = run(restarted)

        assert [row["id"] for row in all_rows[:rows_written] + resumed_rows] == expected

    @pytest.mark.parametrize("from_warehouse", [False, True], ids=["api_run", "warehouse_run"])
    def test_a_nested_cursor_saved_by_the_other_path_is_discarded(self, from_warehouse, tmp_path):
        customers = [{"id": "cus_1", "balance": -500}]
        uri = _write_customer_parent_table(tmp_path, customers)
        nested_params: list[dict] = []

        def nested_method(customer=None, params=None):
            nested_params.append(params or {})
            return _list_object([{"id": "txn_1"}])

        stale = (
            stripe_module.StripeResumeConfig(
                starting_after="cus_0", nested_parent_id="cus_1", nested_starting_after="txn_9"
            )
            if from_warehouse
            else stripe_module.StripeResumeConfig(
                nested_parent_id="cus_1",
                nested_starting_after="txn_9",
                warehouse_fragment_index=0,
                warehouse_row_offset=0,
                warehouse_table_uri="s3://somewhere-else",
                warehouse_version=0,
            )
        )
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = stale

        rows = _run_nested_get_rows(
            nested_method,
            parent_objects=customers,
            warehouse_parent=(
                ParentTableRef(uri=uri, version=deltalake.DeltaTable(uri).version()) if from_warehouse else None
            ),
            resumable_source_manager=manager,
            can_resume=True,
        )

        assert "starting_after" not in nested_params[0]
        assert [row["id"] for row in rows] == ["txn_1"]


_DAY = 24 * 60 * 60


class TestMeterSummaryWindow:
    def test_window_covers_whole_days_up_to_the_current_one(self):
        # Stripe only aggregates daily buckets over UTC day boundaries, and a bucket that is still
        # filling reports a different total on the next run.
        window = stripe_module._meter_summary_window(None, now=3 * _DAY + 3600)
        assert window.end_time == 3 * _DAY
        assert window.start_time == 3 * _DAY - stripe_module.METER_SUMMARY_INITIAL_LOOKBACK_DAYS * _DAY

    def test_watermark_starts_the_window_at_the_newest_day_held(self):
        window = stripe_module._meter_summary_window(100 * _DAY, now=103 * _DAY + 10)
        assert (window.start_time, window.end_time) == (100 * _DAY, 103 * _DAY)

    def test_watermark_past_the_day_boundary_gives_an_empty_window(self):
        # Stripe rejects a range that ends before it starts, which would fail the whole sync.
        window = stripe_module._meter_summary_window(200 * _DAY, now=103 * _DAY)
        assert window.start_time == window.end_time


class TestMeterEventSummaryFanout:
    def _subscription(
        self,
        subscription_id: str,
        customer: str,
        prices: list[dict[str, Any]],
        items_has_more: bool = False,
    ) -> dict[str, Any]:
        return {
            "id": subscription_id,
            "customer": customer,
            "items": {"data": [{"price": price} for price in prices], "has_more": items_has_more},
        }

    def _run(
        self,
        subscriptions: list[dict[str, Any]],
        summaries_per_meter: int = 1,
        resumable_source_manager: Any = None,
        items_by_subscription: dict[str, list[dict[str, Any]]] | None = None,
    ) -> tuple[list[dict], list[tuple[str, dict]]]:
        requested: list[tuple[str, dict]] = []

        def event_summaries_list(meter, params):
            requested.append((meter, params))
            return _FakeStripeList(
                [
                    {
                        "id": f"mtrusg_{meter}_{params['customer']}_{index}",
                        "object": "billing.meter_event_summary",
                        "meter": meter,
                        "aggregated_value": 12,
                        "start_time": params["start_time"],
                        "end_time": params["end_time"],
                    }
                    for index in range(summaries_per_meter)
                ]
            )

        def subscription_items_list(params):
            return _FakeStripeList(
                items_by_subscription.get(params["subscription"], []) if items_by_subscription else []
            )

        client = MagicMock()
        client.billing.meters.event_summaries.list.side_effect = event_summaries_list
        client.subscription_items.list.side_effect = subscription_items_list
        client.subscriptions.list.return_value = _list_object(subscriptions)
        self.client = client

        real_build_resources = stripe_module._build_resources

        def build_resources(_client, logger=None, meter_summary_window=None):
            return real_build_resources(client, logger=None, meter_summary_window=meter_summary_window)

        if resumable_source_manager is None:
            resumable_source_manager = MagicMock()
            resumable_source_manager.can_resume.return_value = False

        with (
            patch.object(stripe_module, "StripeClient"),
            patch.object(stripe_module, "_build_resources", side_effect=build_resources),
        ):
            rows: list[dict] = []
            for table in get_rows(
                api_key="sk_test_123",
                endpoint=BILLING_METER_EVENT_SUMMARY_RESOURCE_NAME,
                account_id=None,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                logger=MagicMock(),
                resumable_source_manager=resumable_source_manager,
                api_version=STRIPE_API_VERSION_ACACIA,
            ):
                rows.extend(table.to_pylist())
        return rows, requested

    def test_only_subscriptions_with_a_metered_price_reach_stripe(self):
        # The endpoint costs one call per meter and customer pair, so a sweep that asked for every
        # customer would spend most of its calls on customers that meter nothing.
        rows, requested = self._run(
            [
                self._subscription("sub_flat", "cus_1", [{"recurring": {"interval": "month"}}, {}]),
                self._subscription("sub_metered", "cus_2", [{"recurring": {"meter": "mtr_a"}}]),
            ]
        )
        assert [meter for meter, _ in requested] == ["mtr_a"]
        # The summary object names its meter but not its customer, so the sweep stamps both keys.
        # The subscription is stamped as discovery provenance, because Stripe scopes the total to
        # the customer and the meter.
        assert [(row["meter"], row["customer"], row["discovery_subscription"]) for row in rows] == [
            ("mtr_a", "cus_2", "sub_metered")
        ]

    def test_a_whole_total_is_still_written_as_a_float(self):
        # Stripe serializes a whole total as a JSON integer, so a sweep that only sees whole totals
        # would create an integer column. The first fractional total could then not be written, and
        # the reset that recovers the sync drops every day older than the initial lookback.
        rows, _ = self._run([self._subscription("sub_1", "cus_1", [{"recurring": {"meter": "mtr_a"}}])])
        assert rows and all(isinstance(row["aggregated_value"], float) for row in rows)

    def test_a_meter_past_the_embedded_item_page_is_still_asked_for(self):
        # Stripe embeds only the first page of a subscription's items. This subscription meters
        # nothing on that page, so without completing the items it would be skipped entirely and
        # its customer would have no usage rows at all.
        rows, requested = self._run(
            [self._subscription("sub_1", "cus_1", [{"recurring": {"interval": "month"}}], items_has_more=True)],
            items_by_subscription={
                "sub_1": [
                    {"price": {"recurring": {"interval": "month"}}},
                    {"price": {"recurring": {"meter": "mtr_late"}}},
                ]
            },
        )
        assert [meter for meter, _ in requested] == ["mtr_late"]
        assert [(row["meter"], row["customer"]) for row in rows] == [("mtr_late", "cus_1")]
        # One call completes the whole subscription, whatever it meters.
        assert self.client.subscription_items.list.call_count == 1

    def test_a_complete_item_page_costs_no_extra_call(self):
        # The saving this fan-out is built on is that a subscription Stripe already described in
        # full needs no call of its own before the sweep decides whether to skip it.
        self._run([self._subscription("sub_1", "cus_1", [{"recurring": {"meter": "mtr_a"}}])])
        assert self.client.subscription_items.list.call_count == 0

    @parameterized.expand(
        [
            # The parent listing carries every subscription the account has ever created, so a call
            # per meter on one that ended long ago is spent on every sync and the count only grows
            # with churn.
            (stripe_module.METER_EVENT_BACKDATING_DAYS + 10, []),
            # Usage can still be recorded for a customer after the subscription ends, so an end just
            # outside the window keeps the subscription rather than cutting it at the window edge.
            (1, ["mtr_a"]),
        ]
    )
    def test_an_ended_subscription_is_asked_for_only_while_usage_can_still_land(
        self, days_before_window: int, expected_meters: list[str]
    ) -> None:
        window = stripe_module._meter_summary_window(None)
        subscription = self._subscription("sub_1", "cus_1", [{"recurring": {"meter": "mtr_a"}}])
        subscription["ended_at"] = window.start_time - days_before_window * _DAY
        _, requested = self._run([subscription])
        assert [meter for meter, _ in requested] == expected_meters

    def test_a_meter_on_several_items_is_asked_for_once(self):
        # Both items bill the same usage series, so a second call would only double the volume.
        _, requested = self._run(
            [
                self._subscription(
                    "sub_1",
                    "cus_1",
                    [
                        {"recurring": {"meter": "mtr_b"}},
                        {"recurring": {"meter": "mtr_a"}},
                        {"recurring": {"meter": "mtr_a"}},
                    ],
                )
            ]
        )
        assert [meter for meter, _ in requested] == ["mtr_a", "mtr_b"]

    def test_request_asks_for_daily_buckets_of_the_subscription_customer(self):
        _, requested = self._run([self._subscription("sub_1", "cus_1", [{"recurring": {"meter": "mtr_a"}}])])
        _, params = requested[0]
        assert params["customer"] == "cus_1"
        assert params["value_grouping_window"] == "day"
        assert params["start_time"] % _DAY == 0
        assert params["end_time"] % _DAY == 0

    def test_resume_drops_the_rows_already_written_and_sends_no_cursor(self):
        # The cursor names a row in the subscription's combined list across its meters. Stripe lists
        # one meter at a time and cannot resolve it, so the sweep applies the cursor itself.
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = stripe_module.StripeResumeConfig(
            nested_parent_id="sub_1",
            nested_starting_after="mtrusg_mtr_a_cus_1_0",
        )
        rows, requested = self._run(
            [self._subscription("sub_1", "cus_1", [{"recurring": {"meter": "mtr_a"}}])],
            summaries_per_meter=3,
            resumable_source_manager=manager,
        )
        assert [row["id"] for row in rows] == ["mtrusg_mtr_a_cus_1_1", "mtrusg_mtr_a_cus_1_2"]
        assert "starting_after" not in requested[0][1]
