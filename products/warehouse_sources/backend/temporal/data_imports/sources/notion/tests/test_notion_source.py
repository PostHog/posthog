import pytest
from unittest import mock

import requests
import structlog
from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NotionSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.notion.notion import NotionResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.notion.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.notion.source import NotionSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

NOTION_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.notion.notion"


def _make_inputs(schema_name: str = "pages") -> SourceInputs:
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
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 400


class TestNotionSource:
    def setup_method(self) -> None:
        self.source = NotionSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.NOTION

    def test_source_config_is_released_with_api_key_field(self) -> None:
        config = self.source.get_source_config
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not getattr(config, "unreleasedSource", None)

        fields = config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True

    def test_get_schemas_returns_all_endpoints_full_refresh(self) -> None:
        schemas = self.source.get_schemas(NotionSourceConfig(api_key="tok"), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)

    def test_get_schemas_honors_names_filter(self) -> None:
        schemas = self.source.get_schemas(NotionSourceConfig(api_key="tok"), team_id=1, names=["users"])
        assert [s.name for s in schemas] == ["users"]

    @parameterized.expand([(200, True), (401, False)])
    def test_validate_credentials(self, status_code: int, expected_valid: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = FakeResponse(status_code)
        with mock.patch(f"{NOTION_MODULE}.make_tracked_session", return_value=session):
            valid, _message = self.source.validate_credentials(NotionSourceConfig(api_key="tok"), team_id=1)
        assert valid is expected_valid

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is NotionResumeConfig

    def test_source_for_pipeline_partitions_search_streams(self) -> None:
        inputs = _make_inputs("pages")
        manager = self.source.get_resumable_source_manager(inputs)
        response = self.source.source_for_pipeline(NotionSourceConfig(api_key="tok"), manager, inputs)

        assert response.name == "pages"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_time"]

    def test_source_for_pipeline_users_has_no_partition(self) -> None:
        inputs = _make_inputs("users")
        manager = self.source.get_resumable_source_manager(inputs)
        response = self.source.source_for_pipeline(NotionSourceConfig(api_key="tok"), manager, inputs)

        assert response.name == "users"
        assert response.partition_mode is None
        assert response.partition_keys is None

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.notion.com/v1/search",),
            ("403 Client Error: Forbidden for url: https://api.notion.com/v1/users",),
        ]
    )
    def test_non_retryable_errors_match(self, error_message: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(pattern in error_message for pattern in non_retryable)

    def test_other_errors_are_retryable(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            pattern in "429 Client Error: Too Many Requests for url: https://api.notion.com/v1/search"
            for pattern in non_retryable
        )


@pytest.mark.parametrize("status_code", [500, 503])
def test_http_error_message_format_matches_non_retryable(status_code: int) -> None:
    # Sanity check that raised HTTPError messages won't accidentally match the 401/403 patterns.
    mock_response = requests.Response()
    mock_response.status_code = status_code
    mock_response.url = "https://api.notion.com/v1/search"
    with pytest.raises(requests.HTTPError) as exc_info:
        mock_response.raise_for_status()
    non_retryable = NotionSource().get_non_retryable_errors()
    assert not any(pattern in str(exc_info.value) for pattern in non_retryable)
