from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tvmaze import TVMazeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.source import TVMazeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.tvmaze import TVMazeResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "shows",
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


class TestTVMazeSource:
    def setup_method(self) -> None:
        self.source = TVMazeSource()
        self.team_id = 123
        self.config = TVMazeSourceConfig()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.TVMAZE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "TVMaze"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/tvmaze.png"
        # Doc slug and docsUrl must agree (see /documenting-warehouse-sources).
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/tvmaze"
        # Open public API — the connect form has no credential fields.
        assert config.fields == []

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog: public docs render the table list from get_schemas.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_all_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # TVmaze has no server-side timestamp filter, so no endpoint may
        # advertise incremental or append sync.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["shows"])
        assert [s.name for s in schemas] == ["shows"]

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # A drifted key silently falls back to LLM enrichment, so keep the
        # curated catalog aligned with the endpoint names.
        assert set(self.source.get_canonical_descriptions()) == set(ENDPOINTS)
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "TVmaze API is unreachable (status 503). Try again later."),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.source.check_connection")
    def test_validate_credentials(self, mock_check: mock.MagicMock, mock_return: tuple[bool, str | None]) -> None:
        mock_check.return_value = mock_return

        assert self.source.validate_credentials(self.config, self.team_id) == mock_return
        mock_check.assert_called_once_with()

    def test_get_non_retryable_errors_covers_auth_rejections(self) -> None:
        # A 401/403 from the public API is an IP-level block that a retry can't
        # fix, so it must be classified non-retryable rather than looping forever.
        errors = self.source.get_non_retryable_errors()
        assert set(errors) == {"401 Client Error", "403 Client Error"}
        assert all(message for message in errors.values())

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is TVMazeResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.source.tvmaze_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="people", team_id=99, job_id="job-xyz")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            endpoint="people",
            team_id=99,
            job_id="job-xyz",
            resumable_source_manager=manager,
        )
