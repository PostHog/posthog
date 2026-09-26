from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.medusa import MedusaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.medusa.source import MedusaSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.medusa.source"


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "Orders",
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


class TestMedusaSource:
    def setup_method(self) -> None:
        self.source = MedusaSource()
        self.team_id = 123
        self.config = MedusaSourceConfig(base_url="https://store.example.com", api_key="sk_test")

    def test_base_url_is_a_connection_host_field(self) -> None:
        # Changing base_url must force the API key to be re-entered, so the stored key is
        # never sent to a freshly-specified host.
        assert self.source.connection_host_fields == ["base_url"]

    @pytest.mark.parametrize(
        "base_url",
        [
            "",
            "http://store.example.com",
            "https://user:pass@store.example.com",
        ],
    )
    def test_validate_credentials_rejects_unsafe_urls_before_probing(self, base_url: str) -> None:
        config = MedusaSourceConfig(base_url=base_url, api_key="sk_test")
        with mock.patch(f"{SOURCE_MODULE}.validate_medusa_credentials") as mock_probe:
            is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert message
        mock_probe.assert_not_called()

    def test_validate_credentials_rejects_disallowed_hosts_before_probing(self) -> None:
        with (
            mock.patch.object(MedusaSource, "is_database_host_valid", return_value=(False, "Host is not allowed")),
            mock.patch(f"{SOURCE_MODULE}.validate_medusa_credentials") as mock_probe,
        ):
            is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert (is_valid, message) == (False, "Host is not allowed")
        mock_probe.assert_not_called()

    @pytest.mark.parametrize(
        ("probe_result", "expected_valid", "expected_message_part"),
        [
            ((True, 200), True, None),
            ((False, 401), False, "secret API key"),
            ((False, 403), False, "secret API key"),
            ((False, None), False, "Couldn't connect"),
            ((False, 500), False, "Couldn't connect"),
        ],
    )
    def test_validate_credentials_maps_probe_results(
        self,
        probe_result: tuple[bool, int | None],
        expected_valid: bool,
        expected_message_part: str | None,
    ) -> None:
        with (
            mock.patch.object(MedusaSource, "is_database_host_valid", return_value=(True, None)),
            mock.patch(f"{SOURCE_MODULE}.validate_medusa_credentials", return_value=probe_result),
        ):
            is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_message_part is None:
            assert message is None
        else:
            assert message is not None and expected_message_part in message

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        manager = mock.MagicMock()
        with pytest.raises(ValueError, match="Unknown Medusa schema"):
            self.source.source_for_pipeline(self.config, manager, _make_inputs(schema_name="Fulfillments"))
