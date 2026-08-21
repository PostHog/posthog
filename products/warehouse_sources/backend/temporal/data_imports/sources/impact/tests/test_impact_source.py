from typing import Optional

from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.impact import ImpactSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.impact import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.impact.source import ImpactSource


class TestImpactSourceClass:
    @parameterized.expand(
        [
            ("valid", True, True, None),
            ("invalid", False, False, "Invalid Impact.com Account SID or Auth Token"),
        ]
    )
    def test_validate_credentials(self, _name: str, api_result: bool, ok: bool, err: Optional[str]) -> None:
        with patch.object(source_module, "validate_impact_credentials", return_value=api_result):
            result = ImpactSource().validate_credentials(ImpactSourceConfig(account_sid="s", auth_token="t"), team_id=1)
        assert result == (ok, err)

    def test_default_version_is_14(self) -> None:
        assert ImpactSource.default_version == "14"
        assert ImpactSource.supported_versions == ("v1", "14")

    @parameterized.expand(
        [
            ("unpinned_resolves_to_default", None, "14"),
            ("legacy_pin_honored", "v1", "v1"),
        ]
    )
    def test_validate_credentials_passes_resolved_version(self, _name: str, pin: Optional[str], expected: str) -> None:
        with patch.object(source_module, "validate_impact_credentials", return_value=True) as mock_validate:
            ImpactSource().validate_credentials(
                ImpactSourceConfig(account_sid="s", auth_token="t"), team_id=1, api_version=pin
            )
        assert mock_validate.call_args.args[2] == expected
