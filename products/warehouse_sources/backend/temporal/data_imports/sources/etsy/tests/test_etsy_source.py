from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.etsy import (
    DAILY_QUOTA_EXHAUSTED_ERROR,
    RATE_LIMITED_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.settings import ENDPOINTS, ETSY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.source import EtsySource

_INCREMENTAL_ENDPOINTS = [name for name, cfg in ETSY_ENDPOINTS.items() if cfg.incremental_fields]
_FULL_REFRESH_ENDPOINTS = [name for name, cfg in ETSY_ENDPOINTS.items() if not cfg.incremental_fields]


class TestEtsySourceClass:
    def test_source_config(self) -> None:
        config = EtsySource().get_source_config

        assert config.label == "Etsy"
        assert config.category == DataWarehouseSourceCategory.E_COMMERCE
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/etsy"
        assert config.iconPath == "/static/services/etsy.png"
        # A hidden source cannot be connected — a finished source must stay visible.
        assert config.unreleasedSource is None

    def test_credential_fields_include_the_shared_secret(self) -> None:
        # Etsy rejects a keystring-only x-api-key, so setup has to collect the secret alongside it.
        secret_field = next(
            field
            for field in EtsySource().get_source_config.fields
            if isinstance(field, SourceFieldInputConfig) and field.name == "shared_secret"
        )

        assert secret_field.required is True
        assert secret_field.secret is True

    def test_shop_id_is_a_connection_host_field(self) -> None:
        # shop_id steers where the stored token is sent, so changing it must force credential re-entry.
        assert EtsySource().connection_host_fields == ["shop_id"]

    def test_api_version_metadata(self) -> None:
        assert EtsySource.supported_versions == ("v3",)
        assert EtsySource.default_version == "v3"
        assert EtsySource.api_docs_url is not None
        assert EtsySource.api_docs_url.startswith("https://")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs table list must render.
        assert EtsySource.lists_tables_without_credentials is True
        assert {table["name"] for table in EtsySource().get_documented_tables()} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("429 Client Error: Too Many Requests for url: https://api.etsy.com/v3/application/users/me",),
            ("500 Server Error: Internal Server Error for url: https://api.etsy.com/v3/application/users/me",),
        ]
    )
    def test_rate_limit_and_server_errors_are_retryable(self, message: str) -> None:
        # EtsyClient's tracked session already retries a 429/5xx three times before raise_for_status
        # can raise; an exhausted rate limit or server error reaching us here must stay out of error
        # tracking as noise instead of being reported like a genuine PostHog bug.
        retryable_errors = EtsySource().get_retryable_errors()

        assert any(pattern in message for pattern in retryable_errors)

    @parameterized.expand([(DAILY_QUOTA_EXHAUSTED_ERROR,), (RATE_LIMITED_ERROR,)])
    def test_rate_limit_sentinels_stay_retryable_and_carry_a_friendly_message(self, sentinel: str) -> None:
        # The transport raises these strings and the source is the only thing that reads them, so a
        # rename on either side would quietly leave the job showing raw 429 text.
        source = EtsySource()

        assert error_message_matches(sentinel, source.get_retryable_errors())
        message = next(
            value
            for pattern, value in source.get_retry_exhausted_errors().items()
            if error_message_matches(sentinel, [pattern])
        )
        assert "Etsy" in message
