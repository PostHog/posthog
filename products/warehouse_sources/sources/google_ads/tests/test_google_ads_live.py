import os
import json
from collections.abc import Iterable, Iterator
from contextlib import nullcontext

import pytest
from unittest import mock

import pyarrow as pa

from products.warehouse_sources.sources.google_ads.configs import (
    GoogleAdsResumeConfig,
    GoogleAdsServiceAccountSourceConfig,
)
from products.warehouse_sources.sources.google_ads.google_ads import get_schemas, google_ads_source
from products.warehouse_sources.sources.google_ads.source import GoogleAdsSource
from products.warehouse_sources.sources.sdk import ResumableSourceManager
from products.warehouse_sources.sources.sdk.testing import source_inputs

SKIP_IF_MISSING_GOOGLE_ADS_CREDENTIALS = pytest.mark.skipif(
    "GOOGLE_SERVICE_ACCOUNT_CREDENTIALS" not in os.environ
    and "GOOGLE_DEVELOPER_TOKEN" not in os.environ
    and "GOOGLE_ADS_CUSTOMER_ID" not in os.environ,
    reason="Google service account credentials and/or developer token not set in environment",
)


@pytest.fixture
def customer_id() -> str:
    """Return customer id if available in environment, otherwise a default."""
    customer_id = os.getenv("GOOGLE_ADS_CUSTOMER_ID", None)

    if not customer_id:
        return "1111111111"
    else:
        return customer_id


@pytest.fixture
def developer_token() -> str:
    """Return developer token if available in environment, otherwise a default."""
    developer_token = os.getenv("GOOGLE_DEVELOPER_TOKEN", None)

    if not developer_token:
        return "aaabbbccc111222333"
    else:
        return developer_token


@pytest.fixture
def service_account_secrets(developer_token: str):
    """Serve the platform service account credentials through the credentials service wrapper."""
    credentials_file_path = os.environ["GOOGLE_SERVICE_ACCOUNT_CREDENTIALS"]
    with open(credentials_file_path) as f:
        credentials = json.load(f)

    with mock.patch(
        "products.warehouse_sources.sources.google_ads.google_ads.credentials_service.get_secrets",
        return_value={
            "GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY": credentials["private_key"],
            "GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY_ID": credentials["private_key_id"],
            "GOOGLE_ADS_SERVICE_ACCOUNT_TOKEN_URI": credentials["token_uri"],
            "GOOGLE_ADS_SERVICE_ACCOUNT_CLIENT_EMAIL": credentials["client_email"],
            "GOOGLE_ADS_DEVELOPER_TOKEN": developer_token,
        },
    ):
        yield


@SKIP_IF_MISSING_GOOGLE_ADS_CREDENTIALS
def test_get_schemas(customer_id: str, service_account_secrets: None):
    """Test get_schemas returns well-known schemas.

    This test is not exhaustive and merely limits itself to asserting a handful
    of well-known schemas are returned.
    """
    cfg = GoogleAdsServiceAccountSourceConfig(customer_id=customer_id)
    schemas = get_schemas(cfg, team_id=1, api_version=GoogleAdsSource().default_version)

    assert "campaign" in schemas
    assert "ad_group" in schemas
    assert "ad" in schemas

    campaign = schemas["campaign"]
    assert campaign["campaign_id"].to_arrow_field() == pa.field("campaign_id", pa.int64())
    assert campaign["campaign_name"].to_arrow_field() == pa.field("campaign_name", pa.string())
    assert campaign["campaign_status"].to_arrow_field() == pa.field("campaign_status", pa.string())
    assert campaign["campaign_start_date"].to_arrow_field() == pa.field("campaign_start_date", pa.date32())

    ad_group = schemas["ad_group"]
    assert ad_group["ad_group_id"].to_arrow_field() == pa.field("ad_group_id", pa.int64())
    assert ad_group["campaign_id"].to_arrow_field() == pa.field("campaign_id", pa.int64())
    assert ad_group["ad_group_name"].to_arrow_field() == pa.field("ad_group_name", pa.string())
    assert ad_group["ad_group_status"].to_arrow_field() == pa.field("ad_group_status", pa.string())
    assert ad_group["ad_group_type"].to_arrow_field() == pa.field("ad_group_type", pa.string())

    ad = schemas["ad"]
    assert ad["ad_group_ad_ad_id"].to_arrow_field() == pa.field("ad_group_ad_ad_id", pa.int64())
    assert ad["ad_group_ad_ad_name"].to_arrow_field() == pa.field("ad_group_ad_ad_name", pa.string())
    assert ad["ad_group_ad_ad_type"].to_arrow_field() == pa.field("ad_group_ad_ad_type", pa.string())


class _MemoryRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def exists(self, key: str) -> int:
        return int(key in self.store)

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.fixture
def memory_redis() -> Iterator[None]:
    # The real Google Ads API answers this test, so the fake network cannot supply the redis.
    redis = _MemoryRedis()
    with mock.patch.object(ResumableSourceManager, "_get_redis", lambda self: nullcontext(redis)):
        yield


@SKIP_IF_MISSING_GOOGLE_ADS_CREDENTIALS
def test_google_ads_source(customer_id: str, service_account_secrets: None, memory_redis: None):
    """Test google_ads_source can iterate rows.

    This test is not exhaustive and merely limits itself to attempting to
    iterate a few sources.
    """

    cfg = GoogleAdsServiceAccountSourceConfig(customer_id=customer_id)
    for resource in (
        "campaign",
        "campaign_stats",
        "ad_group",
        "ad_group_stats",
        "ad",
        "ad_stats",
        "keyword",
        "keyword_stats",
        "video",
        "video_stats",
        "customer_stats",
        "search_term_stats",
        "geographic_stats",
        "campaign_overview_stats",
        "video_performance_stats",
        "asset_group",
        "asset_group_stats",
        "shopping_performance_view",
        "conversion_action",
    ):
        manager = ResumableSourceManager(source_inputs(resource), GoogleAdsResumeConfig)
        source = google_ads_source(
            cfg,
            resource_name=resource,
            team_id=1,
            resumable_source_manager=manager,
            api_version=GoogleAdsSource().default_version,
        )

        items = source.items()
        assert isinstance(items, Iterable)
        list(items)
