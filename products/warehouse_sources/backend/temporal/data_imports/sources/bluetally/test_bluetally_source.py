from typing import Any

from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.source import BluetallySource


def _config(api_key: str = "key", tenant_id: str | None = None) -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.tenant_id = tenant_id
    return config


class TestValidateCredentials:
    def test_success(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.source.validate_bluetally_credentials",
            return_value=True,
        ) as mocked:
            ok, error = BluetallySource().validate_credentials(_config(tenant_id="7"), team_id=1)
        assert ok is True
        assert error is None
        mocked.assert_called_once_with("key", "7", "/assets")

    def test_failure(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.source.validate_bluetally_credentials",
            return_value=False,
        ):
            ok, error = BluetallySource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error is not None

    def test_probes_specific_endpoint_path(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.source.validate_bluetally_credentials",
            return_value=True,
        ) as mocked:
            BluetallySource().validate_credentials(_config(), team_id=1, schema_name="employees")
        mocked.assert_called_once_with("key", None, "/employees")
