import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.skio import SkioSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.skio.source import SkioSource


def _inputs(schema_name: str) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestSkioSource:
    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        source = SkioSource()
        with pytest.raises(ValueError, match="does not exist"):
            source.source_for_pipeline(
                SkioSourceConfig(api_token="token"),
                MagicMock(),
                _inputs("not_a_skio_table"),
            )

    def test_get_schemas_filters_by_names(self) -> None:
        source = SkioSource()
        schemas = source.get_schemas(SkioSourceConfig(api_token="token"), team_id=1, names=["orders", "customers"])
        assert sorted(schema.name for schema in schemas) == ["customers", "orders"]

    @pytest.mark.parametrize(
        "api_error_message",
        [
            # Verbatim strings the live API returns, kept as field knowledge: an invalid token and a
            # token whose role can't see the queried collection. Both ride an HTTP 200 body, so
            # they must match on the exception message for the sync to stop retrying.
            "Skio API error: Invalid response from authorization hook",
            "Skio API error: field 'Subscriptions' not found in type: 'query_root'",
        ],
    )
    def test_non_retryable_patterns_match_real_api_errors(self, api_error_message: str) -> None:
        source = SkioSource()
        assert error_message_matches(api_error_message, source.get_non_retryable_errors().keys())
