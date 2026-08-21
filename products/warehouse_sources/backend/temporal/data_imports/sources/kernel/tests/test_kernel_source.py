import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kernel import KernelSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kernel.source import KernelSource

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.kernel.source"


class TestKernelSource:
    def setup_method(self) -> None:
        self.source = KernelSource()
        self.team_id = 123
        self.config = KernelSourceConfig(api_key="sk_test")

    def test_generated_config_parses_api_key(self) -> None:
        # Guards the hand-checked generated_configs.py edit: the form field must map to `api_key`.
        config = KernelSourceConfig.from_dict({"api_key": "sk_123"})
        assert config.api_key == "sk_123"

    @pytest.mark.parametrize(
        "probe_result, schema_name, expected_valid",
        [
            # Valid token.
            ((True, 200), None, True),
            # Bad token is always rejected.
            ((False, 401), None, False),
            # A 403 at source-create means valid token / missing scope - do not block creation.
            ((False, 403), None, True),
            # A 403 while probing a specific schema is a real scope failure for that table.
            ((False, 403), "invocations", False),
            ((False, None), None, False),
        ],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_kernel_credentials")
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        probe_result: tuple[bool, int | None],
        schema_name: str | None,
        expected_valid: bool,
    ) -> None:
        mock_validate.return_value = probe_result

        is_valid, _error = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        mock_validate.assert_called_once_with("sk_test")
