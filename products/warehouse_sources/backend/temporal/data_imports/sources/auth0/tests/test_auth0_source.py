from typing import Any, Optional

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.auth0.auth0 import Auth0ResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.auth0.settings import (
    AUTH0_ENDPOINTS,
    ENDPOINTS,
    REQUIRED_SCOPES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.auth0.source import Auth0Source
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.auth0 import Auth0SourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.auth0.source"


def _inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "users",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 7,
        "should_use_incremental_field": True,
        "db_incremental_field_last_value": "2024-01-01T00:00:00.000Z",
        "db_incremental_field_earliest_value": None,
        "incremental_field": "updated_at",
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    return SourceInputs(**{**defaults, **overrides})


class TestAuth0Source:
    def setup_method(self) -> None:
        self.source = Auth0Source()
        self.team_id = 7
        self.config = Auth0SourceConfig(auth0_domain="tenant.us.auth0.com", client_id="cid", client_secret="secret")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.AUTH0

    def test_source_is_released_as_alpha(self) -> None:
        config = self.source.get_source_config

        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.label == "Auth0"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/auth0"

    def test_fields_take_machine_to_machine_credentials(self) -> None:
        fields = self.source.get_source_config.fields

        assert [f.name for f in fields] == ["auth0_domain", "client_id", "client_secret"]
        for source_field in fields:
            assert isinstance(source_field, SourceFieldInputConfig)
            assert source_field.required is True
        secret_flags = {f.name: f.secret for f in fields if isinstance(f, SourceFieldInputConfig)}
        assert secret_flags == {"auth0_domain": False, "client_id": False, "client_secret": True}
        client_secret = next(f for f in fields if f.name == "client_secret")
        assert isinstance(client_secret, SourceFieldInputConfig)
        assert client_secret.type == SourceFieldInputConfigType.PASSWORD

    def test_connection_host_fields_pin_the_domain(self) -> None:
        # Without this, an org member could retarget the domain at a server they control and the
        # preserved client secret would be sent there.
        assert self.source.connection_host_fields == ["auth0_domain"]

    def test_api_version_is_pinned_to_what_the_paths_call(self) -> None:
        assert self.source.supported_versions == ("v2",)
        assert self.source.default_version == "v2"
        assert self.source.resolve_api_version(None) == "v2"
        assert all("/api/{version}/" in c.path_template for c in AUTH0_ENDPOINTS.values())

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_auth_failures_are_non_retryable(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_only_collections_with_a_server_side_date_filter_are_incremental(self, endpoint: str) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        # Only users and logs document a Lucene date range filter; everything else is full refresh.
        assert schemas[endpoint].supports_incremental is (endpoint in ("users", "logs"))
        # The window's inclusive lower bound re-reads boundary rows, so append would duplicate them.
        assert schemas[endpoint].supports_append is False

    def test_users_offers_both_timestamp_cursors(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert [f["field"] for f in schemas["users"].incremental_fields] == ["updated_at", "created_at"]
        assert [f["field"] for f in schemas["logs"].incremental_fields] == ["date"]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["logs"])
        assert [s.name for s in schemas] == ["logs"]

    def test_table_catalog_is_listed_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_every_endpoint_is_documented(self, endpoint: str) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert endpoint in descriptions
        assert descriptions[endpoint]["columns"]
        assert REQUIRED_SCOPES[endpoint].startswith("read:")

    @pytest.mark.parametrize("schema_name", [None, "users"])
    def test_validate_credentials_passes_the_config_through(self, schema_name: Optional[str]) -> None:
        with mock.patch(f"{SOURCE_MODULE}.validate_auth0_credentials", return_value=(True, None)) as mock_validate:
            assert self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name) == (True, None)

        kwargs = mock_validate.call_args.kwargs
        assert kwargs == {
            "domain": "tenant.us.auth0.com",
            "client_id": "cid",
            "client_secret": "secret",
            "api_version": "v2",
            "schema_name": schema_name,
            "team_id": self.team_id,
        }

    def test_validate_credentials_surfaces_failures(self) -> None:
        with mock.patch(f"{SOURCE_MODULE}.validate_auth0_credentials", return_value=(False, "nope")):
            assert self.source.validate_credentials(self.config, self.team_id) == (False, "nope")

    def test_resumable_manager_is_bound_to_the_resume_dataclass(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is Auth0ResumeConfig

    def test_source_for_pipeline_forwards_the_incremental_cursor(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs())
        with mock.patch(f"{SOURCE_MODULE}.auth0_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, _inputs())

        kwargs = mock_source.call_args.kwargs
        assert kwargs["endpoint"] == "users"
        assert kwargs["api_version"] == "v2"
        assert kwargs["incremental_field"] == "updated_at"
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00.000Z"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 7

    def test_full_refresh_drops_the_watermark(self) -> None:
        inputs = _inputs(should_use_incremental_field=False, schema_name="clients")
        manager = self.source.get_resumable_source_manager(inputs)
        with mock.patch(f"{SOURCE_MODULE}.auth0_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
