from types import SimpleNamespace

import pytest
from unittest import mock

from django.db import OperationalError

import grpc
from google.ads.googleads.errors import GoogleAdsException
from google.ads.googleads.v23.enums import types as ga_enums
from google.ads.googleads.v23.errors.types.errors import ErrorCode, GoogleAdsError, GoogleAdsFailure
from google.ads.googleads.v23.errors.types.request_error import RequestErrorEnum
from google.api_core import exceptions as google_api_exceptions
from google.auth import exceptions as google_auth_exceptions

from posthog.schema import SourceFieldOauthConfig

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GoogleAdsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.configs import (
    GoogleAdsResumeConfig,
    clean_customer_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads import (
    GoogleAdsColumn,
    GoogleAdsTable,
    _get_integration,
    _is_rejected_page_token_error,
    _is_stale_page_token_error,
    _is_transient_client_init_error,
    _is_transient_grpc_error,
    _load_client_with_transient_retry,
    _search_as_arrow_tables,
    _search_fields_with_transient_retry,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.schemas import RESOURCE_SCHEMAS
from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.source import GoogleAdsSource
from products.warehouse_sources.backend.types import IncrementalFieldType

_CUSTOMER_ID_ERROR = "valid Google Ads customer ID"
_MANAGER_ID_ERROR = "valid Google Ads manager customer ID"


def test_get_source_config_oauth_field_declares_required_scope():
    oauth_field = next(
        field for field in GoogleAdsSource().get_source_config.fields if field.name == "google_ads_integration_id"
    )
    assert isinstance(oauth_field, SourceFieldOauthConfig)
    assert oauth_field.kind == "google-ads"
    assert oauth_field.requiredScopes == "https://www.googleapis.com/auth/adwords"


class TestCleanCustomerId:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("123-456-7890", "1234567890"),
            ("1234567890", "1234567890"),
            ("  123-456-7890  ", "1234567890"),
            ("123 456 7890", "1234567890"),
            ("", ""),
            (None, None),
        ],
    )
    def test_strips_to_bare_digits(self, raw, expected):
        assert clean_customer_id(raw) == expected


class TestGoogleAdsValidateConfig:
    def setup_method(self):
        self.source = GoogleAdsSource()

    def _customer_id_errors(self, job_inputs: dict) -> list[str]:
        _, errors = self.source.validate_config(job_inputs)
        return [e for e in errors if _CUSTOMER_ID_ERROR in e]

    def _manager_id_errors(self, job_inputs: dict) -> list[str]:
        _, errors = self.source.validate_config(job_inputs)
        return [e for e in errors if _MANAGER_ID_ERROR in e]

    @pytest.mark.parametrize(
        "customer_id",
        ["123-456-7890", "1234567890", "123 456 7890", "  123-456-7890  "],
    )
    def test_accepts_any_common_customer_id_format(self, customer_id):
        assert self._customer_id_errors({"customer_id": customer_id}) == []

    @pytest.mark.parametrize(
        "customer_id",
        ["12345", "123-456-789", "abcd", "123-456-78901"],
    )
    def test_rejects_invalid_customer_id(self, customer_id):
        assert len(self._customer_id_errors({"customer_id": customer_id})) == 1

    @pytest.mark.parametrize(
        "mcc_client_id",
        ["123-456-7890", "1234567890", "123 456 7890", "  123-456-7890  "],
    )
    def test_accepts_any_common_manager_customer_id_format(self, mcc_client_id):
        job_inputs = {
            "customer_id": "1234567890",
            "is_mcc_account": {"enabled": True, "mcc_client_id": mcc_client_id},
        }
        assert self._manager_id_errors(job_inputs) == []

    def test_rejects_invalid_manager_customer_id(self):
        job_inputs = {
            "customer_id": "1234567890",
            "is_mcc_account": {"enabled": True, "mcc_client_id": "123"},
        }
        assert len(self._manager_id_errors(job_inputs)) == 1

    @pytest.mark.parametrize("is_mcc_account", [False, True, None])
    def test_non_dict_is_mcc_account_does_not_crash(self, is_mcc_account):
        # API callers may send is_mcc_account as a plain bool instead of the switch-group dict;
        # validate_config must not crash trying to read `.get("enabled")` off it.
        job_inputs = {"customer_id": "1234567890", "is_mcc_account": is_mcc_account}
        assert self._manager_id_errors(job_inputs) == []


class TestGoogleAdsNonRetryableErrors:
    def setup_method(self):
        self.source = GoogleAdsSource()
        self.non_retryable = self.source.get_non_retryable_errors()

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Real RefreshError string observed in production when the refresh
            # token has been revoked / expired — reported by `str(e)` on
            # google.auth.exceptions.RefreshError.
            "('invalid_grant: Bad Request', {'error': 'invalid_grant', 'error_description': 'Bad Request'})",
            "('invalid_grant: Token has been expired or revoked.', {'error': 'invalid_grant', 'error_description': 'Token has been expired or revoked.'})",
            "('invalid_grant: Invalid grant: account not found', {'error': 'invalid_grant', 'error_description': 'Invalid grant: account not found'})",
        ],
    )
    def test_invalid_grant_is_non_retryable(self, error_msg):
        assert any(pattern in error_msg for pattern in self.non_retryable), (
            f"RefreshError message {error_msg!r} did not match any non-retryable pattern"
        )

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Real RefreshError strings observed in production when a Google Workspace
            # admin has restricted third-party API access for the app. Reported by
            # `str(e)` on google.auth.exceptions.RefreshError.
            (
                "('access_not_configured: Access to your account data (which may include HIPAA and PHI data) is "
                "restricted by policies within your organization. Please contact the administrator of your "
                "organization for more information regarding API access from third-party applications.', "
                "{'error': 'access_not_configured', 'error_description': 'Access to your account data ...'})"
            ),
            (
                "('access_not_configured: You can't access this app until an admin at your institution reviews "
                "and configures access for it. If you need access to this app,', {'error': 'access_not_configured', "
                "'error_description': 'You can't access this app ...'})"
            ),
        ],
    )
    def test_access_not_configured_is_non_retryable(self, error_msg):
        assert any(pattern in error_msg for pattern in self.non_retryable), (
            f"RefreshError message {error_msg!r} did not match any non-retryable pattern"
        )

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Observed in production: requesting metrics against a manager (MCC) account.
            (
                "errors {\n  error_code {\n    query_error: REQUESTED_METRICS_FOR_MANAGER\n  }\n  "
                'message: "Metrics cannot be requested for a manager account. To retrieve metrics, '
                'issue separate requests against each client account under the manager account."\n}\n'
            ),
            # Other Google Ads specific failures that should stop retrying.
            "PERMISSION_DENIED: The caller does not have permission",
            "UNAUTHENTICATED: Request had invalid authentication credentials",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT: Request had insufficient authentication scopes",
            "Customer: Account has been deleted",
            "INVALID_CUSTOMER_ID: Customer ID is not valid",
        ],
    )
    def test_permanent_auth_errors_are_non_retryable(self, error_msg):
        is_non_retryable = any(pattern in error_msg for pattern in self.non_retryable.keys())
        assert is_non_retryable, f"Expected error to be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # `str(Integration.DoesNotExist)` as raised by `google_ads_client` during a sync when
            # the OAuth integration row has been deleted/disconnected.
            "Integration matching query does not exist.",
        ],
    )
    def test_missing_integration_is_non_retryable(self, error_msg):
        is_non_retryable = any(pattern in error_msg for pattern in self.non_retryable.keys())
        assert is_non_retryable, f"Expected error to be non-retryable: {error_msg}"

    def test_missing_integration_has_friendly_message(self):
        friendly = self.non_retryable["Integration matching query does not exist"]
        assert friendly is not None
        assert "reconnect" in friendly.lower()

    @pytest.mark.parametrize(
        "error_msg",
        [
            # `str(google.api_core.exceptions.Unauthenticated)` as it propagates from
            # `GoogleAdsService.search` — gapic wraps the transport-level UNAUTHENTICATED as
            # "401 {message}", so it carries the human message but not the bare status token.
            (
                "401 Request is missing required authentication credential. Expected OAuth 2 access "
                "token, login cookie or other valid authentication credential. See "
                "https://developers.google.com/identity/sign-in/web/devconsole-project."
            ),
        ],
    )
    def test_missing_auth_credential_is_non_retryable(self, error_msg):
        is_non_retryable = any(pattern in error_msg for pattern in self.non_retryable.keys())
        assert is_non_retryable, f"Expected error to be non-retryable: {error_msg}"

    def test_missing_auth_credential_has_friendly_message(self):
        friendly = self.non_retryable["Request is missing required authentication credential"]
        assert friendly is not None
        assert "reconnect" in friendly.lower()

    def test_other_model_does_not_exist_is_not_swallowed(self):
        # The pattern is model-specific so an unrelated model's DoesNotExist — which may be a real
        # bug — is not silently treated as non-retryable.
        error_msg = "ExternalDataSchema matching query does not exist."
        assert not any(pattern in error_msg for pattern in self.non_retryable.keys())

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Transient network/infrastructure errors should still be retried.
            "DeadlineExceeded: 504 Deadline Exceeded",
            "UNAVAILABLE: The service is currently unavailable",
            "ConnectionError: Connection reset by peer",
            "INTERNAL: Internal server error",
            # A RefreshError wrapping a transient 502 from Google's token endpoint shares the
            # same error-tracking group as access_not_configured but must remain retryable.
            "('<!DOCTYPE html><title>Error 502 (Server Error)!!1</title>', None)",
        ],
    )
    def test_transient_errors_are_retryable(self, error_msg):
        is_non_retryable = any(pattern in error_msg for pattern in self.non_retryable.keys())
        assert not is_non_retryable, f"Expected error to be retryable: {error_msg}"

    @pytest.mark.parametrize(
        "pattern",
        [
            "PERMISSION_DENIED",
            "UNAUTHENTICATED",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
            "Account has been deleted",
            "INVALID_CUSTOMER_ID",
            "REQUESTED_METRICS_FOR_MANAGER",
            "invalid_grant",
            "access_not_configured",
            "Request is missing required authentication credential",
        ],
    )
    def test_documented_patterns_present(self, pattern):
        assert pattern in self.non_retryable

    def test_requested_metrics_for_manager_has_user_facing_message(self):
        message = self.non_retryable["REQUESTED_METRICS_FOR_MANAGER"]
        assert message is not None
        assert "manager" in message.lower()

    def test_invalid_grant_has_friendly_message(self):
        friendly = self.non_retryable["invalid_grant"]
        assert friendly is not None
        assert "reconnect" in friendly.lower()

    def test_access_not_configured_has_friendly_message(self):
        friendly = self.non_retryable["access_not_configured"]
        assert friendly is not None
        assert "admin" in friendly.lower()


class TestGoogleAdsLookbackDefault:
    _SCHEMAS_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads.get_schemas"

    def test_incremental_stats_schemas_get_default_lookback_dimensions_do_not(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.source import (
            GOOGLE_ADS_STATS_INCREMENTAL_LOOKBACK_SECONDS,
        )

        config = GoogleAdsSourceConfig(customer_id="1234567890", google_ads_integration_id=1)
        # get_schemas() queries the Google Ads API for selectable fields; the static incremental-field
        # map (real, not mocked) is what marks a table incremental, so stub the network call with one
        # stats table (has a segments.date filter) and one dimension table (does not).
        fake_tables = {
            "campaign_stats": SimpleNamespace(description=None, should_sync_default=True),
            "campaign": SimpleNamespace(description=None, should_sync_default=True),
        }
        with mock.patch(self._SCHEMAS_PATH, return_value=fake_tables):
            schemas = {s.name: s for s in GoogleAdsSource().get_schemas(config, team_id=1)}

        assert schemas["campaign_stats"].supports_incremental is True
        assert (
            schemas["campaign_stats"].default_incremental_lookback_seconds
            == GOOGLE_ADS_STATS_INCREMENTAL_LOOKBACK_SECONDS
        )
        assert schemas["campaign"].supports_incremental is False
        assert schemas["campaign"].default_incremental_lookback_seconds is None
        # The default must satisfy the 60-day cap the creation/update endpoints enforce, or creation
        # would reject it.
        assert 0 < GOOGLE_ADS_STATS_INCREMENTAL_LOOKBACK_SECONDS <= 5_184_000


class TestGrpcReceiveLimit:
    # The largest search page observed aborting syncs in production was ~103 MB; the gRPC
    # client must accept at least that much for the resource to sync at all.
    _SDK_DEFAULT = 64 * 1024 * 1024
    _LARGEST_OBSERVED_PAYLOAD = 103_046_535

    def test_raises_sdk_default_receive_limit(self):
        from google.ads.googleads import client as google_ads_client_module

        from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads import (
            GRPC_MAX_RECEIVE_MESSAGE_LENGTH,
            _ensure_grpc_receive_limit,
        )

        _ensure_grpc_receive_limit()

        options = dict(google_ads_client_module._GRPC_CHANNEL_OPTIONS)
        assert options["grpc.max_receive_message_length"] == GRPC_MAX_RECEIVE_MESSAGE_LENGTH
        assert GRPC_MAX_RECEIVE_MESSAGE_LENGTH > self._SDK_DEFAULT
        assert GRPC_MAX_RECEIVE_MESSAGE_LENGTH > self._LARGEST_OBSERVED_PAYLOAD

    def test_is_idempotent(self):
        from google.ads.googleads import client as google_ads_client_module

        from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads import (
            _ensure_grpc_receive_limit,
        )

        _ensure_grpc_receive_limit()
        _ensure_grpc_receive_limit()

        keys = [key for key, _ in google_ads_client_module._GRPC_CHANNEL_OPTIONS]
        assert keys.count("grpc.max_receive_message_length") == 1


class TestValidateCredentials:
    def test_missing_integration_does_not_exist_returns_reconnect_message(self):
        # `google_ads_client` calls `Integration.objects.get(...)`, which raises the typed
        # `Integration.DoesNotExist` when the OAuth connection row is gone. Surface an
        # actionable reconnect message instead of the raw ORM error.
        config = GoogleAdsSourceConfig(customer_id="1234567890", google_ads_integration_id=1)
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads.google_ads_client",
            side_effect=Integration.DoesNotExist(),
        ):
            ok, message = GoogleAdsSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert "no longer exists" in (message or "")
        assert "Integration matching query" not in (message or "")

    def test_missing_integration_string_match_returns_friendly_message(self):
        # The same condition can also surface as a generic exception whose message contains
        # the ORM "matching query does not exist" text; still surface a reconnect message.
        config = GoogleAdsSourceConfig(customer_id="123-456-7890", google_ads_integration_id=1)
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads.google_ads_client",
            side_effect=Exception("Integration matching query does not exist"),
        ):
            ok, message = GoogleAdsSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert "reconnect your Google Ads account" in (message or "")

    def test_transient_google_side_error_returns_retry_message(self):
        # A transient INTERNAL/UNAVAILABLE blip from Google stringifies as a raw gRPC status plus a
        # protobuf failure dump. Surface a clean retry prompt instead of leaking that to the wizard.
        config = GoogleAdsSourceConfig(customer_id="1234567890", google_ads_integration_id=1)
        client = mock.Mock()
        client.get_service.return_value.list_accessible_customers.side_effect = (
            google_api_exceptions.InternalServerError("500 Internal error encountered.")
        )
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads.google_ads_client",
            return_value=client,
        ):
            ok, message = GoogleAdsSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert "try again" in (message or "")
        assert "Internal error encountered" not in (message or "")


def _google_ads_exception(request_error: int) -> GoogleAdsException:
    failure = GoogleAdsFailure(
        errors=[
            GoogleAdsError(
                error_code=ErrorCode(request_error=request_error),
                message="Page token is invalid."
                if request_error == RequestErrorEnum.RequestError.INVALID_PAGE_TOKEN
                else "boom",
            )
        ]
    )
    return GoogleAdsException(error=None, call=None, failure=failure, request_id="req-1")


def _google_ads_exception_with_trigger(request_error: int, trigger_value: str) -> GoogleAdsException:
    # A failure whose request_error code the pinned library can't decode (surfaced as UNKNOWN /
    # "The error code is not in this version.") but whose trigger still echoes the offending value.
    error = GoogleAdsError(
        error_code=ErrorCode(request_error=request_error),
        message="The error code is not in this version.",
    )
    error.trigger.string_value = trigger_value
    failure = GoogleAdsFailure(errors=[error])
    return GoogleAdsException(error=None, call=None, failure=failure, request_id="req-1")


def _string_column(qualified_name: str) -> GoogleAdsColumn:
    return GoogleAdsColumn(
        qualified_name=qualified_name,
        data_type=ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.STRING,  # type: ignore[arg-type]
        is_repeatable=False,
        type_url="",
    )


def _single_row_table() -> GoogleAdsTable:
    return GoogleAdsTable(
        name="campaign",
        alias="campaign",
        columns=[_string_column("campaign.name")],
        parents=None,
        requires_filter=False,
        primary_key=[],
        should_sync_default=True,
        description=None,
    )


def _single_page() -> SimpleNamespace:
    return SimpleNamespace(
        field_mask=SimpleNamespace(paths=["campaign.name"]),
        results=[SimpleNamespace(campaign=SimpleNamespace(name="Acme"))],
        next_page_token="",
    )


class _FakeService:
    """Raises INVALID_PAGE_TOKEN for any non-empty token, succeeds on the first page."""

    def __init__(self, page: SimpleNamespace, error_on_token: GoogleAdsException | None = None):
        self.page = page
        self.error_on_token = error_on_token or _google_ads_exception(RequestErrorEnum.RequestError.INVALID_PAGE_TOKEN)
        self.calls: list[str] = []

    def search(self, request: dict):
        self.calls.append(request["page_token"])
        if request["page_token"]:
            raise self.error_on_token
        return SimpleNamespace(pages=iter([self.page]))


class _FakeResumableManager:
    def __init__(self, saved_token: str | None):
        self._saved = saved_token
        self.saved_states: list[str] = []

    def can_resume(self) -> bool:
        return self._saved is not None

    def load_state(self) -> GoogleAdsResumeConfig | None:
        return GoogleAdsResumeConfig(page_token=self._saved) if self._saved is not None else None

    def save_state(self, data: GoogleAdsResumeConfig) -> None:
        self.saved_states.append(data.page_token)


class TestStalePageTokenDetection:
    @pytest.mark.parametrize(
        "exc, expected",
        [
            (_google_ads_exception(RequestErrorEnum.RequestError.INVALID_PAGE_TOKEN), True),
            # Google returns a distinct EXPIRED_PAGE_TOKEN when a once-valid token aged out
            # between runs — the resumption recovery must treat it the same as INVALID_PAGE_TOKEN.
            (_google_ads_exception(RequestErrorEnum.RequestError.EXPIRED_PAGE_TOKEN), True),
            (_google_ads_exception(RequestErrorEnum.RequestError.RESOURCE_NAME_MISSING), False),
            # A non-``GoogleAdsException`` shape (no ``failure``) must not match.
            (SimpleNamespace(failure=None), False),
        ],
    )
    def test_is_stale_page_token_error(self, exc, expected):
        assert _is_stale_page_token_error(exc) is expected


class TestRejectedPageTokenDetection:
    @pytest.mark.parametrize(
        "exc, page_token, expected",
        [
            # Google rejected our token with a code the pinned library can't decode, but the
            # failure trigger echoes the exact token we sent — recognise it as a stale token.
            (
                _google_ads_exception_with_trigger(RequestErrorEnum.RequestError.UNKNOWN, "SAVED_TOKEN"),
                "SAVED_TOKEN",
                True,
            ),
            # A trigger naming some other value must not be mistaken for a rejected page token.
            (_google_ads_exception_with_trigger(RequestErrorEnum.RequestError.UNKNOWN, "other"), "SAVED_TOKEN", False),
            # An empty page token (first-page request) can never be the rejected value.
            (_google_ads_exception_with_trigger(RequestErrorEnum.RequestError.UNKNOWN, ""), "", False),
            # A non-``GoogleAdsException`` shape (no ``failure``) must not match.
            (SimpleNamespace(failure=None), "SAVED_TOKEN", False),
        ],
    )
    def test_is_rejected_page_token_error(self, exc, page_token, expected):
        assert _is_rejected_page_token_error(exc, page_token) is expected


class TestSearchPageTokenResumption:
    @pytest.mark.parametrize(
        "request_error",
        [
            RequestErrorEnum.RequestError.INVALID_PAGE_TOKEN,
            RequestErrorEnum.RequestError.EXPIRED_PAGE_TOKEN,
        ],
    )
    def test_restarts_pagination_when_saved_page_token_stale(self, request_error):
        service = _FakeService(_single_page(), error_on_token=_google_ads_exception(request_error))
        manager = _FakeResumableManager(saved_token="STALE_TOKEN")

        tables = list(
            _search_as_arrow_tables(
                service=service,  # type: ignore[arg-type]
                customer_id="1234567890",
                query="SELECT campaign.name FROM campaign",
                table=_single_row_table(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            )
        )

        # The stale token was tried, rejected, then pagination restarted from the first page.
        assert service.calls == ["STALE_TOKEN", ""]
        # The stale token is cleared from saved state so a later resume won't reuse it.
        assert manager.saved_states == [""]
        # Rows are still yielded — the data was never lost.
        assert [t.to_pylist() for t in tables] == [[{"campaign_name": "Acme"}]]

    def test_restarts_pagination_when_page_token_rejected_with_unrecognised_code(self):
        # Google rejected the saved token with a request_error code the pinned library can't
        # decode (UNKNOWN / "The error code is not in this version."), so the code-text match
        # misses it; the trigger echoing the token is the only stable signal to restart.
        service = _FakeService(
            _single_page(),
            error_on_token=_google_ads_exception_with_trigger(RequestErrorEnum.RequestError.UNKNOWN, "STALE_TOKEN"),
        )
        manager = _FakeResumableManager(saved_token="STALE_TOKEN")

        tables = list(
            _search_as_arrow_tables(
                service=service,  # type: ignore[arg-type]
                customer_id="1234567890",
                query="SELECT campaign.name FROM campaign",
                table=_single_row_table(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            )
        )

        assert service.calls == ["STALE_TOKEN", ""]
        assert manager.saved_states == [""]
        assert [t.to_pylist() for t in tables] == [[{"campaign_name": "Acme"}]]

    def test_other_google_ads_errors_propagate(self):
        service = _FakeService(
            _single_page(),
            error_on_token=_google_ads_exception(RequestErrorEnum.RequestError.RESOURCE_NAME_MISSING),
        )
        manager = _FakeResumableManager(saved_token="STALE_TOKEN")

        with pytest.raises(GoogleAdsException):
            list(
                _search_as_arrow_tables(
                    service=service,  # type: ignore[arg-type]
                    customer_id="1234567890",
                    query="SELECT campaign.name FROM campaign",
                    table=_single_row_table(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                )
            )

        # No restart attempt — the token was never reset.
        assert manager.saved_states == []

    def test_invalid_page_token_without_saved_state_does_not_loop(self):
        # Guards against an infinite restart loop: with no resumable token, an
        # INVALID_PAGE_TOKEN on the first (empty-token) request must propagate.
        always_failing = SimpleNamespace(
            calls=[],
        )

        def _always_raise(request: dict):
            always_failing.calls.append(request["page_token"])
            raise _google_ads_exception(RequestErrorEnum.RequestError.INVALID_PAGE_TOKEN)

        always_failing.search = _always_raise
        manager = _FakeResumableManager(saved_token=None)

        with pytest.raises(GoogleAdsException):
            list(
                _search_as_arrow_tables(
                    service=always_failing,  # type: ignore[arg-type]
                    customer_id="1234567890",
                    query="SELECT campaign.name FROM campaign",
                    table=_single_row_table(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                )
            )

        assert always_failing.calls == [""]
        assert manager.saved_states == []


_CLIENT_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads.GoogleAdsClient"
_SLEEP_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads.time.sleep"

# The HTML body Google's frontend returns for a transient 502 on the OAuth token endpoint, as it
# reaches `str()` on the resulting RefreshError. google-auth does not flag this status retryable.
_BAD_GATEWAY_TOKEN_ENDPOINT_BODY = (
    "<!DOCTYPE html>\n<html lang=en>\n  <title>Error 502 (Server Error)!!1</title>\n"
    "  <p>The server encountered a temporary error and could not complete your request."
)


class TestLoadClientTransientRetry:
    def test_retries_transport_error_then_succeeds(self):
        client = object()
        load = mock.Mock(
            side_effect=[
                google_auth_exceptions.TransportError("timed out"),
                google_auth_exceptions.TransportError("timed out"),
                client,
            ]
        )

        with mock.patch(_CLIENT_PATH) as ga_client, mock.patch(_SLEEP_PATH) as sleep:
            ga_client.load_from_dict = load
            result = _load_client_with_transient_retry({"refresh_token": "x"})

        assert result is client
        assert load.call_count == 3
        # Backoff grows per attempt per `min(2 * attempt, 30)`: 2s after the 1st failure, 4s after the 2nd.
        assert sleep.call_args_list == [mock.call(2), mock.call(4)]

    def test_retries_transient_refresh_error_then_succeeds(self):
        # A 502 from Google's token endpoint surfaces as a RefreshError (not TransportError) and
        # google-auth does not flag it retryable, but it's a transient server-side blip — ride it
        # out in-process rather than failing the whole import activity before a row is fetched.
        client = object()
        load = mock.Mock(
            side_effect=[
                google_auth_exceptions.RefreshError(_BAD_GATEWAY_TOKEN_ENDPOINT_BODY),
                client,
            ]
        )

        with mock.patch(_CLIENT_PATH) as ga_client, mock.patch(_SLEEP_PATH) as sleep:
            ga_client.load_from_dict = load
            result = _load_client_with_transient_retry({"refresh_token": "x"})

        assert result is client
        assert load.call_count == 2
        assert sleep.call_args_list == [mock.call(2)]

    def test_reraises_after_exhausting_attempts(self):
        load = mock.Mock(side_effect=google_auth_exceptions.TransportError("timed out"))

        with mock.patch(_CLIENT_PATH) as ga_client, mock.patch(_SLEEP_PATH) as sleep:
            ga_client.load_from_dict = load
            with pytest.raises(google_auth_exceptions.TransportError):
                _load_client_with_transient_retry({"refresh_token": "x"}, max_attempts=3)

        assert load.call_count == 3
        # One sleep fewer than attempts — no backoff after the final failure.
        assert sleep.call_args_list == [mock.call(2), mock.call(4)]

    @pytest.mark.parametrize(
        "error",
        [
            # A revoked/expired credential surfaces as RefreshError, not TransportError — it must
            # not be retried as if it were transient (it's handled as non-retryable elsewhere).
            google_auth_exceptions.RefreshError("invalid_grant"),
            ValueError("boom"),
        ],
    )
    def test_non_transient_error_is_not_retried(self, error):
        load = mock.Mock(side_effect=error)

        with mock.patch(_CLIENT_PATH) as ga_client, mock.patch(_SLEEP_PATH) as sleep:
            ga_client.load_from_dict = load
            with pytest.raises(type(error)):
                _load_client_with_transient_retry({"refresh_token": "x"})

        assert load.call_count == 1
        assert sleep.call_args_list == []


class TestTransientClientInitErrorDetection:
    @pytest.mark.parametrize(
        "exc, expected",
        [
            (google_auth_exceptions.TransportError("connection reset by peer"), True),
            # 502 Bad Gateway from the token endpoint: a RefreshError google-auth does not flag
            # retryable, but a transient server-side blip we ride out via its message signature.
            (google_auth_exceptions.RefreshError(_BAD_GATEWAY_TOKEN_ENDPOINT_BODY), True),
            # 500/503/504/408/429 token-endpoint responses arrive as a RefreshError google-auth
            # already flags retryable.
            (google_auth_exceptions.RefreshError("server_error", retryable=True), True),
            # Auth rejections also surface as RefreshError but are not transient — they must not be
            # ridden out in-process (they route through the non-retryable handling elsewhere).
            (google_auth_exceptions.RefreshError("invalid_grant: Token has been expired or revoked."), False),
            (google_auth_exceptions.RefreshError("access_not_configured"), False),
            (ValueError("boom"), False),
        ],
    )
    def test_is_transient_client_init_error(self, exc, expected):
        assert _is_transient_client_init_error(exc) is expected


class _StatusCodeRpcError(grpc.RpcError):
    """A raw gRPC error whose ``code()`` reports a given ``StatusCode`` (``_InactiveRpcError`` shape)."""

    def __init__(self, status_code: grpc.StatusCode, message: str = ""):
        self._status_code = status_code
        self._message = message

    def code(self) -> grpc.StatusCode:
        return self._status_code

    def __str__(self) -> str:
        return self._message


def _grpc_unavailable_error() -> grpc.RpcError:
    return _StatusCodeRpcError(grpc.StatusCode.UNAVAILABLE)


def _grpc_resource_exhausted_error(message: str = "") -> grpc.RpcError:
    return _StatusCodeRpcError(grpc.StatusCode.RESOURCE_EXHAUSTED, message)


def _google_ads_exception_wrapping(grpc_error: grpc.RpcError) -> GoogleAdsException:
    """A ``GoogleAdsException`` carrying a transport-level error on ``error``, the shape the SDK
    raises when it can pull an ads ``failure`` from the trailing metadata alongside the gRPC status.
    """
    return GoogleAdsException(error=grpc_error, call=None, failure=None, request_id="req-1")


def _grpc_internal_error() -> grpc.RpcError:
    return _StatusCodeRpcError(grpc.StatusCode.INTERNAL)


class TestTransientGrpcErrorDetection:
    @pytest.mark.parametrize(
        "exc, expected",
        [
            (google_api_exceptions.ServiceUnavailable("502:Bad Gateway"), True),
            (_grpc_unavailable_error(), True),
            # The SDK wraps the transport status in a GoogleAdsException when an ads failure rides
            # along (e.g. a backend DEADLINE_EXCEEDED) — still transient, so we unwrap it.
            (_google_ads_exception_wrapping(_grpc_unavailable_error()), True),
            # gRPC INTERNAL ("Internal error encountered.") is a transient Google-side blip — the
            # gapic wrapper and the raw _InactiveRpcError must both be ridden out in-process.
            (google_api_exceptions.InternalServerError("500 Internal error encountered."), True),
            (_grpc_internal_error(), True),
            # A quota/rate-limit RESOURCE_EXHAUSTED ("Resource has been exhausted (e.g. check
            # quota).") is Google-flagged retryable — both the gapic wrapper (whose ``code`` is an
            # HTTP int, not a callable ``StatusCode``) and the raw _InactiveRpcError must be ridden out.
            (google_api_exceptions.ResourceExhausted("Resource has been exhausted (e.g. check quota)."), True),
            (_grpc_resource_exhausted_error("Resource has been exhausted (e.g. check quota)."), True),
            # The SDK can also wrap a RESOURCE_EXHAUSTED transport status in a GoogleAdsException — the
            # unwrapped raw _InactiveRpcError then takes the ``code()`` path with the signature guard.
            (
                _google_ads_exception_wrapping(
                    _grpc_resource_exhausted_error("Resource has been exhausted (e.g. check quota).")
                ),
                True,
            ),
            # A client-side "Received message larger than max" abort is RESOURCE_EXHAUSTED too, but is
            # deterministic — it must not be retried in-process regardless of which shape it arrives as.
            (
                google_api_exceptions.ResourceExhausted("Received message larger than max (90000000 vs. 67108864)"),
                False,
            ),
            (_grpc_resource_exhausted_error("Received message larger than max (90000000 vs. 67108864)"), False),
            (
                _google_ads_exception_wrapping(
                    _grpc_resource_exhausted_error("Received message larger than max (90000000 vs. 67108864)")
                ),
                False,
            ),
            # A different gapic error must not be treated as transient.
            (google_api_exceptions.PermissionDenied("PERMISSION_DENIED"), False),
            # Google Ads API errors carry no transient gRPC status — they route through the existing
            # INVALID_PAGE_TOKEN / GoogleAdsException handling, not the transient retry.
            (_google_ads_exception(RequestErrorEnum.RequestError.INVALID_PAGE_TOKEN), False),
            (ValueError("boom"), False),
        ],
    )
    def test_is_transient_grpc_error(self, exc, expected):
        assert _is_transient_grpc_error(exc) is expected


class _FlakyService:
    """Raises a transient error for the first ``fail_times`` calls, then serves one page."""

    def __init__(self, page: SimpleNamespace, error: BaseException, fail_times: int):
        self.page = page
        self.error = error
        self.fail_times = fail_times
        self.calls = 0

    def search(self, request: dict):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error
        return SimpleNamespace(pages=iter([self.page]))


class TestSearchTransientRetry:
    @pytest.mark.parametrize(
        "error",
        [
            google_api_exceptions.ServiceUnavailable("502:Bad Gateway"),
            _grpc_unavailable_error(),
            _google_ads_exception_wrapping(_grpc_unavailable_error()),
            google_api_exceptions.InternalServerError("500 Internal error encountered."),
            _grpc_internal_error(),
            google_api_exceptions.ResourceExhausted("Resource has been exhausted (e.g. check quota)."),
            _grpc_resource_exhausted_error("Resource has been exhausted (e.g. check quota)."),
            _google_ads_exception_wrapping(
                _grpc_resource_exhausted_error("Resource has been exhausted (e.g. check quota).")
            ),
        ],
    )
    def test_rides_out_transient_error(self, error):
        service = _FlakyService(_single_page(), error=error, fail_times=2)
        manager = _FakeResumableManager(saved_token=None)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads.time.sleep"
        ) as sleep:
            tables = list(
                _search_as_arrow_tables(
                    service=service,  # type: ignore[arg-type]
                    customer_id="1234567890",
                    query="SELECT campaign.name FROM campaign",
                    table=_single_row_table(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                )
            )

        # Two transient failures were retried, then the page was served — no data lost.
        assert service.calls == 3
        # Backoff grows per attempt per `min(2 * attempt, 30)`: 2s after the 1st failure, 4s after the 2nd.
        assert sleep.call_args_list == [mock.call(2), mock.call(4)]
        assert [t.to_pylist() for t in tables] == [[{"campaign_name": "Acme"}]]

    def test_persistent_unavailable_is_reraised_for_temporal_to_retry(self):
        service = _FlakyService(
            _single_page(), error=google_api_exceptions.ServiceUnavailable("502:Bad Gateway"), fail_times=99
        )
        manager = _FakeResumableManager(saved_token=None)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads.time.sleep"
        ) as sleep:
            with pytest.raises(google_api_exceptions.ServiceUnavailable):
                list(
                    _search_as_arrow_tables(
                        service=service,  # type: ignore[arg-type]
                        customer_id="1234567890",
                        query="SELECT campaign.name FROM campaign",
                        table=_single_row_table(),
                        resumable_source_manager=manager,  # type: ignore[arg-type]
                    )
                )

        # Bounded attempts: it gives up rather than looping forever, leaving Temporal to retry.
        assert service.calls == 4
        # Backed off between each attempt (2s, 4s, 6s) but not after the final attempt that re-raises.
        assert sleep.call_args_list == [mock.call(2), mock.call(4), mock.call(6)]

    def test_non_transient_error_is_not_retried(self):
        service = _FlakyService(_single_page(), error=ValueError("boom"), fail_times=99)
        manager = _FakeResumableManager(saved_token=None)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads.time.sleep"
        ) as sleep:
            with pytest.raises(ValueError):
                list(
                    _search_as_arrow_tables(
                        service=service,  # type: ignore[arg-type]
                        customer_id="1234567890",
                        query="SELECT campaign.name FROM campaign",
                        table=_single_row_table(),
                        resumable_source_manager=manager,  # type: ignore[arg-type]
                    )
                )

        # First call raises and propagates immediately — no retry, no backoff.
        assert service.calls == 1
        assert sleep.call_count == 0


class _FlakyFieldService:
    """Raises a transient error for the first ``fail_times`` calls, then returns a fields pager."""

    def __init__(self, pager: object, error: BaseException, fail_times: int):
        self.pager = pager
        self.error = error
        self.fail_times = fail_times
        self.calls = 0

    def search_google_ads_fields(self, query: str):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error
        return self.pager


class TestSearchFieldsTransientRetry:
    @pytest.mark.parametrize(
        "error",
        [
            google_api_exceptions.ServiceUnavailable("502:Bad Gateway"),
            _grpc_unavailable_error(),
            _google_ads_exception_wrapping(_grpc_unavailable_error()),
            # The reported failure: gRPC INTERNAL ("Internal error encountered.") during schema
            # discovery, arriving both as the gapic wrapper and the raw _InactiveRpcError.
            google_api_exceptions.InternalServerError("500 Internal error encountered."),
            _grpc_internal_error(),
        ],
    )
    def test_rides_out_transient_error(self, error):
        pager = object()
        service = _FlakyFieldService(pager, error=error, fail_times=2)

        with mock.patch(_SLEEP_PATH) as sleep:
            result = _search_fields_with_transient_retry(service, "select name from x")  # type: ignore[arg-type]

        assert result is pager
        # Two transient failures retried, then the pager was returned.
        assert service.calls == 3
        assert sleep.call_args_list == [mock.call(2), mock.call(4)]

    def test_persistent_internal_is_reraised_for_temporal_to_retry(self):
        service = _FlakyFieldService(
            object(), error=google_api_exceptions.InternalServerError("500 Internal error encountered."), fail_times=99
        )

        with mock.patch(_SLEEP_PATH) as sleep:
            with pytest.raises(google_api_exceptions.InternalServerError):
                _search_fields_with_transient_retry(service, "select name from x")  # type: ignore[arg-type]

        # Bounded attempts: it gives up rather than looping forever, leaving Temporal to retry.
        assert service.calls == 4
        assert sleep.call_args_list == [mock.call(2), mock.call(4), mock.call(6)]

    def test_non_transient_error_is_not_retried(self):
        service = _FlakyFieldService(object(), error=ValueError("boom"), fail_times=99)

        with mock.patch(_SLEEP_PATH) as sleep:
            with pytest.raises(ValueError):
                _search_fields_with_transient_retry(service, "select name from x")  # type: ignore[arg-type]

        assert service.calls == 1
        assert sleep.call_count == 0


_INTEGRATION_GET_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads.Integration.objects.get"
)
_CLOSE_CONNECTIONS_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads.close_old_connections"
)


class TestGetIntegrationDbResilience:
    def test_retries_once_on_dropped_connection_then_succeeds(self):
        integration = object()
        get = mock.Mock(side_effect=[OperationalError("server closed the connection unexpectedly"), integration])

        with (
            mock.patch(_INTEGRATION_GET_PATH, get),
            mock.patch(_CLOSE_CONNECTIONS_PATH) as close,
            mock.patch(_SLEEP_PATH),
        ):
            result = _get_integration(integration_id=1, team_id=2)

        assert result is integration
        assert get.call_count == 2
        # Evicted up front, then again after the failed query marked the connection unusable.
        assert close.call_count == 2

    def test_rides_out_pool_wait_timeout_then_succeeds(self):
        integration = object()
        # A saturated connection pooler rejects the query with a wait timeout (surfaced as an
        # OperationalError); the previous immediate single retry hit the same saturation, so we
        # back off and retry a few times before giving up.
        get = mock.Mock(
            side_effect=[
                OperationalError("query_wait_timeout"),
                OperationalError("query_wait_timeout"),
                integration,
            ]
        )

        with (
            mock.patch(_INTEGRATION_GET_PATH, get),
            mock.patch(_CLOSE_CONNECTIONS_PATH),
            mock.patch(_SLEEP_PATH) as sleep,
        ):
            result = _get_integration(integration_id=1, team_id=2)

        assert result is integration
        assert get.call_count == 3
        # Backoff grows per attempt per `min(2 * attempt, 30)`: 2s after the 1st failure, 4s after the 2nd.
        assert sleep.call_args_list == [mock.call(2), mock.call(4)]

    def test_reraises_after_exhausting_attempts(self):
        get = mock.Mock(side_effect=OperationalError("query_wait_timeout"))

        with (
            mock.patch(_INTEGRATION_GET_PATH, get),
            mock.patch(_CLOSE_CONNECTIONS_PATH),
            mock.patch(_SLEEP_PATH) as sleep,
        ):
            with pytest.raises(OperationalError):
                _get_integration(integration_id=1, team_id=2)

        # Bounded attempts: it gives up rather than looping forever, leaving Temporal to retry.
        assert get.call_count == 4
        # Backed off between each attempt (2s, 4s, 6s) but not after the final attempt that re-raises.
        assert sleep.call_args_list == [mock.call(2), mock.call(4), mock.call(6)]

    def test_missing_integration_is_not_retried(self):
        get = mock.Mock(side_effect=Integration.DoesNotExist())

        with mock.patch(_INTEGRATION_GET_PATH, get), mock.patch(_CLOSE_CONNECTIONS_PATH):
            with pytest.raises(Integration.DoesNotExist):
                _get_integration(integration_id=1, team_id=2)

        # A deleted connection row is non-retryable elsewhere — don't mask it as a transient drop.
        assert get.call_count == 1

    def test_no_retry_on_success(self):
        integration = object()
        get = mock.Mock(return_value=integration)

        with mock.patch(_INTEGRATION_GET_PATH, get), mock.patch(_CLOSE_CONNECTIONS_PATH) as close:
            result = _get_integration(integration_id=1, team_id=2)

        assert result is integration
        assert get.call_count == 1
        assert close.call_count == 1


class TestOverviewStatsSchemas:
    # Overview stats tables exist to recover cost that click-type segmentation drops: requesting
    # segments.click_type makes Google omit cost not yet attributed to a click type, so summed cost
    # reads low for recent days. Each overview must equal its *_stats counterpart minus that one
    # segment, while staying incremental on segments.date.
    @pytest.mark.parametrize(
        "overview_alias, stats_alias",
        [
            ("ad_overview_stats", "ad_stats"),
            ("ad_group_overview_stats", "ad_group_stats"),
        ],
    )
    def test_overview_equals_stats_table_without_click_type(self, overview_alias, stats_alias):
        overview = RESOURCE_SCHEMAS[overview_alias]
        stats = RESOURCE_SCHEMAS[stats_alias]

        assert "segments.click_type" not in overview["field_names"]
        assert "segments.click_type" not in overview["primary_key"]
        assert overview["resource_name"] == stats["resource_name"]
        assert overview["field_names"] == [f for f in stats["field_names"] if f != "segments.click_type"]
        assert overview["primary_key"] == [k for k in stats["primary_key"] if k != "segments.click_type"]
        assert overview["filter_field_names"] == [("segments.date", IncrementalFieldType.Date)]
