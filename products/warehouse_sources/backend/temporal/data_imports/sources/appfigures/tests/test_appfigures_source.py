import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source import AppfiguresSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appfigures import (
    AppfiguresSourceConfig,
)


class TestAppfiguresSource:
    def setup_method(self):
        self.source = AppfiguresSource()
        self.team_id = 123
        self.config = AppfiguresSourceConfig(personal_access_token="pat_test")

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_products_is_full_refresh_reports_and_reviews_incremental(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["products"].supports_incremental is False
        assert schemas["products"].incremental_fields == []
        for name in ("reviews", "sales_report", "revenue_report"):
            assert schemas[name].supports_incremental is True
            assert [f["field"] for f in schemas[name].incremental_fields] == ["date"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["reviews"])
        assert len(schemas) == 1
        assert schemas[0].name == "reviews"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "status,schema_name,expected_ok",
        [
            (200, None, True),
            (200, "reviews", True),
            (401, None, False),
            (401, "reviews", False),
            # 403 at source-create is a valid token missing an unrelated scope — accept it.
            (403, None, True),
            # 403 for a specific schema means the token can't sync that table — reject.
            (403, "reviews", False),
            (500, None, False),
            (None, None, False),
        ],
    )
    def test_validate_credentials(self, status, schema_name, expected_ok):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source.check_credentials",
            return_value=status,
        ):
            ok, _ = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
            assert ok is expected_ok

    def test_validate_credentials_probes_schema_specific_path(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source.check_credentials",
            return_value=200,
        ) as probe:
            self.source.validate_credentials(self.config, self.team_id, schema_name="reviews")
            probe.assert_called_once_with("pat_test", "/reviews")

    def test_validate_credentials_defaults_to_products_path(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source.check_credentials",
            return_value=200,
        ) as probe:
            self.source.validate_credentials(self.config, self.team_id)
            probe.assert_called_once_with("pat_test", "/products/mine")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.appfigures.com/v2/reviews?count=1",
            "403 Client Error: Forbidden for url: https://api.appfigures.com/v2/reports/sales",
            "403 Client Error: This request requires 3 credit(s). Reason: Some given products are not owned by your account. (the first one is: 338244644767 for url: https://api.appfigures.com/v2/reviews?count=500&page=1&sort=date&start=2026-08-05",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.appfigures.com/v2/reviews",
        ],
    )
    def test_non_retryable_errors_ignore_unrelated(self, unrelated_error):
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)
