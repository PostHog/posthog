import pytest
from unittest import mock

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gumroad import (
    GumroadSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.settings import (
    ENDPOINTS,
    GUMROAD_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.source import GumroadSource

INCREMENTAL_ENDPOINTS = {"sales", "payouts"}


class TestGumroadSource:
    def setup_method(self) -> None:
        self.source = GumroadSource()
        self.team_id = 123
        self.config = GumroadSourceConfig(access_token="gumroad-token")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Gumroad"
        assert config.category == DataWarehouseSourceCategory.E_COMMERCE
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/gumroad.png"
        # The source ships visible — a truthy unreleasedSource hides it from every user.
        assert not config.unreleasedSource

    def test_pinned_version_matches_the_paths_the_code_calls(self) -> None:
        assert self.source.default_version == "v2"
        assert self.source.supported_versions == ("v2",)
        assert all(config.path.startswith("/v2/") for config in GUMROAD_ENDPOINTS.values())

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
