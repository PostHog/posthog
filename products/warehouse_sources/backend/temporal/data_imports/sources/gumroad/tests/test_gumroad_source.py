import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gumroad import (
    GumroadSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.gumroad import GumroadResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.settings import (
    ENDPOINTS,
    GUMROAD_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.source import GumroadSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {"sales", "payouts"}


class TestGumroadSource:
    def setup_method(self) -> None:
        self.source = GumroadSource()
        self.team_id = 123
        self.config = GumroadSourceConfig(access_token="gumroad-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.GUMROAD

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Gumroad"
        assert config.category == DataWarehouseSourceCategory.E_COMMERCE
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/gumroad.png"
        # The source ships visible — a truthy unreleasedSource hides it from every user.
        assert not config.unreleasedSource

    def test_access_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        assert [f.name for f in config.fields] == ["access_token"]
        field = config.fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_pinned_version_matches_the_paths_the_code_calls(self) -> None:
        assert self.source.default_version == "v2"
        assert self.source.supported_versions == ("v2",)
        assert all(config.path.startswith("/v2/") for config in GUMROAD_ENDPOINTS.values())

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("name", sorted(ENDPOINTS))
    def test_get_schemas_incremental_semantics(self, name: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == name)

        # Only /sales and /payouts take a server-side `after` filter; everything else would have
        # to page the whole collection, which is a full refresh in disguise.
        if name in INCREMENTAL_ENDPOINTS:
            assert schema.supports_incremental is True
            assert [f["field"] for f in schema.incremental_fields] == ["created_at"]
        else:
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["sales"])
        assert [s.name for s in schemas] == ["sales"]

    @pytest.mark.parametrize(
        "name,expected_keys",
        [
            ("sales", ["id"]),
            ("products", ["id"]),
            ("payouts", ["id"]),
            ("subscribers", ["id"]),
            # Universal offer codes and global custom fields are listed under every product they
            # apply to, so the parent id has to be in the key or the rows collide.
            ("offer_codes", ["product_id", "id"]),
            ("custom_fields", ["product_id", "id"]),
            ("variant_categories", ["product_id", "id"]),
            ("product_reviews", ["product_id", "id"]),
        ],
    )
    def test_primary_keys(self, name: str, expected_keys: list[str]) -> None:
        assert GUMROAD_ENDPOINTS[name].primary_key == expected_keys

    @pytest.mark.parametrize(
        "observed_error,expect_match",
        [
            ("401 Client Error: Unauthorized for url: https://api.gumroad.com/v2/sales", True),
            ("403 Client Error: Forbidden for url: https://api.gumroad.com/v2/payouts", True),
            ("500 Server Error: Internal Server Error for url: https://api.gumroad.com/v2/sales", False),
        ],
    )
    def test_non_retryable_errors_match_auth_failures_only(self, observed_error: str, expect_match: bool) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable) is expect_match

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.source.validate_gumroad_credentials"
    )
    def test_validate_credentials_plumbs_access_token(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        assert mock_validate.call_args.args == ("gumroad-token",)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.source.check_endpoint_permission"
    )
    def test_get_endpoint_permissions_reports_missing_scope_per_table(self, mock_probe: mock.MagicMock) -> None:
        # A token can hold view_public without view_payouts, and the user needs to see which
        # table that costs them rather than having source creation fail.
        mock_probe.side_effect = lambda _token, path: path != "/v2/payouts"

        results = self.source.get_endpoint_permissions(
            self.config, self.team_id, ["sales", "payouts", "products", "offer_codes"]
        )

        assert results["sales"] is None
        assert results["products"] is None
        assert results["offer_codes"] is None
        assert results["payouts"] is not None and "view_payouts" in results["payouts"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.source.check_endpoint_permission"
    )
    def test_get_endpoint_permissions_probes_each_path_once(self, mock_probe: mock.MagicMock) -> None:
        # All four product-scoped tables share one probe path; probing per table would issue a
        # request per row of the schema picker.
        mock_probe.return_value = True

        self.source.get_endpoint_permissions(
            self.config, self.team_id, ["products", "offer_codes", "custom_fields", "variant_categories"]
        )

        assert [call.args[1] for call in mock_probe.call_args_list] == ["/v2/products"]

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert manager._data_class is GumroadResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.source.gumroad_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_gumroad_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "sales"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "created_at"
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_gumroad_source.call_args.kwargs
        assert kwargs["access_token"] == "gumroad-token"
        assert kwargs["endpoint"] == "sales"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["incremental_field"] == "created_at"
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.source.gumroad_source")
    def test_source_for_pipeline_omits_watermark_when_not_incremental(
        self, mock_gumroad_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "sales"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_gumroad_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
