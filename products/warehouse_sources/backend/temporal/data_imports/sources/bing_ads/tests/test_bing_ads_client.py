import types

import pytest
from unittest import mock

from suds import WebFault

from products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.client import (
    BingAdsClient,
    extract_webfault_detail,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.source import BingAdsSource


def _make_webfault(faultstring: str, detail: object | None) -> WebFault:
    """Build a suds WebFault mirroring the shape the bingads SDK produces.

    str(WebFault) is the generic faultstring; the actionable error codes live on fault.detail.
    """
    fault = types.SimpleNamespace(faultstring=faultstring, detail=detail)
    return WebFault(fault, None)


def _ad_api_fault_detail(error_code: str, message: str, code: int = 105) -> object:
    error = types.SimpleNamespace(Code=code, ErrorCode=error_code, Message=message)
    return types.SimpleNamespace(AdApiFaultDetail=types.SimpleNamespace(Errors=types.SimpleNamespace(AdApiError=error)))


def _operation_fault_detail(*errors: tuple[object, str]) -> object:
    """Build an ``ApiFaultDetail.OperationErrors.OperationError[]`` detail.

    OperationError carries ``Code``/``Message`` (no ``ErrorCode``); pass a single error or many.
    """
    operation_errors = [types.SimpleNamespace(Code=code, Message=message) for code, message in errors]
    payload = operation_errors[0] if len(operation_errors) == 1 else operation_errors
    return types.SimpleNamespace(
        ApiFaultDetail=types.SimpleNamespace(OperationErrors=types.SimpleNamespace(OperationError=payload))
    )


@pytest.mark.parametrize(
    "detail,expected",
    [
        # No detail at all -> empty string, nothing to surface.
        (None, ""),
        # AdApiFaultDetail single error: ErrorCode wins over numeric Code.
        (
            _ad_api_fault_detail("InvalidCredentials", "The user is not authenticated."),
            "InvalidCredentials: The user is not authenticated.",
        ),
        # ApiFaultDetail single OperationError: falls back to numeric Code when no ErrorCode.
        (
            _operation_fault_detail((114, "Campaign service operation failed.")),
            "114: Campaign service operation failed.",
        ),
        # ApiFaultDetail with multiple OperationErrors are all surfaced, joined by "; ".
        (
            _operation_fault_detail((114, "First failure."), (116, "Second failure.")),
            "114: First failure.; 116: Second failure.",
        ),
    ],
)
def test_extract_webfault_detail(detail, expected):
    """extract_webfault_detail must parse both AdApiFaultDetail and ApiFaultDetail shapes."""
    fault = types.SimpleNamespace(detail=detail)
    assert extract_webfault_detail(fault) == expected


class TestBingAdsClient:
    """Test suite for BingAdsClient."""

    def setup_method(self):
        """Set up test fixtures."""
        self.access_token = "test_access_token"
        self.refresh_token = "test_refresh_token"
        self.developer_token = "test_developer_token"
        self.account_id = 12345
        self.customer_id = 67890

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.client.ServiceClient")
    def test_get_customer_id_success(self, mock_service_client):
        """Test successful customer ID retrieval."""
        mock_user = mock.MagicMock()
        mock_user.CustomerId = self.customer_id

        mock_response = mock.MagicMock()
        mock_response.User = mock_user

        mock_client_instance = mock_service_client.return_value
        mock_client_instance.GetUser.return_value = mock_response

        client = BingAdsClient(self.access_token, self.refresh_token, self.developer_token)
        result = client.get_customer_id()

        assert result == self.customer_id
        assert client._customer_id == self.customer_id
        mock_client_instance.GetUser.assert_called_once_with(UserId=None)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.client.ServiceClient")
    def test_get_customer_id_preserves_underlying_exception_details(self, mock_service_client):
        """Underlying exception's class name and message must be embedded in the raised ValueError so
        the retry framework can selectively match auth-related substrings as non-retryable while
        keeping transient SDK errors (network/timeouts) retryable.
        """

        class OAuthTokenRequestException(Exception):
            pass

        mock_client_instance = mock_service_client.return_value
        mock_client_instance.GetUser.side_effect = OAuthTokenRequestException(
            "invalid_grant The provided authorization grant has expired or been revoked."
        )

        client = BingAdsClient(self.access_token, self.refresh_token, self.developer_token)
        with pytest.raises(ValueError) as exc_info:
            client.get_customer_id()

        message = str(exc_info.value)
        assert "Failed to fetch customer ID" in message
        assert "OAuthTokenRequestException" in message
        assert "invalid_grant" in message
        # __cause__ preserves the original exception for stack traces / logging.
        assert isinstance(exc_info.value.__cause__, OAuthTokenRequestException)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.client.ServiceClient")
    def test_get_customer_id_transient_failure_message_has_no_auth_substring(self, mock_service_client):
        """A network/timeout failure must not coincidentally match the non-retryable auth patterns."""
        mock_client_instance = mock_service_client.return_value
        mock_client_instance.GetUser.side_effect = ConnectionError(
            "HTTPSConnectionPool(host='bingads.microsoft.com', port=443): Max retries exceeded"
        )

        client = BingAdsClient(self.access_token, self.refresh_token, self.developer_token)
        with pytest.raises(ValueError) as exc_info:
            client.get_customer_id()

        message = str(exc_info.value)
        assert "ConnectionError" in message

        non_retryable_patterns = BingAdsSource().get_non_retryable_errors()
        assert not any(pattern in message for pattern in non_retryable_patterns)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.client.ServiceClient")
    def test_get_customer_id_surfaces_soap_fault_detail(self, mock_service_client):
        """The generic 'Invalid client data' faultstring hides the real error code in the SOAP fault
        detail. get_customer_id must surface that code so the retry framework can recognise it and
        operators can see the real cause — matching an existing non-retryable auth pattern.
        """
        webfault = _make_webfault(
            "Invalid client data. Check the SOAP fault details for more information. TrackingId: abc-123.",
            _ad_api_fault_detail("InvalidCredentials", "The user is not authenticated."),
        )
        mock_client_instance = mock_service_client.return_value
        mock_client_instance.GetUser.side_effect = webfault

        client = BingAdsClient(self.access_token, self.refresh_token, self.developer_token)
        with pytest.raises(ValueError) as exc_info:
            client.get_customer_id()

        message = str(exc_info.value)
        assert "Failed to fetch customer ID" in message
        # The detail error code is surfaced alongside the generic umbrella message.
        assert "InvalidCredentials" in message
        assert "Invalid client data" in message
        # The surfaced detail makes the failure match a non-retryable pattern.
        non_retryable_patterns = BingAdsSource().get_non_retryable_errors()
        assert any(pattern in message for pattern in non_retryable_patterns)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.client.ServiceClient")
    def test_get_customer_id_webfault_without_detail_keeps_generic_message(self, mock_service_client):
        """A WebFault with no parseable detail must not crash extraction — it just keeps the faultstring."""
        webfault = _make_webfault("Internal Error", detail=None)
        mock_client_instance = mock_service_client.return_value
        mock_client_instance.GetUser.side_effect = webfault

        client = BingAdsClient(self.access_token, self.refresh_token, self.developer_token)
        with pytest.raises(ValueError) as exc_info:
            client.get_customer_id()

        message = str(exc_info.value)
        assert "Failed to fetch customer ID: WebFault" in message
        assert "Internal Error" in message
        # No detail to surface, so no auth pattern should be matched (stays retryable).
        non_retryable_patterns = BingAdsSource().get_non_retryable_errors()
        assert not any(pattern in message for pattern in non_retryable_patterns)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.client.ServiceClient")
    def test_get_campaigns_success(self, mock_service_client):
        """Test successful campaigns retrieval."""
        mock_campaign = mock.MagicMock()
        mock_campaign.Id = 123
        mock_campaign.Name = "Test Campaign"
        mock_campaign.Status = "Active"
        mock_campaign.CampaignType = "Search"
        mock_campaign.BudgetType = "DailyBudgetStandard"
        mock_campaign.DailyBudget = 100
        mock_campaign.AudienceAdsBidAdjustment = 0
        mock_campaign.TimeZone = "PacificTimeUSCanadaTijuana"

        mock_languages = mock.MagicMock()
        mock_languages.string = ["English"]
        mock_campaign.Languages = mock_languages

        mock_campaigns = mock.MagicMock()
        mock_campaigns.Campaign = [mock_campaign]

        mock_client_instance = mock_service_client.return_value
        mock_client_instance.GetCampaignsByAccountId.return_value = mock_campaigns

        client = BingAdsClient(self.access_token, self.refresh_token, self.developer_token)
        result = list(client.get_campaigns(self.account_id, self.customer_id))

        assert len(result) == 1
        assert len(result[0]) == 1
        campaign_data = result[0][0]
        assert campaign_data["Id"] == 123
        assert campaign_data["Name"] == "Test Campaign"
        assert campaign_data["Status"] == "Active"
        assert campaign_data["Languages"] == ["English"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.client.ServiceClient")
    def test_get_campaigns_surfaces_soap_fault_detail(self, mock_service_client):
        """GetCampaignsByAccountId raises the same generic 'Invalid client data' WebFault as GetUser when
        the configured account is unusable. get_campaigns must funnel it through _wrap_with_fault_detail
        so the real error code in the SOAP detail reaches the retry framework instead of a raw WebFault.
        """
        webfault = _make_webfault(
            "Invalid client data. Check the SOAP fault details for more information. TrackingId: abc-123.",
            _ad_api_fault_detail("AuthenticationTokenExpired", "The authentication token has expired."),
        )
        mock_client_instance = mock_service_client.return_value
        mock_client_instance.GetCampaignsByAccountId.side_effect = webfault

        client = BingAdsClient(self.access_token, self.refresh_token, self.developer_token)
        with pytest.raises(ValueError) as exc_info:
            list(client.get_campaigns(self.account_id, self.customer_id))

        message = str(exc_info.value)
        assert "Failed to fetch campaigns" in message
        assert "AuthenticationTokenExpired" in message
        assert "Invalid client data" in message
        non_retryable_patterns = BingAdsSource().get_non_retryable_errors()
        assert any(pattern in message for pattern in non_retryable_patterns)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.client.ServiceClient")
    def test_get_campaigns_transient_failure_stays_retryable(self, mock_service_client):
        """A network/timeout failure from GetCampaignsByAccountId must keep its original signature and
        not coincidentally match a non-retryable auth pattern.
        """
        mock_client_instance = mock_service_client.return_value
        mock_client_instance.GetCampaignsByAccountId.side_effect = ConnectionError(
            "HTTPSConnectionPool(host='bingads.microsoft.com', port=443): Max retries exceeded"
        )

        client = BingAdsClient(self.access_token, self.refresh_token, self.developer_token)
        with pytest.raises(ValueError) as exc_info:
            list(client.get_campaigns(self.account_id, self.customer_id))

        message = str(exc_info.value)
        assert "Failed to fetch campaigns" in message
        assert "ConnectionError" in message
        non_retryable_patterns = BingAdsSource().get_non_retryable_errors()
        assert not any(pattern in message for pattern in non_retryable_patterns)
