from typing import Any

import pytest
from unittest import mock

import structlog

from posthog.schema import ReleaseStatus, SourceFieldFileUploadConfig, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.firebase import FirebaseResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.settings import AUTH_USERS_TABLE
from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.source import FirebaseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.firebase import (
    FirebaseKeyFileConfig,
    FirebaseSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_GET_TABLES = "products.warehouse_sources.backend.temporal.data_imports.sources.firebase.source.get_tables"
_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.firebase.source.validate_firebase_credentials"
)


def firebase_config(**overrides: Any) -> FirebaseSourceConfig:
    return FirebaseSourceConfig(
        key_file=FirebaseKeyFileConfig(
            project_id=overrides.pop("project_id", "demo-project"),
            private_key="-----BEGIN PRIVATE KEY-----",
            private_key_id="key-id",
            client_email="importer@demo-project.iam.gserviceaccount.com",
            token_uri="https://oauth2.googleapis.com/token",
        ),
        database_id=overrides.pop("database_id", None),
        realtime_database_url=overrides.pop("realtime_database_url", None),
        realtime_database_paths=overrides.pop("realtime_database_paths", None),
    )


def source_inputs(schema_name: str, **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": structlog.get_logger("firebase-test"),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestFirebaseSource:
    def setup_method(self) -> None:
        self.source = FirebaseSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.FIREBASE

    def test_source_is_released_in_alpha(self) -> None:
        config = self.source.get_source_config

        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_form_takes_a_service_account_key_and_optional_realtime_database_settings(self) -> None:
        fields = {field.name: field for field in self.source.get_source_config.fields}

        assert isinstance(fields["key_file"], SourceFieldFileUploadConfig)
        assert fields["key_file"].required is True
        for name in ("database_id", "realtime_database_url", "realtime_database_paths"):
            field = fields[name]
            assert isinstance(field, SourceFieldInputConfig)
            assert field.required is False

    def test_connection_target_fields_require_credential_re_entry_when_changed(self) -> None:
        # The Realtime Database host, the Firestore database selector and the Realtime Database
        # path allow-list all decide what the preserved service account key reads, so editing any
        # of them has to force key file re-entry.
        assert self.source.connection_host_fields == [
            "database_id",
            "realtime_database_url",
            "realtime_database_paths",
        ]

    def test_auth_users_columns_are_documented(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert "localId" in descriptions[AUTH_USERS_TABLE]["columns"]

    def test_get_schemas_lists_discovered_tables_as_full_refresh(self) -> None:
        with mock.patch(_GET_TABLES, return_value=[AUTH_USERS_TABLE, "firestore_rooms"]):
            schemas = self.source.get_schemas(firebase_config(), team_id=1)

        assert [schema.name for schema in schemas] == [AUTH_USERS_TABLE, "firestore_rooms"]
        assert all(not schema.supports_incremental and not schema.supports_append for schema in schemas)

    def test_get_schemas_honors_the_name_filter(self) -> None:
        with mock.patch(_GET_TABLES, return_value=[AUTH_USERS_TABLE, "firestore_rooms"]):
            schemas = self.source.get_schemas(firebase_config(), team_id=1, names=["firestore_rooms"])

        assert [schema.name for schema in schemas] == ["firestore_rooms"]

    @pytest.mark.parametrize(
        "database_id,expected",
        [(None, "(default)"), ("", "(default)"), ("  ", "(default)"), ("analytics", "analytics")],
    )
    def test_blank_database_id_falls_back_to_the_default_database(self, database_id: Any, expected: str) -> None:
        with mock.patch(_VALIDATE, return_value=(True, None)) as validate:
            self.source.validate_credentials(firebase_config(database_id=database_id), team_id=1)

        assert validate.call_args.args[0].database_id == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, ()),
            ("", ()),
            ("rooms", ("rooms",)),
            (" rooms , /messages/lobby/ ,, rooms ", ("rooms", "messages/lobby")),
        ],
    )
    def test_realtime_database_paths_are_split_and_deduplicated(self, raw: Any, expected: tuple[str, ...]) -> None:
        with mock.patch(_VALIDATE, return_value=(True, None)) as validate:
            self.source.validate_credentials(firebase_config(realtime_database_paths=raw), team_id=1)

        assert validate.call_args.args[0].realtime_database_paths == expected

    def test_validate_credentials_passes_through_the_transport_result(self) -> None:
        with mock.patch(_VALIDATE, return_value=(False, "nope")):
            assert self.source.validate_credentials(firebase_config(), team_id=1) == (False, "nope")

    def test_resume_manager_is_bound_to_the_firebase_cursor(self) -> None:
        manager = self.source.get_resumable_source_manager(source_inputs(AUTH_USERS_TABLE))

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FirebaseResumeConfig

    def test_source_for_pipeline_syncs_the_requested_table(self) -> None:
        manager = self.source.get_resumable_source_manager(source_inputs("firestore_rooms"))

        response = self.source.source_for_pipeline(firebase_config(), manager, source_inputs("firestore_rooms"))

        assert response.name == "firestore_rooms"

    def test_permanent_auth_failures_are_not_retried(self) -> None:
        errors = self.source.get_non_retryable_errors()

        assert "error=invalid_grant" in errors
        assert "403 Client Error: Forbidden" in errors
        assert "message=CONFIGURATION_NOT_FOUND" in errors
