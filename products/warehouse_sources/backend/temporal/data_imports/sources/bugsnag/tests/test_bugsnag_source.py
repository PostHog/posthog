from typing import Any

from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.bugsnag import BugsnagResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.settings import (
    BUGSNAG_ENDPOINTS,
    ENDPOINTS,
    BugsnagScope,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.source import BugsnagSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BugsnagSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _source_inputs(schema_name: str = "errors") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestBugsnagSource:
    def setup_method(self) -> None:
        self.source = BugsnagSource()
        self.team_id = 1

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.BUGSNAG

    def test_source_config_basics(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Bugsnag"
        # Alpha + still unreleased while it ships full-refresh-only and awaits live-API verification.
        assert config.unreleasedSource is True
        field_names = [f.name for f in config.fields]
        assert field_names == ["auth_token"]
        auth_field = config.fields[0]
        assert isinstance(auth_field, SourceFieldInputConfig)
        assert auth_field.required is True
        assert auth_field.secret is True

    def test_generated_config_parses_auth_token(self) -> None:
        # Guards the hand-checked generated_configs.py edit: the form field must map to `auth_token`.
        config = BugsnagSourceConfig.from_dict({"auth_token": "tok_123"})
        assert config.auth_token == "tok_123"

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_all_schemas_are_full_refresh(self) -> None:
        # Incremental isn't advertised until the server-side time-filter behavior is verified
        # against the live API, so every table ships full refresh only.
        for schema in self.source.get_schemas(MagicMock(), team_id=self.team_id):
            assert schema.supports_incremental is False, schema.name
            assert schema.supports_append is False, schema.name

    @parameterized.expand(
        [
            ("organizations", True),
            ("projects", True),
            ("errors", True),
            ("events", False),
            ("pivots", False),
            ("event_fields", False),
            ("trace_fields", False),
        ]
    )
    def test_should_sync_default(self, endpoint: str, expected_default: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(MagicMock(), team_id=self.team_id)}
        assert schemas[endpoint].should_sync_default is expected_default

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id, names=["errors", "projects"])
        assert {s.name for s in schemas} == {"errors", "projects"}

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.source.validate_bugsnag_credentials"
    )
    def test_validate_credentials_success(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = (True, None)
        ok, error = self.source.validate_credentials(BugsnagSourceConfig(auth_token="tok"), self.team_id)
        assert ok is True
        assert error is None
        mock_validate.assert_called_once_with("tok")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.source.validate_bugsnag_credentials"
    )
    def test_validate_credentials_failure(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = (False, "Invalid BugSnag auth token")
        ok, error = self.source.validate_credentials(BugsnagSourceConfig(auth_token="bad"), self.team_id)
        assert ok is False
        assert error == "Invalid BugSnag auth token"

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BugsnagResumeConfig

    def test_source_for_pipeline_plumbs_args(self) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs("errors"))
        response = self.source.source_for_pipeline(
            BugsnagSourceConfig(auth_token="tok"), manager, _source_inputs("errors")
        )
        assert response.name == "errors"
        assert response.primary_keys == BUGSNAG_ENDPOINTS["errors"].primary_keys

    @parameterized.expand(
        [
            ("organizations", ["id"]),
            ("projects", ["id", "organization_id"]),
            ("collaborators", ["id", "organization_id"]),
            ("errors", ["id", "project_id"]),
            ("event_fields", ["display_id", "project_id"]),
        ]
    )
    def test_source_response_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs(endpoint))
        response = self.source.source_for_pipeline(
            BugsnagSourceConfig(auth_token="tok"), manager, _source_inputs(endpoint)
        )
        assert response.primary_keys == expected_keys

    def test_fan_out_children_carry_parent_id_in_primary_key(self) -> None:
        # Fan-out children aggregate rows from every parent, so the parent id injected into each row
        # must be part of the primary key — otherwise per-parent-unique ids collide table-wide and
        # seed duplicate rows that slow every subsequent merge.
        for config in BUGSNAG_ENDPOINTS.values():
            if config.scope is BugsnagScope.PER_ORG:
                assert "organization_id" in config.primary_keys, config.name
            elif config.scope is BugsnagScope.PER_PROJECT:
                assert "project_id" in config.primary_keys, config.name

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.bugsnag.com/projects/abc/errors?per_page=100",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.bugsnag.com/user/organizations?per_page=1",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://api.bugsnag.com/projects/abc/errors",
            ),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.bugsnag.com/user/organizations",
            ),
            ("read_timeout", "HTTPSConnectionPool(host='api.bugsnag.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_canonical_descriptions_cover_core_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        for endpoint in ("organizations", "projects", "errors", "events", "releases"):
            assert endpoint in descriptions
            assert descriptions[endpoint]["description"]

    def test_canonical_description_keys_are_real_endpoints(self) -> None:
        # Canonical descriptions are keyed by schema name; a typo'd key would silently never apply.
        descriptions: dict[str, Any] = self.source.get_canonical_descriptions()
        assert set(descriptions).issubset(set(ENDPOINTS))
