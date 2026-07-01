from typing import Any

from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TodoistSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.source import TodoistSource
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.todoist import TodoistResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = overrides.get("schema_name", "tasks")
    return inputs


class TestTodoistSource:
    def setup_method(self) -> None:
        self.source = TodoistSource()
        self.team_id = 123
        self.config = TodoistSourceConfig(api_token="tok-test")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.TODOIST

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Todoist"
        assert config.label == "Todoist"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Stays hidden until the source is promoted out of alpha.
        assert config.unreleasedSource is True
        assert len(config.fields) == 1

        token_field = config.fields[0]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.name == "api_token"
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        # The token is sent to the API, so it must be stored as a secret.
        assert token_field.secret is True

    def test_get_schemas_matches_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_are_all_full_refresh(self) -> None:
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["tasks", "projects"])
        assert {s.name for s in schemas} == {"tasks", "projects"}

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # Each declared endpoint should ship a curated description so it isn't sent to the LLM.
        described = set(self.source.get_canonical_descriptions().keys())
        assert set(ENDPOINTS).issubset(described)

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.todoist.com/api/v1/tasks?limit=200",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.todoist.com/api/v1/projects",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.todoist.com', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.todoist.com/api/v1/tasks"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.todoist.com/api/v1/tasks"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_validate_credentials_success(self) -> None:
        with mock.patch.object(source_module, "validate_todoist_credentials", return_value=True) as probe:
            ok, error = self.source.validate_credentials(self.config, self.team_id)
        assert ok is True
        assert error is None
        probe.assert_called_once_with("tok-test")

    def test_validate_credentials_failure(self) -> None:
        with mock.patch.object(source_module, "validate_todoist_credentials", return_value=False):
            ok, error = self.source.validate_credentials(self.config, self.team_id)
        assert ok is False
        assert error == "Invalid Todoist API token"

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is TodoistResumeConfig

    def test_source_for_pipeline_plumbs_token_and_endpoint(self) -> None:
        manager = mock.MagicMock()
        inputs = _make_inputs(schema_name="projects")
        with mock.patch.object(source_module, "todoist_source") as todoist_source_fn:
            self.source.source_for_pipeline(self.config, manager, inputs)
        todoist_source_fn.assert_called_once_with(
            api_token="tok-test",
            endpoint="projects",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )
