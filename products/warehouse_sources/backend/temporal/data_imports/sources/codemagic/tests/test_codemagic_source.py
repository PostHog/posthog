import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.source import CodemagicSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codemagic import (
    CodemagicSourceConfig,
)


class TestCodemagicSource:
    def setup_method(self) -> None:
        self.source = CodemagicSource()
        self.team_id = 123
        self.config = CodemagicSourceConfig(api_token="test-token")

    @pytest.mark.parametrize(
        ("pinned_version", "expected_version"),
        [
            (None, "v3"),
            ("v1", "v1"),
            ("v3", "v3"),
        ],
    )
    def test_pinned_version_reaches_request_layer(self, pinned_version: str | None, expected_version: str) -> None:
        module = "products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.source"
        with (
            patch(f"{module}.validate_codemagic_credentials", return_value=(True, None)) as mock_validate,
            patch(f"{module}.codemagic_source") as mock_source,
        ):
            self.source.validate_credentials(self.config, self.team_id, api_version=pinned_version)
            inputs = MagicMock(api_version=self.source.resolve_api_version(pinned_version), schema_name="Builds")
            self.source.source_for_pipeline(self.config, MagicMock(), inputs)

        mock_validate.assert_called_once_with("test-token", expected_version)
        assert mock_source.call_args.kwargs["api_version"] == expected_version
