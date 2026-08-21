from typing import Any

from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.source import FireworksAISource


def _config(api_key: str = "fw_test", account_id: str = "my-account") -> Any:
    return source_module.FireworksAISourceConfig(api_key=api_key, account_id=account_id)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("account_not_found", 404, None, False),
            ("forbidden_at_create_is_accepted", 403, None, True),
            ("forbidden_for_schema_is_rejected", 403, "models", False),
            ("unexpected", 500, None, False),
        ]
    )
    def test_status_code_mapping(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        with patch.object(source_module, "get_status_code", return_value=status):
            ok, _err = FireworksAISource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok

    def test_invalid_account_id_rejected_without_probe(self) -> None:
        with patch.object(source_module, "get_status_code") as mock_probe:
            ok, err = FireworksAISource().validate_credentials(_config(account_id="bad id!"), team_id=1)
        assert ok is False
        assert err is not None
        mock_probe.assert_not_called()

    def test_pasted_resource_prefix_is_normalized_before_probe(self) -> None:
        with patch.object(source_module, "get_status_code", return_value=200) as mock_probe:
            ok, _err = FireworksAISource().validate_credentials(_config(account_id="accounts/my-account"), team_id=1)
        assert ok is True
        assert mock_probe.call_args.args == ("fw_test", "my-account", None)

    def test_transport_failure_returns_actionable_error(self) -> None:
        with patch.object(source_module, "get_status_code", side_effect=Exception("boom")):
            ok, err = FireworksAISource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert err is not None
