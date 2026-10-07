import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.ahrefs.source import AhrefsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ahrefs import AhrefsSourceConfig


@pytest.mark.parametrize("project_id", ["", "0", "-1", "1.5", "https://example.com/123", "１２３", " 123 "])
def test_invalid_project_id_prevents_probe(project_id: str) -> None:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.ahrefs.source.validate_ahrefs_credentials"
    ) as validate:
        valid, message = AhrefsSource().validate_credentials(
            AhrefsSourceConfig(api_key="test-key", project_id=project_id), 1
        )
    assert valid is False
    assert message == "Enter a positive Site Audit project ID from your Ahrefs project URL."
    validate.assert_not_called()


@pytest.mark.parametrize("project_id", ["123", "00123"])
def test_valid_project_id_reaches_probe(project_id: str) -> None:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.ahrefs.source.validate_ahrefs_credentials",
        return_value=(True, None),
    ) as validate:
        assert AhrefsSource().validate_credentials(
            AhrefsSourceConfig(api_key="test-key", project_id=project_id), 1
        ) == (
            True,
            None,
        )
    validate.assert_called_once_with("test-key")
