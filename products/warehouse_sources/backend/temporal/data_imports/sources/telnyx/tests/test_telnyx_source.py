from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.telnyx import TelnyxSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.telnyx.settings import ENDPOINTS, TELNYX_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.telnyx.source import TelnyxSource

INCREMENTAL_ENDPOINTS = {name for name, endpoint in TELNYX_ENDPOINTS.items() if endpoint.incremental_field}
FULL_REFRESH_ENDPOINTS = set(ENDPOINTS) - INCREMENTAL_ENDPOINTS


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "MessagingDetailRecords",
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


class TestTelnyxSource:
    def setup_method(self) -> None:
        self.source = TelnyxSource()
        self.team_id = 123
        self.config = TelnyxSourceConfig(api_key="test-key")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs table list can render.
        assert self.source.lists_tables_without_credentials is True

    def test_api_version_metadata(self) -> None:
        assert self.source.supported_versions == ("v2",)
        assert self.source.default_version == "v2"
        assert self.source.api_docs_url.startswith("https://")

    @pytest.mark.parametrize("endpoint", sorted(FULL_REFRESH_ENDPOINTS))
    def test_get_schemas_full_refresh_endpoints(self, endpoint: str) -> None:
        # No documented server-side timestamp filter for these record types, so they must not
        # falsely advertise incremental support.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # Every advertised endpoint should have a curated description so the docs and the AI
        # agent get authoritative metadata instead of paying for LLM enrichment.
        assert set(self.source.get_canonical_descriptions().keys()) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        ("creds_valid", "expected_valid", "expected_message"),
        [
            (True, True, None),
            (False, False, "Invalid Telnyx API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.telnyx.source.validate_telnyx_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        creds_valid: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = creds_valid

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.telnyx.source.telnyx_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="VerifyDetailRecords", team_id=99, job_id="job-xyz")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key="test-key",
            endpoint="VerifyDetailRecords",
            team_id=99,
            job_id="job-xyz",
            resumable_source_manager=manager,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert response.primary_keys == TELNYX_ENDPOINTS["VerifyDetailRecords"].primary_key

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_for_pipeline_partitions_on_stable_field(self, endpoint: str) -> None:
        # Every partition key is a creation/start/invocation timestamp, never an
        # `updated_at`-like field that would rewrite partitions on every sync.
        with mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.telnyx.source.telnyx_source"):
            response = self.source.source_for_pipeline(
                self.config, mock.MagicMock(spec=ResumableSourceManager), _make_inputs(schema_name=endpoint)
            )

        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == [TELNYX_ENDPOINTS[endpoint].partition_key]
