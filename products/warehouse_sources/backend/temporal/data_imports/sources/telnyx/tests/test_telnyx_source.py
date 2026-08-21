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

    def test_api_version_metadata(self) -> None:
        assert self.source.supported_versions == ("v2",)
        assert self.source.default_version == "v2"
        assert self.source.api_docs_url.startswith("https://")

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
