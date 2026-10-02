import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.singular import (
    SingularSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.singular.settings import (
    DEFAULT_DIMENSIONS,
    DEFAULT_METRICS,
    LOOKUPS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.singular.source import (
    SingularSource,
    report_query,
)

_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.singular.source.validate_singular_credentials"
)


class TestSingularSource:
    def setup_method(self):
        self.source = SingularSource()
        self.team_id = 123

    def test_report_merges_on_date_with_a_lookback_and_lookups_are_full_refresh(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(SingularSourceConfig(api_key="k"), 1)}

        report = schemas.pop("daily_report")
        assert report.supports_incremental
        assert not report.supports_append
        assert [field["field"] for field in report.incremental_fields] == ["date"]
        assert report.default_incremental_lookback_seconds == 7 * 24 * 60 * 60

        assert set(schemas) == set(LOOKUPS)
        for lookup in schemas.values():
            assert not lookup.supports_incremental
            assert lookup.default_incremental_lookback_seconds is None

    def test_empty_inputs_fall_back_to_the_default_report(self):
        query = report_query(SingularSourceConfig(api_key="k"))

        assert query.dimensions == DEFAULT_DIMENSIONS
        assert query.metrics == DEFAULT_METRICS
        assert query.cohort_metrics == ()
        assert query.cohort_periods == ()

    @pytest.mark.parametrize(
        "cohort_metrics, cohort_periods",
        [("revenue", None), (None, "7d"), ("revenue", " , ")],
    )
    @mock.patch(_VALIDATE)
    def test_cohort_fields_must_be_set_together(self, mock_validate, cohort_metrics, cohort_periods):
        config = SingularSourceConfig(api_key="k", cohort_metrics=cohort_metrics, cohort_periods=cohort_periods)

        is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert message is not None and "Cohort metrics and cohort periods go together" in message
        mock_validate.assert_not_called()

    @mock.patch(_VALIDATE, return_value=(True, None))
    def test_valid_inputs_reach_the_api_key_check(self, mock_validate):
        config = SingularSourceConfig(api_key="k", cohort_metrics="revenue", cohort_periods="7d")

        assert self.source.validate_credentials(config, self.team_id) == (True, None)
        mock_validate.assert_called_once_with("k", "v2.0")

    @pytest.mark.parametrize(
        "schema_name, expected",
        [("daily_report", True), ("custom_dimensions", False), ("cohort_metrics", False)],
    )
    def test_only_the_report_counts_as_resumable(self, schema_name, expected):
        assert self.source.resume_covers_run(incremental_or_append=True, schema_name=schema_name) is expected
