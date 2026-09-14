from unittest import mock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.settings import (
    COMMISSIONS_INCREMENTAL_LOOKBACK_SECONDS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.source import FirstPromoterSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.firstpromoter import (
    FirstPromoterSourceConfig,
)

FULL_REFRESH_ENDPOINTS = ("payouts", "promo_codes", "promoter_campaigns", "promoters", "referrals")


class TestFirstPromoterSource:
    def setup_method(self) -> None:
        self.source = FirstPromoterSource()
        self.team_id = 123
        self.config = FirstPromoterSourceConfig(api_key="fp-key", account_id="98765")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "FirstPromoter"
        assert config.label == "FirstPromoter"
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/first_promoter.png"
        # The source ships visible — a truthy unreleasedSource hides it from every user.
        assert not config.unreleasedSource

    def test_credential_fields(self) -> None:
        config = self.source.get_source_config
        # Both are mandatory: the Admin API rejects a request carrying only the bearer token.
        assert [f.name for f in config.fields] == ["api_key", "account_id"]
        api_key, account_id = config.fields
        assert isinstance(api_key, SourceFieldInputConfig)
        assert isinstance(account_id, SourceFieldInputConfig)
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.secret is True
        assert api_key.required is True
        assert account_id.required is True

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_commissions_is_the_only_incremental_table(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["commissions"].supports_incremental is True
        assert [f["field"] for f in schemas["commissions"].incremental_fields] == ["created_at"]
        # Commission status and payout linkage mutate after creation, so an incremental run has to
        # re-read a trailing window rather than only rows newer than the watermark.
        assert schemas["commissions"].default_incremental_lookback_seconds == COMMISSIONS_INCREMENTAL_LOOKBACK_SECONDS

    @parameterized.expand([(name,) for name in FULL_REFRESH_ENDPOINTS])
    def test_mutable_tables_stay_full_refresh(self, name: str) -> None:
        # These endpoints either have no usable server-side time filter or no way to pin row
        # order; offering incremental would freeze their mutating fields at first-import values.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[name].supports_incremental is False
        assert schemas[name].incremental_fields == []
        assert schemas[name].default_incremental_lookback_seconds is None

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["commissions"])
        assert [s.name for s in schemas] == ["commissions"]

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.firstpromoter.com/api/v2/company/promoters", True),
            ("403 Client Error: Forbidden for url: https://api.firstpromoter.com/api/v2/company/commissions", True),
            (
                "429 Client Error: Too Many Requests for url: https://api.firstpromoter.com/api/v2/company/payouts",
                False,
            ),
            (
                "500 Server Error: Internal Server Error for url: https://api.firstpromoter.com/api/v2/company/payouts",
                False,
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures_only(self, observed_error: str, expect_match: bool) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable) is expect_match

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.source.first_promoter_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "commissions"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.api_version = None
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "created_at"
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "fp-key"
        assert kwargs["account_id"] == "98765"
        assert kwargs["endpoint"] == "commissions"
        assert kwargs["api_version"] == "v2"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["incremental_field"] == "created_at"
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.source.first_promoter_source"
    )
    def test_source_for_pipeline_omits_watermark_when_not_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "commissions"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
