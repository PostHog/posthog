from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    ZapierSupportedStorageSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zapier_supported_storage.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zapier_supported_storage.source import (
    ZapierSupportedStorageSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.zapier_supported_storage.source"


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "records",
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


class TestZapierSupportedStorageSource:
    def setup_method(self) -> None:
        self.source = ZapierSupportedStorageSource()
        self.team_id = 123
        self.config = ZapierSupportedStorageSourceConfig(secret="abcdef01-2345-4678-9abc-def012345678")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ZAPIERSUPPORTEDSTORAGE

    def test_get_source_config_single_secret_field(self) -> None:
        config = self.source.get_source_config

        assert config.releaseStatus == ReleaseStatus.ALPHA
        # docsUrl must match the doc filename so the posthog.com page resolves.
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/zapier-supported-storage"

        fields = [f for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert [f.name for f in fields] == ["secret"]
        secret = fields[0]
        # The store secret is the sole credential and must be handled as a password/secret.
        assert secret.type == SourceFieldInputConfigType.PASSWORD
        assert secret.secret is True
        assert secret.required is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "400 Client Error"])
    def test_non_retryable_errors_cover_auth_and_malformed_secret(self, expected_key: str) -> None:
        keys = self.source.get_non_retryable_errors()
        assert any(expected_key in k for k in keys)

    def test_get_schemas_single_full_refresh_table(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS) == {"records"}
        # The store has no timestamps, so nothing supports incremental or append.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["records"])[0].name == "records"
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_without_credentials(self) -> None:
        # A static endpoint catalog opts into public docs; get_documented_tables must succeed with
        # no credentials and surface the records table as full refresh.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert [t["name"] for t in tables] == ["records"]
        assert "Full refresh" in tables[0]["sync_methods"]

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        assert set(self.source.get_canonical_descriptions().keys()) == set(ENDPOINTS)

    @mock.patch(f"{MODULE}.validate_zapier_supported_storage_credentials")
    def test_validate_credentials_delegates_with_secret(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        result = self.source.validate_credentials(self.config, self.team_id)

        assert result == (True, None)
        mock_validate.assert_called_once_with(self.config.secret)

    @mock.patch(f"{MODULE}.zapier_supported_storage_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="records", team_id=99)

        self.source.source_for_pipeline(self.config, inputs)

        mock_source.assert_called_once_with(
            secret=self.config.secret,
            endpoint="records",
            logger=inputs.logger,
        )
