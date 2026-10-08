import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.source import ButtondownSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buttondown import (
    ButtondownSourceConfig,
)

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.source.validate_buttondown_credentials"
)
SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.source.buttondown_source"


class TestButtondownSource:
    def setup_method(self) -> None:
        self.source = ButtondownSource()
        self.team_id = 123
        self.config = ButtondownSourceConfig(api_key="bd-key")

    @pytest.mark.parametrize(
        "probe_result,schema_name,expected",
        [
            ((True, 200), None, (True, None)),
            ((False, 401), None, (False, "Invalid Buttondown API key")),
            # A 403 means a real key that can't read one endpoint, so it must not block setup.
            ((False, 403), None, (True, None)),
            ((False, 403), "emails", (False, "Invalid Buttondown API key")),
            ((False, None), None, (False, "Invalid Buttondown API key")),
        ],
    )
    def test_validate_credentials(
        self, probe_result: tuple[bool, int | None], schema_name: str | None, expected: tuple[bool, str | None]
    ) -> None:
        with mock.patch(VALIDATE_PATCH, return_value=probe_result) as mock_validate:
            assert self.source.validate_credentials(self.config, self.team_id, schema_name) == expected

        mock_validate.assert_called_once_with("bd-key", "2026-04-01")

    def test_source_for_pipeline_honors_a_pinned_api_version(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "emails"
        inputs.api_version = "2025-01-02"

        with mock.patch(SOURCE_PATCH) as mock_source:
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["api_version"] == "2025-01-02"
