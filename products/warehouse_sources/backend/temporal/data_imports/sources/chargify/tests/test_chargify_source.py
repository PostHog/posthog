from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.chargify.source import ChargifySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.chargify import (
    ChargifySourceConfig,
)


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "Customers",
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


class TestChargifySource:
    def setup_method(self) -> None:
        self.source = ChargifySource()
        self.team_id = 123
        self.config = ChargifySourceConfig(api_key="test-key", subdomain="acme")

    @pytest.mark.parametrize(
        ("subdomain", "creds_valid", "expected_valid", "expected_message"),
        [
            ("acme", True, True, None),
            ("acme", False, False, "Invalid Chargify credentials"),
            ("has spaces", True, False, "Chargify site subdomain is invalid"),
            ("bad/slash", True, False, "Chargify site subdomain is invalid"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chargify.source.validate_chargify_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        subdomain: str,
        creds_valid: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = creds_valid
        config = ChargifySourceConfig(api_key="test-key", subdomain=subdomain)

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message

    def test_validate_credentials_skips_api_call_for_bad_subdomain(self) -> None:
        # An obviously malformed subdomain must fail before any network call is attempted.
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.chargify.source.validate_chargify_credentials"
        ) as mock_validate:
            config = ChargifySourceConfig(api_key="test-key", subdomain="bad domain")
            is_valid, _ = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        mock_validate.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.chargify.source.chargify_source")
    def test_source_for_pipeline_partitions_on_created_at(self, mock_source: mock.MagicMock) -> None:
        # A stable creation timestamp partitions the table; using created_at (never updated_at)
        # keeps partitions from being rewritten on every sync.
        response = self.source.source_for_pipeline(
            self.config, mock.MagicMock(spec=ResumableSourceManager), _make_inputs(schema_name="Invoices")
        )

        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["created_at"]
