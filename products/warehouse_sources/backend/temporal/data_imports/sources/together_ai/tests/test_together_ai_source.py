from typing import Any

from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai.source import TogetherAISource


def _config(api_key: str = "together_test") -> Any:
    return source_module.TogetherAISourceConfig(api_key=api_key)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_at_create_is_accepted", 403, None, True),
            ("forbidden_for_schema_is_rejected", 403, "fine_tunes", False),
            ("unexpected", 500, None, False),
        ]
    )
    def test_status_code_mapping(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        with patch.object(source_module, "get_status_code", return_value=status):
            ok, _err = TogetherAISource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok

    def test_probes_requested_schema_endpoint(self) -> None:
        with patch.object(source_module, "get_status_code", return_value=200) as mock_probe:
            TogetherAISource().validate_credentials(_config(), team_id=1, schema_name="batches")
        assert mock_probe.call_args.args == ("together_test", "batches")

    def test_transport_failure_returns_actionable_error(self) -> None:
        with patch.object(source_module, "get_status_code", side_effect=Exception("boom")):
            ok, err = TogetherAISource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert err is not None
