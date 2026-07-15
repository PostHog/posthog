import uuid
from collections.abc import Mapping
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import stripe as stripe_lib
import requests
from parameterized import parameterized
from stripe._http_client import HTTPClient

from posthog.models.integration import Integration

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import StripeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
    ACCOUNT_RESOURCE_NAME,
    CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
    CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME,
    STRIPE_API_VERSION_ACACIA,
    SUBSCRIPTION_RESOURCE_NAME,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.settings import WEBHOOK_ONLY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source import StripeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe import (
    StripeAuthenticationError,
    StripeNestedResource,
    StripePermissionError,
    StripeResource,
    StripeResumeConfig,
    StripeValidationError,
    _build_resources,
    _call_stripe,
    _clean_stripe_error_message,
    _tracked_stripe_http_client,
    check_endpoint_permissions,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.tests.e2e.conftest import run_external_data_job_workflow

from .data import BALANCE_TRANSACTIONS

pytestmark = pytest.mark.usefixtures("minio_client")


def _exception_with_code(message: str, code: str) -> Exception:
    error = Exception(message)
    error.code = code  # type: ignore[attr-defined]
    return error


@pytest.fixture
def external_data_source(team):
    source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={
            "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
            "stripe_account_id": "acct_id",
        },
    )
    return source


@pytest.fixture
def external_data_schema_full_refresh(external_data_source, team):
    schema = ExternalDataSchema.objects.create(
        name="BalanceTransaction",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="full_refresh",
        sync_type_config={},
    )
    return schema


@pytest.fixture
def external_data_schema_incremental(external_data_source, team):
    schema = ExternalDataSchema.objects.create(
        name="BalanceTransaction",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="incremental",
        sync_type_config={"incremental_field": "created", "incremental_field_type": "integer"},
    )
    return schema


# mock the chunk size to 1 so we can test how iterating over chunks of data works, particularly with updating the
# incremental field last value
@mock.patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_source_full_refresh(
    team, mock_stripe_api, external_data_source, external_data_schema_full_refresh
):
    """Test that a full refresh sync works as expected.

    We expect a single API call to be made to our mock Stripe API, which returns all the balance transactions.
    """

    with mock.patch.object(ResumableSourceManager, "save_state") as mock_save_state:
        table_name = "stripe_balancetransaction"
        expected_num_rows = len(BALANCE_TRANSACTIONS)

        await run_external_data_job_workflow(
            team=team,
            external_data_source=external_data_source,
            external_data_schema=external_data_schema_full_refresh,
            table_name=table_name,
            expected_rows_synced=expected_num_rows,
            expected_total_rows=expected_num_rows,
        )

        # Check that the API was called as expected
        api_calls_made = mock_stripe_api.get_all_api_calls()
        assert len(api_calls_made) == 1
        assert api_calls_made[0].url == "https://api.stripe.com/v1/balance_transactions?limit=100"

        # Make sure the last balance transaction ID was saved as the resume point
        assert mock_save_state.call_args[0][0].starting_after == BALANCE_TRANSACTIONS[-1]["id"]


# mock the chunk size to 1 so we can test how iterating over chunks of data works, particularly with updating the
# incremental field last value
@mock.patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_source_resuming_full_refresh(
    team, mock_stripe_api, external_data_source, external_data_schema_full_refresh
):
    """Test that resuming a full refresh sync works as expected.

    We expect a single API call to be made to our mock Stripe API, which returns all the balance transactions with a filter.
    """

    starting_after = "customer_id_1"
    with (
        mock.patch.object(ResumableSourceManager, "can_resume", return_value=True),
        mock.patch.object(
            ResumableSourceManager, "load_state", return_value=StripeResumeConfig(starting_after=starting_after)
        ),
        mock.patch.object(ResumableSourceManager, "save_state") as mock_save_state,
    ):
        table_name = "stripe_balancetransaction"
        expected_num_rows = len(BALANCE_TRANSACTIONS)

        await run_external_data_job_workflow(
            team=team,
            external_data_source=external_data_source,
            external_data_schema=external_data_schema_full_refresh,
            table_name=table_name,
            expected_rows_synced=expected_num_rows,
            expected_total_rows=expected_num_rows,
        )

    # Check that the API was called as expected
    api_calls_made = mock_stripe_api.get_all_api_calls()
    assert len(api_calls_made) == 1
    assert (
        api_calls_made[0].url
        == f"https://api.stripe.com/v1/balance_transactions?limit=100&starting_after={starting_after}"
    )

    # Make sure the last balance transaction ID was saved as the resume point
    assert mock_save_state.call_args[0][0].starting_after == BALANCE_TRANSACTIONS[-1]["id"]


# mock the chunk size to 1 so we can test how iterating over chunks of data works, particularly with updating the
# incremental field last value
@mock.patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_source_incremental(team, mock_stripe_api, external_data_source, external_data_schema_incremental):
    """Test that an incremental sync works as expected.

    We set the 'max_created' value to the created timestamp of the third item in the BALANCE_TRANSACTIONS list. This
    means on the first sync it will return all the data, except for the most recent 2 balance transactions.

    Then, after resetting the 'max_created' value, we expect the incremental sync to return the most recent 2 balance
    transactions when it is called again.
    """

    table_name = "stripe_balancetransaction"

    # mock the API so it doesn't return all data on initial sync
    third_item_created = BALANCE_TRANSACTIONS[2]["created"]
    mock_stripe_api.set_max_created(third_item_created)
    expected_rows_synced = 3
    expected_total_rows = 3

    await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_incremental,
        table_name=table_name,
        expected_rows_synced=expected_rows_synced,
        expected_total_rows=expected_total_rows,
    )

    # Check that the API was called as expected
    api_calls_made = mock_stripe_api.get_all_api_calls()
    assert len(api_calls_made) == 1
    assert parse_qs(urlparse(api_calls_made[0].url).query) == {
        "limit": ["100"],
    }

    mock_stripe_api.reset_max_created()
    # run the incremental sync
    # we expect this to bring in 2 more rows
    expected_rows_synced = 2
    expected_total_rows = len(BALANCE_TRANSACTIONS)

    await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_incremental,
        table_name=table_name,
        expected_rows_synced=expected_rows_synced,
        expected_total_rows=expected_total_rows,
    )

    api_calls_made = mock_stripe_api.get_all_api_calls()
    # Check that the API was called once more
    assert len(api_calls_made) == 3
    assert parse_qs(urlparse(api_calls_made[1].url).query) == {
        "created[lt]": [str(BALANCE_TRANSACTIONS[4]["created"])],
        "limit": ["100"],
    }
    assert parse_qs(urlparse(api_calls_made[2].url).query) == {
        "created[gt]": [f"{third_item_created}"],
        "limit": ["100"],
    }


def _mock_all_stripe_endpoints(mock_client):
    mock_client.accounts.list = mock.MagicMock()
    mock_client.balance_transactions.list = mock.MagicMock()
    mock_client.charges.list = mock.MagicMock()
    mock_client.customers.list = mock.MagicMock()
    mock_client.disputes.list = mock.MagicMock()
    mock_client.invoice_items.list = mock.MagicMock()
    mock_client.invoices.list = mock.MagicMock()
    mock_client.payouts.list = mock.MagicMock()
    mock_client.prices.list = mock.MagicMock()
    mock_client.products.list = mock.MagicMock()
    mock_client.subscriptions.list = mock.MagicMock()
    mock_client.refunds.list = mock.MagicMock()
    mock_client.credit_notes.list = mock.MagicMock()
    mock_client.coupons.list = mock.MagicMock()


def test_validate_credentials_basic_only_probes_one_endpoint():
    """Default (no `endpoints`) is the cheap auth probe — one call total. We must not bang
    every resource during initial source setup; that's what schema selection is for."""
    mock_client = mock.MagicMock()
    _mock_all_stripe_endpoints(mock_client)

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
        return_value=mock_client,
    ):
        result = validate_credentials("api_key")

        assert result is True

        # Only the basic-probe endpoint (Customer) is hit.
        mock_client.customers.list.assert_called_once_with(params={"limit": 1})

        # Every other endpoint stays untouched.
        mock_client.accounts.list.assert_not_called()
        mock_client.balance_transactions.list.assert_not_called()
        mock_client.charges.list.assert_not_called()
        mock_client.disputes.list.assert_not_called()
        mock_client.invoice_items.list.assert_not_called()
        mock_client.invoices.list.assert_not_called()
        mock_client.payouts.list.assert_not_called()
        mock_client.prices.list.assert_not_called()
        mock_client.products.list.assert_not_called()
        mock_client.subscriptions.list.assert_not_called()
        mock_client.refunds.list.assert_not_called()
        mock_client.credit_notes.list.assert_not_called()
        mock_client.coupons.list.assert_not_called()


def test_subscription_list_uses_expand_for_discounts():
    """Subscription list call must expand discounts so coupon details ride inline.

    Without `expand=data.discounts` Stripe returns an array of discount IDs, which is
    insufficient for revenue projection — customers need amount_off / percent_off /
    duration. Item-level discounts (`items.data.discounts`) need the same treatment.
    """
    mock_client = mock.MagicMock()

    # Empty page response — we only care about how the list method was invoked.
    empty_page = mock.MagicMock()
    empty_page.auto_paging_iter.return_value = iter([])
    mock_client.subscriptions.list.return_value = empty_page

    resumable_manager = mock.MagicMock()
    resumable_manager.can_resume.return_value = False

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
        return_value=mock_client,
    ):
        # Drain the generator so the list call actually happens.
        list(
            get_rows(
                api_key="api_key",
                endpoint=SUBSCRIPTION_RESOURCE_NAME,
                account_id=None,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                logger=mock.MagicMock(),
                resumable_source_manager=resumable_manager,
                api_version=STRIPE_API_VERSION_ACACIA,
                should_use_incremental_field=False,
            )
        )

    mock_client.subscriptions.list.assert_called_once()
    call_params = mock_client.subscriptions.list.call_args.kwargs["params"]
    assert call_params["status"] == "all"
    # Key must be "expand" (not "expand[]"): a list under "expand[]" encodes to expand[][0]=…
    # (doubled brackets) which Stripe rejects. See _build_resources for the full explanation.
    assert call_params["expand"] == ["data.discounts", "data.items.data.discounts"]
    assert "expand[]" not in call_params


@pytest.mark.parametrize("endpoint", WEBHOOK_ONLY_ENDPOINTS)
def test_webhook_only_endpoint_yields_no_rows(endpoint):
    """Webhook-only resources have no API list endpoint; get_rows must short-circuit
    cleanly so the initial sync completes and the webhook source manager can take over."""
    mock_client = mock.MagicMock()
    resumable_manager = mock.MagicMock()
    resumable_manager.can_resume.return_value = False

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
        return_value=mock_client,
    ):
        rows = list(
            get_rows(
                api_key="api_key",
                endpoint=endpoint,
                account_id=None,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                logger=mock.MagicMock(),
                resumable_source_manager=resumable_manager,
                api_version=STRIPE_API_VERSION_ACACIA,
                should_use_incremental_field=False,
            )
        )

    assert rows == []
    # No Stripe list endpoint should be hit for a webhook-only resource.
    mock_client.subscriptions.list.assert_not_called()
    mock_client.coupons.list.assert_not_called()


@pytest.mark.parametrize("endpoint", WEBHOOK_ONLY_ENDPOINTS)
def test_validate_credentials_skips_webhook_only_resource(endpoint):
    """Webhook-only resources have no list endpoint, so validation should short-circuit
    and not hit Stripe."""
    mock_client = mock.MagicMock()

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
        return_value=mock_client,
    ):
        result = validate_credentials("api_key", [endpoint])

    assert result is True
    # No list method should be called when validating a webhook-only resource.
    mock_client.coupons.list.assert_not_called()
    mock_client.subscriptions.list.assert_not_called()


def test_validate_credentials_basic_treats_403_as_success():
    """Basic mode is auth-only: a 403 on the probe means the key is valid but lacks that
    specific scope. Schema selection is responsible for per-endpoint scope reporting, so
    the wizard's connect step must not block on a missing scope here."""
    mock_client = mock.MagicMock()
    _mock_all_stripe_endpoints(mock_client)
    mock_client.customers.list = mock.MagicMock(side_effect=stripe_lib.PermissionError(message="Forbidden"))

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
        return_value=mock_client,
    ):
        result = validate_credentials("api_key")

    assert result is True


def test_validate_credentials_basic_unknown_error_raises_validation_error():
    """Network / schema / rate-limit failures on the basic probe must surface as
    StripeValidationError so the underlying message is shown, not silently swallowed."""
    mock_client = mock.MagicMock()
    _mock_all_stripe_endpoints(mock_client)
    mock_client.customers.list = mock.MagicMock(side_effect=RuntimeError("connection reset by peer"))

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
            return_value=mock_client,
        ),
        pytest.raises(StripeValidationError) as e,
    ):
        validate_credentials("api_key")

    assert "connection reset" in next(iter(e.value.errors.values()))


def test_validate_credentials_with_explicit_endpoint():
    """When the caller names one endpoint, only that endpoint is probed."""
    mock_client = mock.MagicMock()
    _mock_all_stripe_endpoints(mock_client)

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
        return_value=mock_client,
    ):
        result = validate_credentials("api_key", endpoints=[ACCOUNT_RESOURCE_NAME])

        assert result is True

        mock_client.accounts.list.assert_called_once_with(params={"limit": 1})
        mock_client.balance_transactions.list.assert_not_called()
        mock_client.charges.list.assert_not_called()
        mock_client.customers.list.assert_not_called()


def test_validate_credentials_basic_authentication_error_short_circuits():
    """An invalid API key (401) on the basic probe must raise StripeAuthenticationError
    so the user sees the right reason rather than a misleading permissions error."""
    mock_client = mock.MagicMock()
    _mock_all_stripe_endpoints(mock_client)
    mock_client.customers.list = mock.MagicMock(
        side_effect=stripe_lib.AuthenticationError(message="Invalid API Key provided: rk_live_***")
    )

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
            return_value=mock_client,
        ),
        pytest.raises(StripeAuthenticationError) as e,
    ):
        validate_credentials("api_key")

    assert "Invalid API Key" in str(e.value)


def test_validate_credentials_endpoint_list_authentication_error_short_circuits():
    """In endpoint-list mode, a 401 on any probe must abort the loop immediately —
    every other call will 401 the same way and we should not keep banging the API."""
    mock_client = mock.MagicMock()
    auth_error = stripe_lib.AuthenticationError(message="Invalid API Key provided: rk_live_***")
    mock_client.accounts.list = mock.MagicMock(side_effect=auth_error)
    mock_client.balance_transactions.list = mock.MagicMock()
    mock_client.charges.list = mock.MagicMock()

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
            return_value=mock_client,
        ),
        pytest.raises(StripeAuthenticationError) as e,
    ):
        validate_credentials(
            "api_key",
            endpoints=[ACCOUNT_RESOURCE_NAME, "BalanceTransaction", "Charge"],
        )

    assert "Invalid API Key" in str(e.value)
    mock_client.balance_transactions.list.assert_not_called()
    mock_client.charges.list.assert_not_called()


def test_validate_credentials_endpoint_list_permission_error_lists_only_403_resources():
    """403 on one requested endpoint must be reported as a per-resource permission gap,
    not poisoned by other unrelated successes."""
    mock_client = mock.MagicMock()
    _mock_all_stripe_endpoints(mock_client)
    mock_client.charges.list = mock.MagicMock(side_effect=stripe_lib.PermissionError(message="Forbidden"))

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
            return_value=mock_client,
        ),
        pytest.raises(StripePermissionError) as e,
    ):
        validate_credentials("api_key", endpoints=["Charge", "Customer", "Account"])

    assert list(e.value.missing_permissions.keys()) == ["Charge"]


def test_validate_credentials_endpoint_list_unknown_error_raises_validation_error():
    """Non-403 failures on a requested endpoint surface verbatim via StripeValidationError."""
    mock_client = mock.MagicMock()
    _mock_all_stripe_endpoints(mock_client)
    mock_client.charges.list = mock.MagicMock(side_effect=RuntimeError("connection reset by peer"))

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
            return_value=mock_client,
        ),
        pytest.raises(StripeValidationError) as e,
    ):
        validate_credentials("api_key", endpoints=["Charge", "Customer"])

    assert list(e.value.errors.keys()) == ["Charge"]
    assert "connection reset" in e.value.errors["Charge"]
    assert e.value.missing_permissions == {}


def test_validate_credentials_endpoint_list_mixed_403_and_unknown_raises_validation_error_with_both():
    """Validation errors win (higher-severity) but carry collected 403s along."""
    mock_client = mock.MagicMock()
    _mock_all_stripe_endpoints(mock_client)
    mock_client.charges.list = mock.MagicMock(side_effect=RuntimeError("connection reset"))
    mock_client.subscriptions.list = mock.MagicMock(side_effect=stripe_lib.PermissionError(message="Forbidden"))

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
            return_value=mock_client,
        ),
        pytest.raises(StripeValidationError) as e,
    ):
        validate_credentials("api_key", endpoints=["Charge", "Subscription", "Customer"])

    assert list(e.value.errors.keys()) == ["Charge"]
    assert list(e.value.missing_permissions.keys()) == ["Subscription"]


@pytest.mark.parametrize(
    "nested_table_name",
    [CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME, CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME],
)
def test_validate_credentials_nested_resource_validates_via_parent(nested_table_name):
    """Nested resources can't be listed without a parent customer ID. Validating them
    must proxy to the Customer endpoint instead of raising a fake "<resource> does not exist"
    error — which used to surface as "Stripe credentials lack permissions for CustomerPaymentMethod"
    every time the user toggled the sync method on a nested table."""
    mock_client = mock.MagicMock()
    mock_client.customers.list = mock.MagicMock()

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
        return_value=mock_client,
    ):
        result = validate_credentials("api_key", endpoints=[nested_table_name])

    assert result is True
    # The parent's list endpoint is the one we actually call.
    mock_client.customers.list.assert_called_once_with(params={"limit": 1})


@pytest.mark.parametrize(
    "nested_table_name",
    [CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME, CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME],
)
def test_validate_credentials_nested_resource_surfaces_parent_permission_error(nested_table_name):
    """If the parent (Customer) scope is missing, the error must name both the nested table
    the user toggled and the parent that actually gates the permission — `Nested (Parent)` —
    so the message is unambiguous about which Stripe scope to grant."""
    mock_client = mock.MagicMock()
    mock_client.customers.list = mock.MagicMock(side_effect=stripe_lib.PermissionError(message="Forbidden"))

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
            return_value=mock_client,
        ),
        pytest.raises(StripePermissionError) as e,
    ):
        validate_credentials("api_key", endpoints=[nested_table_name])

    assert list(e.value.missing_permissions.keys()) == [f"{nested_table_name} (Customer)"]


def test_clean_stripe_error_message_collapses_redacted_key():
    """Stripe's permission errors quote the restricted key with ~80 redacted middle chars
    (`rk_live_***********...***********gbeftZ`). The unedited message is too long for a
    toast — collapse the asterisk run while keeping the visible prefix/suffix that lets
    users identify which key was used."""
    raw = (
        "Request req_DzMMiyPa4cynLi: The provided key 'rk_live_"
        + ("*" * 80)
        + "gbeftZ' does not have the required permissions for this endpoint on account "
        + "'acct_1HIMDDEuIatRXSdz'. Having the 'rak_payment_method_read' permission would "
        + "allow this request to continue."
    )

    cleaned = _clean_stripe_error_message(raw)

    assert "*" * 80 not in cleaned
    assert "***" in cleaned  # we keep a short marker
    assert "rk_live_***gbeftZ" in cleaned
    # Critically, the actionable detail must survive the cleanup.
    assert "rak_payment_method_read" in cleaned


def test_clean_stripe_error_message_passthrough_when_no_redaction():
    """No redacted run in the message → return unchanged."""
    msg = "Request req_xxx: Some non-permission error without redaction."
    assert _clean_stripe_error_message(msg) == msg


def test_subscription_expand_encodes_as_array_not_object():
    """End-to-end encoding regression: the discount expand must reach Stripe as
    expand[0]=…&expand[1]=… (a real array), not expand[][0]=… which Stripe parses as an
    array-of-one-object and rejects with "Invalid string: {...}". The mock-based test above
    can't catch this because it intercepts above the SDK's query-string encoding."""
    captured: dict[str, str] = {}

    class RecordingHTTPClient(HTTPClient):
        name = "recording"

        def request_with_retries(self, method, url, headers, post_data=None, max_network_retries=None, *, _usage=None):
            captured["url"] = url
            body = '{"object":"list","data":[],"has_more":false,"url":"/v1/subscriptions"}'
            return body, 200, {"request-id": "req_test"}

        def request_stream_with_retries(
            self, method, url, headers, post_data=None, max_network_retries=None, *, _usage=None
        ):
            raise NotImplementedError

    client = stripe_lib.StripeClient("sk_test_x", http_client=RecordingHTTPClient())
    resources = _build_resources(client)
    subscription = resources[SUBSCRIPTION_RESOURCE_NAME]
    subscription.method(params=subscription.params)

    url = captured["url"]
    assert "expand[0]=data.discounts" in url
    assert "expand[1]=data.items.data.discounts" in url
    # The doubled-bracket form is the bug — Stripe rejects it.
    assert "expand[][0]" not in url


@pytest.mark.parametrize(
    "error_factory",
    [
        # InvalidRequestError requires a positional `param` — the regression that broke imports.
        lambda msg: stripe_lib.InvalidRequestError(msg, "expand[]"),
        lambda msg: stripe_lib.PermissionError(msg),
        lambda msg: stripe_lib.AuthenticationError(msg),
        lambda msg: stripe_lib.APIConnectionError(msg),
    ],
)
def test_call_stripe_cleans_message_and_preserves_error_type(error_factory):
    """_call_stripe must re-raise the same StripeError subclass with a cleaned message.
    Reconstructing via `type(e)(message=...)` broke for subclasses with extra required
    args (e.g. InvalidRequestError's `param`), so we mutate the message in place instead."""
    raw = "The provided key 'rk_live_" + ("*" * 80) + "gbeftZ' is invalid"

    def boom():
        raise error_factory(raw)

    with pytest.raises(stripe_lib.StripeError) as exc_info:
        _call_stripe(boom)

    raised = exc_info.value
    assert type(raised) is type(error_factory(raw))
    assert "*" * 80 not in str(raised)
    assert "rk_live_***gbeftZ" in str(raised)


def test_call_stripe_passes_through_successful_result():
    assert _call_stripe(lambda x: x + 1, 41) == 42


@parameterized.expand(
    [
        # (status_code, num_retries, max_network_retries, expected)
        # 429 is now retried while budget remains — the SDK omits this on its own.
        ("rate_limit_retried", 429, 0, 2, True),
        # ...but stops once the retry budget is exhausted, so we don't loop forever.
        ("rate_limit_budget_exhausted", 429, 2, 2, False),
        # 5xx keeps the SDK's built-in retry behavior.
        ("server_error_still_retried", 503, 0, 2, True),
        # Non-retryable 4xx (e.g. a bad request) must NOT be retried.
        ("bad_request_not_retried", 400, 0, 2, False),
    ]
)
def test_stripe_http_client_retries_rate_limits(_name, status_code, num_retries, max_network_retries, expected):
    """Stripe's SDK never retries 429s, so a transient rate limit during pagination would crash
    the import activity. Our client opts 429 into the SDK's Retry-After-aware backoff while
    preserving the base behavior for 5xx and leaving non-retryable 4xx alone."""
    client = _tracked_stripe_http_client()
    response: tuple[bytes, int, Mapping[str, str]] = (b"", status_code, {})

    assert (
        client._should_retry(response, None, num_retries=num_retries, max_network_retries=max_network_retries)
        is expected
    )


@parameterized.expand(
    [
        # (cause, num_retries, max_network_retries, expected)
        # A connection reset mid-response body surfaces as a ChunkedEncodingError, which Stripe
        # wraps in a non-retryable APIConnectionError — we retry it while budget remains.
        ("connection_reset_retried", requests.exceptions.ChunkedEncodingError("Connection broken"), 0, 2, True),
        # ...but stops once the retry budget is exhausted, so we don't loop forever.
        (
            "connection_reset_budget_exhausted",
            requests.exceptions.ChunkedEncodingError("Connection broken"),
            2,
            2,
            False,
        ),
        # An SSL error is deliberately non-retryable in the SDK — we must not start retrying it.
        ("ssl_error_not_retried", requests.exceptions.SSLError("bad cert"), 0, 2, False),
        # An APIConnectionError with no wrapped cause has nothing to identify as a reset.
        ("no_cause_not_retried", None, 0, 2, False),
    ]
)
def test_stripe_http_client_retries_connection_reset(_name, cause, num_retries, max_network_retries, expected):
    """A connection reset while paging surfaces from requests as a ChunkedEncodingError, which the
    SDK declines to retry (only Timeout/ConnectionError are retryable) so it crashes the import.
    Our client retries that transient reset in-process while leaving SSL errors non-retryable."""
    client = _tracked_stripe_http_client()
    # response=None is how the SDK signals a connection error rather than an HTTP response.
    error = stripe_lib.APIConnectionError("Unexpected error communicating with Stripe.")
    if cause is not None:
        error.__cause__ = cause

    assert (
        client._should_retry(None, error, num_retries=num_retries, max_network_retries=max_network_retries) is expected
    )


def test_validate_credentials_nested_resources_have_registered_parents():
    """Invariant: every StripeNestedResource's `parent_name` must point at a key that is
    also registered as a top-level StripeResource in _build_resources. validate_credentials
    does a direct dict lookup on parent_name, so a miss would crash rather than render a
    useful error. Catch the misconfiguration here in CI rather than at runtime.

    Important: this test does NOT compare method identity. Stripe's SDK exposes endpoints
    via property descriptors that return a fresh bound method on every attribute access
    (`id(client.customers.list) == id(client.customers.list)` is False). MagicMock caches
    attribute access and made identity checks falsely pass — so the linkage is carried
    explicitly via the `parent_name` string instead.
    """
    mock_client = mock.MagicMock()
    resources = _build_resources(mock_client, logger=None)

    for name, resource in resources.items():
        if isinstance(resource, StripeNestedResource):
            assert resource.parent_name, f"Nested resource {name!r} must declare a parent_name."
            parent_entry = resources.get(resource.parent_name)
            assert isinstance(parent_entry, StripeResource), (
                f"Nested resource {name!r} declares parent_name={resource.parent_name!r}, but no "
                f"top-level StripeResource with that name is registered in _build_resources. "
                f"validate_credentials would crash trying to resolve it."
            )


def test_validate_credentials_with_missing_table_name():
    mock_client = mock.MagicMock()
    _mock_all_stripe_endpoints(mock_client)

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
            return_value=mock_client,
        ),
        pytest.raises(StripePermissionError) as e,
    ):
        validate_credentials("api_key", endpoints=["bad_table"])

    # No endpoint should be called
    mock_client.accounts.list.assert_not_called()
    mock_client.balance_transactions.list.assert_not_called()
    mock_client.charges.list.assert_not_called()
    mock_client.customers.list.assert_not_called()
    mock_client.disputes.list.assert_not_called()
    mock_client.invoice_items.list.assert_not_called()
    mock_client.invoices.list.assert_not_called()
    mock_client.payouts.list.assert_not_called()
    mock_client.prices.list.assert_not_called()
    mock_client.products.list.assert_not_called()
    mock_client.subscriptions.list.assert_not_called()
    mock_client.refunds.list.assert_not_called()
    mock_client.credit_notes.list.assert_not_called()
    mock_client.coupons.list.assert_not_called()

    assert "bad_table" in str(e)


def test_validate_credentials_endpoint_list_oauth_skips_account():
    """accounts.list requires Connect platform access — OAuth connected-account tokens
    can't call it. When the caller asks for Account explicitly under OAuth, the probe
    must be silently dropped rather than producing a confusing 403."""
    mock_client = mock.MagicMock()
    _mock_all_stripe_endpoints(mock_client)

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
        return_value=mock_client,
    ):
        result = validate_credentials(
            "oauth_token",
            endpoints=[ACCOUNT_RESOURCE_NAME, "Customer", "Charge"],
            auth_method="oauth",
        )

        assert result is True

        # accounts.list must NOT be called for OAuth tokens
        mock_client.accounts.list.assert_not_called()
        # Other listed endpoints still get probed
        mock_client.customers.list.assert_called_once_with(params={"limit": 1})
        mock_client.charges.list.assert_called_once_with(params={"limit": 1})


def test_check_endpoint_permissions_returns_per_endpoint_status():
    """check_endpoint_permissions feeds the schema-selection UI. It must report each
    endpoint's status individually instead of short-circuiting on the first denial."""
    mock_client = mock.MagicMock()
    _mock_all_stripe_endpoints(mock_client)
    mock_client.charges.list = mock.MagicMock(side_effect=stripe_lib.PermissionError(message="Forbidden"))
    mock_client.subscriptions.list = mock.MagicMock(side_effect=RuntimeError("connection reset"))

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
        return_value=mock_client,
    ):
        results = check_endpoint_permissions("api_key", endpoints=["Customer", "Charge", "Subscription"])

    assert results["Customer"] is None
    assert results["Charge"] is not None and "Forbidden" in results["Charge"]
    assert results["Subscription"] is not None and "connection reset" in results["Subscription"]


def test_check_endpoint_permissions_raises_on_401():
    """A bad key (401) must short-circuit — every probe will fail the same way and the
    UI needs to surface a credential failure rather than render thirteen denial rows."""
    mock_client = mock.MagicMock()
    _mock_all_stripe_endpoints(mock_client)
    mock_client.customers.list = mock.MagicMock(
        side_effect=stripe_lib.AuthenticationError(message="Invalid API Key provided: rk_live_***")
    )

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
            return_value=mock_client,
        ),
        pytest.raises(StripeAuthenticationError),
    ):
        check_endpoint_permissions("api_key", endpoints=["Customer", "Charge"])


def test_check_endpoint_permissions_oauth_marks_account_as_unavailable():
    """OAuth tokens can't reach accounts.list. Surface a clear, non-403 reason so the UI
    can render the right message instead of leaving the user wondering about scopes."""
    mock_client = mock.MagicMock()
    _mock_all_stripe_endpoints(mock_client)

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
        return_value=mock_client,
    ):
        results = check_endpoint_permissions(
            "oauth_token", endpoints=[ACCOUNT_RESOURCE_NAME, "Customer"], auth_method="oauth"
        )

    account_reason = results[ACCOUNT_RESOURCE_NAME]
    assert account_reason is not None
    assert "OAuth" in account_reason
    assert results["Customer"] is None
    mock_client.accounts.list.assert_not_called()


def test_validate_credentials_oauth_account_endpoint_returns_true():
    mock_client = mock.MagicMock()

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
        return_value=mock_client,
    ):
        result = validate_credentials("oauth_token", endpoints=[ACCOUNT_RESOURCE_NAME], auth_method="oauth")

        assert result is True

        # No Stripe API calls should be made — Account is skipped for OAuth before any checks run
        mock_client.accounts.list.assert_not_called()
        mock_client.balance_transactions.list.assert_not_called()


class TestGetApiKey:
    @pytest.fixture
    def stripe_source(self):
        return StripeSource()

    @pytest.fixture
    def stripe_integration(self, team):
        return Integration.objects.create(
            team=team,
            kind="stripe",
            config={"account_name": "Test Business (acct_123)"},
            sensitive_config={"access_token": "sk_live_oauth_token"},
            integration_id="acct_123",
        )

    def test_api_key_selection_returns_key(self, stripe_source):
        config = StripeSourceConfig.from_dict(
            {"auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"}}
        )
        assert stripe_source._get_api_key(config, team_id=1) == "sk_test_123"

    def test_api_key_selection_raises_when_key_missing(self, stripe_source):
        config = StripeSourceConfig.from_dict({"auth_method": {"selection": "api_key"}})
        with pytest.raises(ValueError, match="Missing Stripe API key"):
            stripe_source._get_api_key(config, team_id=1)

    @pytest.mark.django_db
    def test_oauth_selection_returns_access_token(self, stripe_source, team, stripe_integration):
        config = StripeSourceConfig.from_dict(
            {"auth_method": {"selection": "oauth", "stripe_integration_id": stripe_integration.id}}
        )
        assert stripe_source._get_api_key(config, team.pk) == "sk_live_oauth_token"

    def test_oauth_selection_raises_when_integration_id_missing(self, stripe_source):
        config = StripeSourceConfig.from_dict({"auth_method": {"selection": "oauth"}})
        with pytest.raises(ValueError, match="Missing Stripe integration ID"):
            stripe_source._get_api_key(config, team_id=1)

    @pytest.mark.django_db
    def test_oauth_selection_raises_when_integration_not_found(self, stripe_source, team):
        config = StripeSourceConfig.from_dict({"auth_method": {"selection": "oauth", "stripe_integration_id": 99999}})
        with pytest.raises(ValueError, match="Integration not found"):
            stripe_source._get_api_key(config, team.pk)


class TestGetEndpointPermissions:
    """`get_endpoint_permissions` feeds the UI — it must never leak unexpected exception details."""

    @pytest.fixture
    def stripe_source(self):
        return StripeSource()

    def test_value_error_from_get_api_key_surfaces_message(self, stripe_source):
        config = StripeSourceConfig.from_dict({"auth_method": {"selection": "api_key"}})
        result = stripe_source.get_endpoint_permissions(config, team_id=1, endpoints=["Customer", "Charge"])
        # Curated ValueError messages from _get_api_key are safe to render verbatim.
        assert result == {"Customer": "Missing Stripe API key", "Charge": "Missing Stripe API key"}

    def test_unexpected_exception_renders_generic_reason(self, stripe_source):
        config = StripeSourceConfig.from_dict(
            {"auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"}}
        )
        with mock.patch.object(stripe_source, "_get_api_key", side_effect=RuntimeError("internal token=secret123")):
            result = stripe_source.get_endpoint_permissions(config, team_id=1, endpoints=["Customer"])
        # Generic message — never leak the raw exception body to the UI.
        assert result == {"Customer": "Stripe credentials are not available"}
        assert "secret123" not in result["Customer"]


class TestUpdateWebhookEvents:
    """`update_webhook_events` reconciles a Stripe endpoint's enabled_events with the desired set."""

    WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/dwh/123"

    def _mock_client_with_endpoint(self, *, url, enabled_events):
        endpoint = mock.MagicMock()
        endpoint.id = "we_123"
        endpoint.url = url
        endpoint.enabled_events = enabled_events

        mock_client = mock.MagicMock()
        mock_client.webhook_endpoints.list.return_value.auto_paging_iter.return_value = [endpoint]
        return mock_client, endpoint

    def test_drift_calls_update_with_merged_set(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe import update_webhook_events

        mock_client, endpoint = self._mock_client_with_endpoint(
            url=self.WEBHOOK_URL, enabled_events=["charge.captured"]
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
            return_value=mock_client,
        ):
            result = update_webhook_events("rk_test", None, self.WEBHOOK_URL, ["charge.captured", "customer.created"])

        assert result.success
        mock_client.webhook_endpoints.update.assert_called_once()
        args, kwargs = mock_client.webhook_endpoints.update.call_args
        # Stripe SDK signature is update(endpoint_id, params={...}) — endpoint id positional,
        # events nested under `params`. Asserting this exact shape guards against passing
        # enabled_events as a bare kwarg (a silent TypeError that never actually updates).
        assert args[0] == "we_123"
        enabled = kwargs["params"]["enabled_events"]
        assert "customer.created" in enabled
        # Pre-existing events the user had are preserved.
        assert "charge.captured" in enabled

    @parameterized.expand(
        [
            # endpoint already carries everything desired
            ("already in sync", WEBHOOK_URL, ["charge.captured", "customer.created"]),
            # endpoint listens to all events
            ("wildcard endpoint", WEBHOOK_URL, ["*"]),
            # no endpoint matches our url
            ("no matching endpoint", "https://other.example.com", ["charge.captured"]),
        ]
    )
    def test_does_not_write_when_no_drift(self, _name, endpoint_url, enabled_events):
        from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe import update_webhook_events

        mock_client, _ = self._mock_client_with_endpoint(url=endpoint_url, enabled_events=enabled_events)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
            return_value=mock_client,
        ):
            result = update_webhook_events("rk_test", None, self.WEBHOOK_URL, ["charge.captured", "customer.created"])

        assert result.success
        mock_client.webhook_endpoints.update.assert_not_called()

    def test_permission_error_returns_actionable_failure_without_raising(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe import update_webhook_events

        mock_client, _ = self._mock_client_with_endpoint(url=self.WEBHOOK_URL, enabled_events=["charge.captured"])
        mock_client.webhook_endpoints.update.side_effect = stripe_lib.PermissionError(message="Forbidden")

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
            return_value=mock_client,
        ):
            result = update_webhook_events("rk_test", None, self.WEBHOOK_URL, ["customer.created"])

        assert result.success is False
        assert result.error is not None
        assert "Write" in result.error
        assert "customer.created" in result.error

    def test_empty_desired_is_noop(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe import update_webhook_events

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient"
        ) as mock_client_cls:
            result = update_webhook_events("rk_test", None, "https://x", [])

        assert result.success
        mock_client_cls.assert_not_called()


class TestAllKnownWebhookEvents:
    """Guards the event-derivation the create + reconcile paths both depend on."""

    def test_only_emits_events_under_mapped_prefixes(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
            RESOURCE_TO_STRIPE_WEBHOOK_EVENT,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe import (
            _all_known_webhook_events,
        )

        events = _all_known_webhook_events()

        assert len(events) > 0
        # Never subscribe to an event outside a mapped prefix — that's noise we'd drop anyway.
        prefixes = set(RESOURCE_TO_STRIPE_WEBHOOK_EVENT.values())
        for event in events:
            assert any(event.startswith(f"{p}.") for p in prefixes), f"unmapped event leaked in: {event}"

    def test_includes_revenue_critical_resource_events(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe import (
            _all_known_webhook_events,
        )

        events = set(_all_known_webhook_events())
        # The resources Revenue analytics depends on must always be covered. Disputes ride in via
        # `charge.dispute.*` (the `dispute` prefix itself yields nothing — events are charge-scoped).
        for expected in ["charge.captured", "customer.created", "invoice.created", "customer.subscription.created"]:
            assert expected in events, f"missing critical event: {expected}"
        assert any(e.startswith("charge.dispute.") for e in events)


class TestCreateWebhook:
    def test_creates_endpoint_with_full_known_event_set(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe import (
            _all_known_webhook_events,
            create_webhook,
        )

        endpoint = mock.MagicMock()
        endpoint.secret = "whsec_abc"
        mock_client = mock.MagicMock()
        mock_client.webhook_endpoints.create.return_value = endpoint

        url = "https://webhooks.us.posthog.com/public/webhooks/dwh/123"
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
            return_value=mock_client,
        ):
            result = create_webhook("rk_test", None, url)

        assert result.success
        assert result.extra_inputs == {"signing_secret": "whsec_abc"}
        _, kwargs = mock_client.webhook_endpoints.create.call_args
        params = kwargs["params"]
        assert params["url"] == url
        # Refactor guard: create must still register exactly the full known event set.
        assert params["enabled_events"] == _all_known_webhook_events()

    def test_permission_error_returns_actionable_failure(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe import create_webhook

        mock_client = mock.MagicMock()
        mock_client.webhook_endpoints.create.side_effect = Exception("403 Forbidden")

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
            return_value=mock_client,
        ):
            result = create_webhook("rk_test", None, "https://x")

        assert result.success is False
        assert result.error is not None
        assert "permission" in result.error.lower()

    @parameterized.expand(
        [
            # (name, exception)
            ("message", Exception("The provided key does not have access to account 'acct_123'.")),
            ("revoked", Exception("Application access may have been revoked.")),
            ("account_invalid_code", _exception_with_code("403 Forbidden", "account_invalid")),
        ]
    )
    def test_account_access_error_points_to_manual_setup(self, _name, exception):
        from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe import create_webhook

        mock_client = mock.MagicMock()
        mock_client.webhook_endpoints.create.side_effect = exception

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.StripeClient",
            return_value=mock_client,
        ):
            result = create_webhook("rk_test", "acct_123", "https://x")

        assert result.success is False
        assert result.error is not None
        # Account-access errors must surface the actionable account guidance, never the raw fallback
        # or the generic webhook-scope permission message.
        assert "account" in result.error.lower()
        assert "Failed to create webhook automatically" not in result.error
        assert "permission to create webhooks" not in result.error
