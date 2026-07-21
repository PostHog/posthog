from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SwarmiaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.source import SwarmiaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.swarmia import SwarmiaResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.source"


def _make_inputs(
    schema_name: str = "pull_requests",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="end_date" if should_use_incremental_field else None,
        incremental_field_type=IncrementalFieldType.Date if should_use_incremental_field else None,
        job_id="job-id",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestSwarmiaSource:
    def setup_method(self) -> None:
        self.source = SwarmiaSource()
        self.config = SwarmiaSourceConfig(api_key="token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SWARMIA

    def test_source_config_is_released_alpha(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Swarmia"
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/swarmia"

    def test_source_config_has_secret_api_key_field(self) -> None:
        fields = self.source.get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True

    @parameterized.expand(
        [
            ("pull_requests", True),
            ("dora", True),
            ("investment", True),
            ("capex", False),
            ("capex_employees", False),
            ("fte", False),
        ]
    )
    def test_get_schemas_incremental_support(self, endpoint: str, supports_incremental: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}

        schema = schemas[endpoint]
        assert schema.supports_incremental is supports_incremental
        # Re-pulled trailing windows must be merged (deduped on primary key), never appended.
        assert schema.supports_append is False
        if supports_incremental:
            assert [f["field"] for f in schema.incremental_fields] == ["end_date"]

    def test_get_schemas_returns_all_endpoints_and_filters_by_name(self) -> None:
        assert {s.name for s in self.source.get_schemas(self.config, team_id=1)} == set(ENDPOINTS)
        assert [s.name for s in self.source.get_schemas(self.config, team_id=1, names=["dora"])] == ["dora"]

    @parameterized.expand(
        [
            ("valid_token", 200, None, True),
            ("invalid_token", 401, None, False),
            ("forbidden_at_create_is_accepted", 403, None, True),
            ("forbidden_for_specific_schema_fails", 403, "investment", False),
            ("network_failure", None, None, False),
        ]
    )
    @patch(f"{_SOURCE_MODULE}.check_credentials")
    def test_validate_credentials(
        self,
        _name: str,
        status: int | None,
        schema_name: str | None,
        expected_valid: bool,
        mock_check: MagicMock,
    ) -> None:
        mock_check.return_value = status

        valid, error = self.source.validate_credentials(self.config, team_id=1, schema_name=schema_name)

        assert valid is expected_valid
        if not expected_valid:
            assert error

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert manager._data_class is SwarmiaResumeConfig

    @patch(f"{_SOURCE_MODULE}.swarmia_source")
    def test_source_for_pipeline_passes_incremental_value_only_when_enabled(self, mock_source: MagicMock) -> None:
        manager = MagicMock()

        inputs = _make_inputs(should_use_incremental_field=True, db_incremental_field_last_value="2026-06-28")
        self.source.source_for_pipeline(self.config, manager, inputs)
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "token"
        assert kwargs["endpoint"] == "pull_requests"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-06-28"

        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value="2026-06-28")
        self.source.source_for_pipeline(self.config, manager, inputs)
        kwargs = mock_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None

    def test_non_retryable_errors_cover_auth_failures(self) -> None:
        errors = self.source.get_non_retryable_errors()
        assert "401 Client Error: Unauthorized for url: https://app.swarmia.com" in errors
        assert "403 Client Error: Forbidden for url: https://app.swarmia.com" in errors

    def test_canonical_descriptions_match_endpoint_catalog(self) -> None:
        # A canonical entry keyed off a name not in the catalog is silently unused (typo guard).
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)
