import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gumroad import (
    GumroadSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.settings import GUMROAD_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.source import GumroadSource


class TestGumroadSource:
    def setup_method(self) -> None:
        self.source = GumroadSource()
        self.team_id = 123
        self.config = GumroadSourceConfig(access_token="gumroad-token")

    def test_pinned_version_matches_the_paths_the_code_calls(self) -> None:
        assert self.source.default_version == "v2"
        assert self.source.supported_versions == ("v2",)
        assert all(config.path.startswith("/v2/") for config in GUMROAD_ENDPOINTS.values())

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
