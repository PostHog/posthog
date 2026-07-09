from collections.abc import Generator
from datetime import datetime
from typing import Any

import structlog
from bingads import AuthorizationData, OAuthTokens, OAuthWebAuthCodeGrant, ServiceClient
from bingads.v13 import reporting
from suds import WebFault

from posthog.settings import integrations

from .schemas import REPORT_CONFIG, RESOURCE_SCHEMAS, BingAdsResource
from .utils import (
    ENVIRONMENT,
    REPORT_POLL_INTERVAL_MS,
    build_report_request,
    download_and_extract_report_csv,
    parse_csv_to_dicts,
)

logger = structlog.get_logger(__name__)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def extract_webfault_detail(fault: Any) -> str:
    """Pull the actionable error codes/messages out of a Bing Ads suds ``WebFault``.

    The top-level ``faultstring`` is intentionally generic (e.g. "Invalid client data. Check the
    SOAP fault details for more information."). The real, stable error codes — ``InvalidCredentials``,
    ``AuthenticationTokenExpired``, ``WorkIdentityNotAvailable``, etc. — live in the SOAP fault
    detail. Surfacing them lets the retry framework recognise auth/credential failures as
    non-retryable and gives operators a real cause instead of the opaque umbrella message.

    Detail shape mirrors the bingads SDK (see ``bingads.util.errorcode_of_exception``):
    ``AdApiFaultDetail.Errors.AdApiError[]`` for auth/general errors and
    ``ApiFaultDetail.OperationErrors.OperationError[]`` for operation-level errors.
    """
    detail = getattr(fault, "detail", None)
    if detail is None:
        return ""

    ad_api_errors = getattr(getattr(getattr(detail, "AdApiFaultDetail", None), "Errors", None), "AdApiError", None)
    operation_errors = getattr(
        getattr(getattr(detail, "ApiFaultDetail", None), "OperationErrors", None), "OperationError", None
    )

    parts: list[str] = []
    for err in _as_list(ad_api_errors) + _as_list(operation_errors):
        code = getattr(err, "ErrorCode", None) or getattr(err, "Code", None)
        message = getattr(err, "Message", None)
        fragment = ": ".join(str(p) for p in (code, message) if p)
        if fragment:
            parts.append(fragment)

    return "; ".join(parts)


def _wrap_with_fault_detail(e: Exception, context: str) -> ValueError:
    """Wrap a bingads SDK error so the SOAP fault detail the generic faultstring hides reaches
    both the logs and the retry classifier. Every Bing Ads SOAP call should funnel its errors
    through here — otherwise the real, stable code (``InvalidReportColumn``, ``InvalidCredentials``,
    etc.) is lost behind the opaque "Invalid client data..." umbrella message.

    Preserves the underlying exception's type and message — plus any SOAP fault detail — so the
    retry framework can selectively recognise auth/config failures as non-retryable while transient
    SDK errors (network, Bing outage, rate limits) keep their original signature and stay retryable.
    """
    fault_detail = extract_webfault_detail(e.fault) if isinstance(e, WebFault) else ""
    logger.warning(
        context,
        error=str(e),
        error_type=type(e).__name__,
        fault_detail=fault_detail,
    )
    detail_suffix = f" ({fault_detail})" if fault_detail else ""
    return ValueError(f"{context}: {type(e).__name__}: {e}{detail_suffix}")


class BingAdsClient:
    def __init__(self, access_token: str, refresh_token: str, developer_token: str):
        self.developer_token = developer_token
        self._customer_id: int | None = None

        # The SDK requires OAuth setup
        self.oauth = OAuthWebAuthCodeGrant(
            client_id=integrations.BING_ADS_CLIENT_ID,
            client_secret=integrations.BING_ADS_CLIENT_SECRET,
            redirection_uri="",
        )

        # Access private member to set token - this is the SDK's expected pattern
        self.oauth._oauth_tokens = OAuthTokens(
            access_token=access_token,
            access_token_expires_in_seconds=3600,
            refresh_token=refresh_token,
        )

        self.authorization_data = AuthorizationData(
            account_id=None,
            customer_id=None,
            developer_token=developer_token,
            authentication=self.oauth,
        )

    def get_customer_id(self) -> int:
        if self._customer_id is not None:
            return self._customer_id

        try:
            service_client = ServiceClient(
                service="CustomerManagementService",
                version=13,
                authorization_data=self.authorization_data,
                environment=ENVIRONMENT,
            )

            user = service_client.GetUser(UserId=None).User
            self._customer_id = user.CustomerId
        except Exception as e:
            raise _wrap_with_fault_detail(e, "Failed to fetch customer ID") from e

        return self._customer_id

    def get_campaigns(self, account_id: int, customer_id: int) -> Generator[list[dict[str, Any]]]:
        self.authorization_data.account_id = account_id
        self.authorization_data.customer_id = customer_id

        try:
            service_client = ServiceClient(
                service="CampaignManagementService",
                version=13,
                authorization_data=self.authorization_data,
                environment=ENVIRONMENT,
            )

            campaigns = service_client.GetCampaignsByAccountId(AccountId=account_id)
        except Exception as e:
            raise _wrap_with_fault_detail(e, "Failed to fetch campaigns") from e

        result = []
        if campaigns and campaigns.Campaign:
            for campaign in campaigns.Campaign:
                languages = getattr(campaign, "Languages", None)
                languages_list = list(languages.string) if languages and hasattr(languages, "string") else None
                result.append(
                    {
                        "Id": campaign.Id,
                        "Name": campaign.Name,
                        "Status": campaign.Status,
                        "CampaignType": getattr(campaign, "CampaignType", None),
                        "BudgetType": getattr(campaign, "BudgetType", None),
                        "DailyBudget": getattr(campaign, "DailyBudget", None),
                        "AudienceAdsBidAdjustment": getattr(campaign, "AudienceAdsBidAdjustment", None),
                        "Languages": languages_list,
                        "TimeZone": getattr(campaign, "TimeZone", None),
                    }
                )

        yield result

    def get_performance_report(
        self,
        resource: BingAdsResource,
        account_id: int,
        customer_id: int,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict[str, Any]]:
        report_config = REPORT_CONFIG[resource]
        schema = RESOURCE_SCHEMAS[resource]

        self.authorization_data.account_id = account_id
        self.authorization_data.customer_id = customer_id

        try:
            reporting_service_manager = reporting.ReportingServiceManager(
                authorization_data=self.authorization_data,
                poll_interval_in_milliseconds=REPORT_POLL_INTERVAL_MS,
                environment=ENVIRONMENT,
            )

            # Build report request using SDK's factory pattern
            report_request = build_report_request(
                service_factory=reporting_service_manager._service_client.factory,
                report_config=report_config,
                field_names=schema["field_names"],
                account_id=account_id,
                start_date=start_date,
                end_date=end_date,
            )

            # Download and extract CSV from ZIP
            csv_data = download_and_extract_report_csv(
                reporting_service_manager=reporting_service_manager,
                report_request=report_request,
                report_type=report_config["report_type"],
                account_id=account_id,
            )
        except Exception as e:
            raise _wrap_with_fault_detail(e, f"Failed to generate {resource.value} report") from e

        return parse_csv_to_dicts(csv_data)

    def get_data_by_resource(
        self,
        resource: BingAdsResource,
        account_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Generator[list[dict[str, Any]]]:
        customer_id = self.get_customer_id()

        if resource == BingAdsResource.CAMPAIGNS:
            yield from self.get_campaigns(account_id, customer_id)
        elif resource in REPORT_CONFIG:
            if not start_date or not end_date:
                raise ValueError("start_date and end_date required for performance reports")
            yield self.get_performance_report(resource, account_id, customer_id, start_date, end_date)
        else:
            raise ValueError(f"Unsupported resource: {resource}")
