from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.factorial.factorial import FactorialResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.factorial.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.factorial.source import FactorialSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FactorialSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "employees",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestFactorialSource:
    def setup_method(self) -> None:
        self.source = FactorialSource()
        self.team_id = 123
        self.config = FactorialSourceConfig(api_key="test-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.FACTORIAL

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Factorial"
        assert config.label == "Factorial"
        # Shipping behind the unreleased flag while in alpha: hidden from users until verified live.
        assert config.unreleasedSource is True
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/factorial"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

        (api_key_field,) = config.fields
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O in get_schemas), so the public docs can render the
        # Supported tables section.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error", "Unauthorized for url"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_all_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No endpoint has a curl-verified server-side filter yet, so every schema is full refresh only.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["leaves"])
        assert len(schemas) == 1
        assert schemas[0].name == "leaves"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_get_documented_tables_renders_catalog(self) -> None:
        # Drives the public-docs <SourceTables /> path: static catalog + canonical descriptions.
        tables = self.source.get_documented_tables()
        names = {t["name"] for t in tables}
        assert names == set(ENDPOINTS)
        leaves = next(t for t in tables if t["name"] == "leaves")
        assert leaves["description"]
        assert leaves["sync_methods"] == ["Full refresh"]
        assert leaves["primary_keys"] == []  # detected_primary_keys is unset for static schemas

    def test_canonical_descriptions_keyed_by_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        # Every documented table must map to a real endpoint, else the description is dead weight.
        assert set(descriptions).issubset(set(ENDPOINTS))

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            ((True, None), True, None),
            (
                (False, "Invalid Factorial API key, or it does not have access to your account's data."),
                False,
                "Invalid Factorial API key, or it does not have access to your account's data.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.factorial.source.validate_factorial_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, str | None],
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("test-key")

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FactorialResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.factorial.source.factorial_source")
    def test_source_for_pipeline_passes_arguments(self, mock_factorial_source: mock.MagicMock) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = _make_inputs(schema_name="leaves", team_id=99, job_id="job-xyz")

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_factorial_source.assert_called_once_with(
            api_key="test-key",
            endpoint="leaves",
            team_id=99,
            job_id="job-xyz",
            resumable_source_manager=manager,
        )
