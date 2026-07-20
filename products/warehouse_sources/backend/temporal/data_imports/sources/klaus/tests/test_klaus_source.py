from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KlausSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.klaus.klaus import KlausResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.klaus.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.klaus.source import KlausSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {"reviews", "autoqa_reviews", "autoqa_ratings", "csat", "calibration_sessions"}
FULL_REFRESH_ENDPOINTS = {"users", "workspaces", "quizzes", "scorecards", "disputes"}


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "reviews",
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


class TestKlausSource:
    def setup_method(self) -> None:
        self.source = KlausSource()
        self.team_id = 123
        self.config = KlausSourceConfig(subdomain="acme", api_token="test-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.KLAUS

    def test_subdomain_is_a_connection_host_field(self) -> None:
        # Changing the subdomain retargets where the stored token is sent, so it must
        # force the token to be re-entered.
        assert self.source.connection_host_fields == ["subdomain"]

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Klaus"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/klaus"

        subdomain_field, api_token_field = config.fields
        assert isinstance(subdomain_field, SourceFieldInputConfig)
        assert subdomain_field.name == "subdomain"
        assert subdomain_field.type == SourceFieldInputConfigType.TEXT
        assert subdomain_field.required is True

        assert isinstance(api_token_field, SourceFieldInputConfig)
        assert api_token_field.name == "api_token"
        assert api_token_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_token_field.required is True
        assert api_token_field.secret is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error", "Unauthorized for url"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        assert {name for name, s in schemas.items() if s.supports_incremental} == INCREMENTAL_ENDPOINTS
        assert {name for name, s in schemas.items() if not s.supports_incremental} == FULL_REFRESH_ENDPOINTS
        for name in INCREMENTAL_ENDPOINTS:
            assert schemas[name].incremental_fields, name
        for name in FULL_REFRESH_ENDPOINTS:
            assert schemas[name].incremental_fields == [], name

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["reviews", "nonexistent"])
        assert [s.name for s in schemas] == ["reviews"]

    def test_get_documented_tables_lists_static_catalog(self) -> None:
        # lists_tables_without_credentials must stay in sync with a get_schemas that
        # does no I/O, so the public docs can render the table catalog.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            ((True, None), True, None),
            ((False, "Invalid Zendesk QA subdomain or API token"), False, "Invalid Zendesk QA subdomain or API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.klaus.source.validate_klaus_credentials"
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
        mock_validate.assert_called_once_with(self.config.subdomain, self.config.api_token)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is KlausResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.klaus.source.klaus_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        logger = mock.MagicMock()
        inputs = _make_inputs(
            schema_name="autoqa_reviews",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            logger=logger,
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            subdomain="acme",
            api_token="test-token",
            endpoint="autoqa_reviews",
            logger=logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
