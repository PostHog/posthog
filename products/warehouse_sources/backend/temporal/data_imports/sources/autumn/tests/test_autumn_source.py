from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.autumn.autumn import AutumnResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.autumn.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.autumn.source import AutumnSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.autumn import AutumnSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(
    schema_name: str = "Customers",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
    api_version: Optional[str] = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field=incremental_field,
        incremental_field_type=None,
        job_id="job-id",
        logger=MagicMock(),
        reset_pipeline=False,
        api_version=api_version,
    )


class TestAutumnSource:
    def setup_method(self) -> None:
        self.source = AutumnSource()
        self.config = AutumnSourceConfig(api_key="am_sk_test")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.AUTUMN

    def test_get_schemas_advertises_incremental_only_for_events(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=123)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)

        by_name = {schema.name: schema for schema in schemas}
        incremental_names = [name for name, schema in by_name.items() if schema.supports_incremental]
        assert incremental_names == ["Events"]
        assert [field["field"] for field in by_name["Events"].incremental_fields] == ["timestamp"]

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=123, names=["Events", "Invoices"])

        assert {schema.name for schema in schemas} == {"Events", "Invoices"}

    def test_validate_credentials_delegates_with_pinned_api_version(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.autumn.source.validate_autumn_credentials",
            return_value=(True, None),
        ) as mock_validate:
            assert self.source.validate_credentials(self.config, team_id=123) == (True, None)

        mock_validate.assert_called_once_with("am_sk_test", "2.3.0")

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())

        assert manager._data_class is AutumnResumeConfig

    @pytest.mark.parametrize(
        ("should_use_incremental_field", "expected_last_value"),
        [
            (True, 1704067200000),
            # A stale watermark must not leak into a full-refresh run.
            (False, None),
        ],
    )
    def test_source_for_pipeline_plumbing(
        self, should_use_incremental_field: bool, expected_last_value: Optional[int]
    ) -> None:
        inputs = _make_inputs(
            schema_name="Events",
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=1704067200000,
            incremental_field="timestamp",
        )
        manager = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.autumn.source.autumn_source"
        ) as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key="am_sk_test",
            endpoint="Events",
            team_id=123,
            job_id="job-id",
            api_version="2.3.0",
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=expected_last_value,
            incremental_field="timestamp",
        )

    def test_source_config_keeps_api_key_secret_and_source_visible(self) -> None:
        config = self.source.get_source_config

        assert config.unreleasedSource is not True

        (api_key_field,) = config.fields
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
