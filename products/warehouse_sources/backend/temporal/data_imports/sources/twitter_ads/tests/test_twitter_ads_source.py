import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests

from posthog.models.integration.model import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twitterads import (
    TwitterAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twitter_ads.settings import (
    ACCOUNT_ACCESS_DENIED,
    MISSING_APP,
    MISSING_INTEGRATION,
    REVOKED_GRANT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twitter_ads.source import TwitterAdsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.twitter_ads.twitter_ads import (
    TwitterAdsClient,
    twitter_ads_source,
)


@pytest.mark.parametrize(
    "status,message",
    [
        (200, None),
        (401, REVOKED_GRANT),
        (403, ACCOUNT_ACCESS_DENIED),
        (503, "X Ads could not validate this ad account. Please try again."),
    ],
)
@override_settings(TWITTER_ADS_CONSUMER_KEY="fake-key", TWITTER_ADS_CONSUMER_SECRET="fake-secret")
def test_validate_account_access_and_error_mapping(status: int, message: str | None) -> None:
    integration = Integration(
        kind="twitter-ads", sensitive_config={"oauth_token": "fake-access", "oauth_token_secret": "fake-secret"}
    )
    http_response = requests.Response()
    http_response.status_code = status
    http_response._content = b'{"data": {}}'
    http_response.url = "https://ads-api.x.com/12/accounts/account"
    source = TwitterAdsSource()
    with (
        patch.object(source, "get_oauth_integration", return_value=integration),
        patch("requests.Session.send", return_value=http_response),
    ):
        assert source.validate_credentials(
            TwitterAdsSourceConfig(account_id="account", twitter_ads_integration_id=1), 1
        ) == (status == 200, message)
    if status in (401, 403):
        with pytest.raises(requests.HTTPError) as error:
            http_response.raise_for_status()
        assert any(
            pattern in str(error.value) and text == message
            for pattern, text in source.get_non_retryable_errors().items()
        )
        with (
            patch.object(source, "get_oauth_integration", return_value=integration),
            patch("requests.Session.send", return_value=http_response),
            pytest.raises(IntegrationAccountListingError, match=message),
        ):
            source.get_oauth_accounts(1, 1)


@pytest.mark.parametrize("case", ["missing-integration", "missing-token", "wrong-kind", "missing-app", "network"])
@override_settings(TWITTER_ADS_CONSUMER_KEY="fake-key", TWITTER_ADS_CONSUMER_SECRET="fake-secret")
def test_unusable_connection_has_actionable_message(case: str) -> None:
    integration = Integration(
        kind="twitter-ads", sensitive_config={"oauth_token": "fake-access", "oauth_token_secret": "fake-secret"}
    )
    source = TwitterAdsSource()
    expected = MISSING_INTEGRATION
    if case == "missing-token":
        integration.sensitive_config = {}
    if case == "wrong-kind":
        integration.kind = "reddit-ads"
    if case == "missing-app":
        expected = MISSING_APP
    if case == "network":
        expected = "Could not reach X Ads. Please try again."
    with (
        patch.object(
            source,
            "get_oauth_integration",
            return_value=integration,
            side_effect=ValueError("Integration not found") if case == "missing-integration" else None,
        ),
        patch("requests.Session.send", side_effect=requests.ConnectionError("unreachable")),
        override_settings(TWITTER_ADS_CONSUMER_KEY="" if case == "missing-app" else "fake-key"),
    ):
        assert source.validate_credentials(
            TwitterAdsSourceConfig(account_id="account", twitter_ads_integration_id=1), 1
        ) == (False, expected)
        with pytest.raises(IntegrationAccountListingError, match=expected):
            source.get_oauth_accounts(1, 1)


def test_account_listing_preserves_names_and_omits_deleted() -> None:
    source = TwitterAdsSource()
    with (
        patch.object(source, "get_oauth_integration", return_value=MagicMock()),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.twitter_ads.source.TwitterAdsClient"
        ) as client,
    ):
        client.return_value.pages.return_value = iter(
            [
                {"data": [{"id": "one", "name": "Example Ads"}]},
                {"data": [{"id": "two", "deleted": True}, {"id": "three"}]},
            ]
        )
        accounts = source.get_oauth_accounts(1, 1)
    assert [(account.value, account.display_name) for account in accounts] == [
        ("one", "Example Ads"),
        ("three", "three"),
    ]


@override_settings(TWITTER_ADS_CONSUMER_KEY="fake-key", TWITTER_ADS_CONSUMER_SECRET="fake-secret")
def test_unsupported_version_and_unknown_table_fail_before_http() -> None:
    integration = Integration(
        kind="twitter-ads", sensitive_config={"oauth_token": "fake-access", "oauth_token_secret": "fake-secret"}
    )
    with pytest.raises(ValueError, match="Unsupported X Ads API version"):
        TwitterAdsClient(integration, "11")
    with pytest.raises(ValueError, match="Unknown X Ads table"):
        twitter_ads_source(TwitterAdsClient(integration), "account", "unknown", MagicMock(), None)
