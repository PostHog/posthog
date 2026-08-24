from typing import Any

from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.settings import AUTH_USERS_TABLE
from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.source import FirebaseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.firebase import (
    FirebaseKeyFileConfig,
    FirebaseSourceConfig,
)

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

    def test_connection_target_fields_require_credential_re_entry_when_changed(self) -> None:
        # The Realtime Database host, the Firestore database selector and the Realtime Database
        # path allow-list all decide what the preserved service account key reads, so editing any
        # of them has to force key file re-entry.
        assert self.source.connection_host_fields == [
            "database_id",
            "realtime_database_url",
            "realtime_database_paths",
        ]

    def test_get_schemas_lists_discovered_tables_as_full_refresh(self) -> None:
        with mock.patch(_GET_TABLES, return_value=[AUTH_USERS_TABLE, "firestore_rooms"]):
            schemas = self.source.get_schemas(firebase_config(), team_id=1)

        assert [schema.name for schema in schemas] == [AUTH_USERS_TABLE, "firestore_rooms"]
        assert all(not schema.supports_incremental and not schema.supports_append for schema in schemas)

    def test_get_schemas_honors_the_name_filter(self) -> None:
        with mock.patch(_GET_TABLES, return_value=[AUTH_USERS_TABLE, "firestore_rooms"]):
            schemas = self.source.get_schemas(firebase_config(), team_id=1, names=["firestore_rooms"])

        assert [schema.name for schema in schemas] == ["firestore_rooms"]

    def test_source_for_pipeline_syncs_the_requested_table(self) -> None:
        manager = self.source.get_resumable_source_manager(source_inputs("firestore_rooms"))

        response = self.source.source_for_pipeline(firebase_config(), manager, source_inputs("firestore_rooms"))

        assert response.name == "firestore_rooms"
