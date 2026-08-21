from typing import Optional

from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.impactpartner import (
    ImpactPartnerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.impact_partner import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.impact_partner.source import ImpactPartnerSource


class TestImpactPartnerSourceClass:
    @parameterized.expand(
        [
            ("valid", True, True, None),
            ("invalid", False, False, "Invalid Impact.com Account SID or Auth Token"),
        ]
    )
    def test_validate_credentials(self, _name: str, api_result: bool, ok: bool, err: Optional[str]) -> None:
        with patch.object(
            source_module, "validate_impact_partner_credentials", return_value=api_result
        ) as mock_validate:
            result = ImpactPartnerSource().validate_credentials(
                ImpactPartnerSourceConfig(account_sid="s", auth_token="t"), team_id=1
            )
        assert result == (ok, err)
        # An unpinned source instance validates against the default vendor API version.
        assert mock_validate.call_args.args[2] == "16"
