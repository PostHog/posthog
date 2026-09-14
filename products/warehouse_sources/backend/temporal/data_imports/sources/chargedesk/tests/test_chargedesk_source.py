from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.chargedesk import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.chargedesk.source import ChargedeskSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.chargedesk import (
    ChargedeskSourceConfig,
)


def _config() -> ChargedeskSourceConfig:
    return ChargedeskSourceConfig(api_key="sk_test")


class TestChargedeskSourceConfig:
    def test_single_secret_api_key_field(self) -> None:
        fields = ChargedeskSource().get_source_config.fields
        assert len(fields) == 1
        api_key_field = fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        # The secret key must be stored as a password/secret, never plain text.
        assert api_key_field.secret is True

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog, so the public docs can render the table list.
        assert ChargedeskSource.lists_tables_without_credentials is True


class TestGetSchemas:
    def test_incremental_fields_use_resource_timestamp(self) -> None:
        schemas = {s.name: s for s in ChargedeskSource().get_schemas(_config(), team_id=1)}
        assert schemas["charges"].incremental_fields[0]["field"] == "occurred"
        # Customers/subscriptions track the creation timestamp column that the row actually carries.
        assert schemas["customers"].incremental_fields[0]["field"] == "first_seen"
        assert schemas["subscriptions"].incremental_fields[0]["field"] == "first_seen"


class TestValidateCredentials:
    def test_valid_key(self) -> None:
        with patch.object(source_module, "validate_chargedesk_credentials", return_value=True):
            ok, error = ChargedeskSource().validate_credentials(_config(), team_id=1)
        assert ok is True
        assert error is None

    def test_invalid_key(self) -> None:
        with patch.object(source_module, "validate_chargedesk_credentials", return_value=False):
            ok, error = ChargedeskSource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error is not None


class TestSourceForPipeline:
    def _inputs(self, **overrides: Any) -> MagicMock:
        inputs = MagicMock()
        inputs.schema_name = "charges"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1000
        inputs.db_incremental_field_earliest_value = 500
        for key, value in overrides.items():
            setattr(inputs, key, value)
        return inputs

    def test_plumbs_incremental_values_through(self) -> None:
        captured: dict[str, Any] = {}

        def _fake_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "response"

        with patch.object(source_module, "chargedesk_source", side_effect=_fake_source):
            ChargedeskSource().source_for_pipeline(_config(), MagicMock(), self._inputs())

        assert captured["endpoint"] == "charges"
        assert captured["api_key"] == "sk_test"
        assert captured["team_id"] is not None
        assert captured["job_id"] is not None
        assert captured["db_incremental_field_last_value"] == 1000
        assert captured["db_incremental_field_earliest_value"] == 500

    def test_non_incremental_run_passes_no_watermark(self) -> None:
        captured: dict[str, Any] = {}

        def _fake_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "response"

        with patch.object(source_module, "chargedesk_source", side_effect=_fake_source):
            ChargedeskSource().source_for_pipeline(
                _config(), MagicMock(), self._inputs(should_use_incremental_field=False)
            )

        assert captured["db_incremental_field_last_value"] is None
        assert captured["db_incremental_field_earliest_value"] is None


if __name__ == "__main__":
    pytest.main([__file__])
