from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.maxio import MaxioSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.maxio.source import MaxioSource


def _config(**overrides: Any) -> MaxioSourceConfig:
    defaults: dict[str, Any] = {"subdomain": "acme", "api_key": "test-key", "region": "us"}
    defaults.update(overrides)
    return MaxioSourceConfig(**defaults)


def _inputs(schema_name: str, should_use_incremental_field: bool = False, **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 123,
        "should_use_incremental_field": should_use_incremental_field,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestMaxioSource:
    def test_connection_host_fields_cover_host_determining_fields(self) -> None:
        assert MaxioSource().connection_host_fields == ["subdomain", "region"]

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = MaxioSource().get_schemas(_config(), team_id=123, names=["customers", "invoices"])

        assert {schema.name for schema in schemas} == {"customers", "invoices"}

    @pytest.mark.parametrize("subdomain", ["bad domain", "acme!", ""])
    def test_validate_credentials_rejects_invalid_subdomain_without_network(self, subdomain: str) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.maxio.source.validate_maxio_credentials"
        ) as mock_validate:
            valid, error = MaxioSource().validate_credentials(_config(subdomain=subdomain), team_id=123)

        assert valid is False
        assert error == "Maxio subdomain is incorrect"
        mock_validate.assert_not_called()

    @pytest.mark.parametrize(("result", "message"), [((True, None), None), ((False, "nope"), "nope")])
    def test_validate_credentials_delegates_to_api_probe(
        self, result: tuple[bool, str | None], message: str | None
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.maxio.source.validate_maxio_credentials",
            return_value=result,
        ) as mock_validate:
            valid, error = MaxioSource().validate_credentials(
                _config(subdomain="https://acme.chargify.com/"), team_id=123
            )

        assert (valid, error) == result
        # A pasted URL must reach the probe as the normalized bare subdomain.
        mock_validate.assert_called_once_with("test-key", "acme", "us")


class TestMaxioSourceForPipeline:
    def test_incremental_last_value_only_passed_when_enabled(self) -> None:
        source = MaxioSource()
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = _inputs("subscriptions", should_use_incremental_field=False)
        inputs.db_incremental_field_last_value = "2024-05-01"

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.maxio.source.maxio_source"
        ) as mock_source:
            mock_source.return_value.name = "subscriptions"
            mock_source.return_value.column_hints = None
            source.source_for_pipeline(_config(), manager, inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
