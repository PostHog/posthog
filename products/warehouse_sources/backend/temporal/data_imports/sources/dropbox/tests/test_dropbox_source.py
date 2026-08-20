from contextlib import AbstractContextManager
from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldOauthConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox.dropbox import DropboxResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox.source import DropboxSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dropbox import (
    DropboxSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dropbox.source"


class TestDropboxSource:
    def setup_method(self) -> None:
        self.source = DropboxSource()
        self.team_id = 123
        self.config = DropboxSourceConfig(
            dropbox_integration_id=7,
            folder_path="/Reports",
            team_member_id="dbmid:1",
        )

    def _patch_integration(
        self, access_token: str | None = "access-1", kind: str = "dropbox"
    ) -> AbstractContextManager[Any]:
        integration = mock.MagicMock()
        integration.access_token = access_token
        integration.kind = kind
        return mock.patch.object(DropboxSource, "get_oauth_integration", return_value=integration)

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.DROPBOX

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Dropbox"
        assert config.label == "Dropbox"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/dropbox.png"

        field_names = [f.name for f in config.fields]
        assert field_names == [
            "dropbox_integration_id",
            "folder_path",
            "team_member_id",
            "root_namespace_id",
        ]

    def test_the_account_is_connected_through_the_posthog_oauth_app(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldOauthConfig))

        assert field.name == "dropbox_integration_id"
        assert field.kind == "dropbox"
        assert field.required is True
        # Only individual scopes: a team scope would make every Dropbox token team-linked.
        assert field.requiredScopes == "account_info.read files.metadata.read sharing.read"

    @pytest.mark.parametrize("field_name", ["folder_path", "team_member_id", "root_namespace_id"])
    def test_business_and_scoping_fields_are_optional(self, field_name: str) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == field_name)

        assert field.required is False
        assert field.secret is False

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.dropboxapi.com/2/files/list_folder",
            "403 Client Error: Forbidden for url: https://api.dropboxapi.com/2/team_log/get_events",
            "409 Client Error: Conflict for url: https://api.dropboxapi.com/2/files/list_folder",
            "Integration not found: 7",
            "Dropbox access token not found",
        ],
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.dropboxapi.com/2/files/list_folder",
            "500 Server Error for url: https://api.dropboxapi.com/2/files/list_folder",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_leave_transient_failures_alone(self, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_covers_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_the_audit_log_is_incremental(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        # `team_log/get_events` is the one endpoint with a server-side time filter.
        assert {name for name, schema in schemas.items() if schema.supports_incremental} == {"team_events"}
        assert schemas["team_events"].incremental_fields == INCREMENTAL_FIELDS["team_events"]
        assert [f["field"] for f in schemas["team_events"].incremental_fields] == ["timestamp"]
        assert schemas["files"].incremental_fields == []
        assert schemas["files"].supports_append is False

    @pytest.mark.parametrize(
        "endpoint, should_sync_default",
        [
            ("files", True),
            ("shared_links", True),
            ("shared_folders", True),
            ("team_members", False),
            ("team_events", False),
        ],
    )
    def test_team_tables_are_not_enabled_by_default(self, endpoint: str, should_sync_default: bool) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].should_sync_default is should_sync_default

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["files"])

        assert [schema.name for schema in schemas] == ["files"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_are_published_without_credentials(self) -> None:
        tables = self.source.get_documented_tables()

        assert {table["name"] for table in tables} == set(ENDPOINTS)
        assert all(table["description"] for table in tables)

    def test_canonical_descriptions_key_off_endpoint_names(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS) <= set(ENDPOINTS)

    @pytest.mark.parametrize(
        "transport_result, expected",
        [
            ((True, None), (True, None)),
            ((False, "Could not authenticate with Dropbox."), (False, "Could not authenticate with Dropbox.")),
        ],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_dropbox_credentials")
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        transport_result: tuple[bool, str | None],
        expected: tuple[bool, str | None],
    ) -> None:
        mock_validate.return_value = transport_result

        with self._patch_integration():
            assert self.source.validate_credentials(self.config, self.team_id) == expected

        credentials = mock_validate.call_args.args[0]
        assert credentials.access_token == "access-1"
        assert credentials.team_member_id == "dbmid:1"

    @pytest.mark.parametrize(
        "failure",
        [ValueError("Integration not found: 7"), None],
        ids=["integration_missing", "access_token_missing"],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_dropbox_credentials")
    def test_validate_credentials_fails_cleanly_without_a_usable_connection(
        self, mock_validate: mock.MagicMock, failure: ValueError | None
    ) -> None:
        patcher = (
            mock.patch.object(DropboxSource, "get_oauth_integration", side_effect=failure)
            if failure is not None
            else self._patch_integration(access_token=None)
        )

        with patcher:
            is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error == "Connect a Dropbox account to continue."
        mock_validate.assert_not_called()

    @mock.patch(f"{_SOURCE_MODULE}.validate_dropbox_credentials")
    def test_validate_credentials_refuses_an_integration_from_another_provider(
        self, mock_validate: mock.MagicMock
    ) -> None:
        # The integration id is picked by whoever edits the source, so a same-team Slack (or any
        # other) connection must be rejected before its bearer token is handed to Dropbox.
        with self._patch_integration(kind="slack"):
            is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error == "Connect a Dropbox account to continue."
        mock_validate.assert_not_called()

    @mock.patch(f"{_SOURCE_MODULE}.dropbox_source")
    def test_source_for_pipeline_refuses_an_integration_from_another_provider(
        self, mock_dropbox_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.schema_name = "files"

        with self._patch_integration(kind="slack"):
            with pytest.raises(ValueError, match="Integration not found: 7"):
                self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        mock_dropbox_source.assert_not_called()

    @mock.patch(f"{_SOURCE_MODULE}.check_endpoint_access")
    def test_get_endpoint_permissions_delegates_to_the_probe(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = {"files": None, "team_events": "missing scope"}

        with self._patch_integration():
            results = self.source.get_endpoint_permissions(self.config, self.team_id, ["files", "team_events"])

        assert results == {"files": None, "team_events": "missing scope"}
        assert mock_check.call_args.args[1] == ["files", "team_events"]

    @mock.patch(f"{_SOURCE_MODULE}.check_endpoint_access")
    def test_get_endpoint_permissions_never_blocks_the_schema_picker(self, mock_check: mock.MagicMock) -> None:
        with mock.patch.object(DropboxSource, "get_oauth_integration", side_effect=ValueError("Integration not found")):
            results = self.source.get_endpoint_permissions(self.config, self.team_id, ["files", "team_events"])

        assert results == {"files": None, "team_events": None}
        mock_check.assert_not_called()

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DropboxResumeConfig

    @mock.patch(f"{_SOURCE_MODULE}.dropbox_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_dropbox_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.schema_name = "team_events"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-05-01T00:00:00Z"
        manager = mock.MagicMock()

        with self._patch_integration() as mock_get_integration:
            self.source.source_for_pipeline(self.config, manager, inputs)

        assert mock_get_integration.call_args.args == (7, self.team_id)
        kwargs = mock_dropbox_source.call_args.kwargs
        assert kwargs["endpoint"] == "team_events"
        assert kwargs["folder_path"] == "/Reports"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01T00:00:00Z"
        assert kwargs["credentials"].access_token == "access-1"

    @mock.patch(f"{_SOURCE_MODULE}.dropbox_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_dropbox_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.schema_name = "files"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-05-01T00:00:00Z"

        with self._patch_integration():
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_dropbox_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @mock.patch(f"{_SOURCE_MODULE}.dropbox_source")
    def test_source_for_pipeline_refuses_a_connection_with_no_access_token(
        self, mock_dropbox_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.schema_name = "files"

        with self._patch_integration(access_token=None):
            with pytest.raises(ValueError, match="Dropbox access token not found"):
                self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        mock_dropbox_source.assert_not_called()
