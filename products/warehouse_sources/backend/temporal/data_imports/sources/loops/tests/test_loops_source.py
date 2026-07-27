from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.loops import LoopsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.loops.loops import LoopsResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.loops.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.loops.source import LoopsSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "campaigns",
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


class TestLoopsSource:
    def setup_method(self) -> None:
        self.source = LoopsSource()
        self.team_id = 123
        self.config = LoopsSourceConfig(api_key="test-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.LOOPS

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Loops"
        assert config.label == "Loops"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/loops.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/loops"

        assert len(config.fields) == 1
        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    @pytest.mark.parametrize(
        "raised_message",
        [
            # requests raises `<status> Client Error: <reason> for url: <url>`; the sync matcher
            # is a substring check, so the keys must classify these as non-retryable.
            "401 Client Error: Unauthorized for url: https://app.loops.so/api/v1/campaigns?perPage=50",
            "403 Client Error: Forbidden for url: https://app.loops.so/api/v1/lists",
        ],
    )
    def test_auth_errors_are_non_retryable(self, raised_message: str) -> None:
        keys = self.source.get_non_retryable_errors().keys()
        assert any(key in raised_message for key in keys)

    def test_get_schemas_all_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Loops list endpoints have no server-side timestamp filters, so advertising
        # incremental sync would silently degrade to a broken full scan.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    @pytest.mark.parametrize(
        ("names", "expected"),
        [
            (["campaigns"], {"campaigns"}),
            (["nonexistent"], set()),
        ],
    )
    def test_get_schemas_filtered_by_names(self, names: list[str], expected: set[str]) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=names)
        assert {s.name for s in schemas} == expected

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            ((True, None), True, None),
            ((False, "Invalid Loops API key"), False, "Invalid Loops API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.loops.source.validate_loops_credentials"
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
        mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is LoopsResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.loops.source.loops_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="workflows", team_id=99, job_id="job-xyz")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key="test-key",
            endpoint="workflows",
            team_id=99,
            job_id="job-xyz",
            resumable_source_manager=manager,
        )

    def test_canonical_descriptions_cover_only_known_endpoints(self) -> None:
        # A description keyed by a name `get_schemas` never returns is dead metadata
        # (typo'd endpoint or a rename that missed this file).
        assert set(self.source.get_canonical_descriptions().keys()) <= set(ENDPOINTS)
