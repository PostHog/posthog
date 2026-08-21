from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.source import CoralogixSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coralogix import (
    CoralogixSourceConfig,
)


def _config(
    api_key: str = "test-key", domain: str = "eu2.coralogix.com", tier: str = "frequent_search"
) -> CoralogixSourceConfig:
    return CoralogixSourceConfig.from_dict({"api_key": api_key, "domain": domain, "tier": tier})


class TestCoralogixSource:
    @parameterized.expand([("valid", True), ("invalid", False)])
    def test_validate_credentials(self, _name: str, probe_result: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.source.validate_coralogix_credentials",
            return_value=probe_result,
        ) as probe:
            valid, error = CoralogixSource().validate_credentials(_config("key-1", "coralogix.us"), team_id=1)

        probe.assert_called_once_with("key-1", "coralogix.us")
        assert valid is probe_result
        assert (error is None) is probe_result

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.eu2.coralogix.com/api/v1/dataprime/query",),
            ("403 Client Error: Forbidden for url: https://api.coralogix.us/api/v1/dataprime/query",),
        ]
    )
    def test_non_retryable_errors_match_credential_failures(self, raised_message: str) -> None:
        # A revoked key or wrong-cluster domain must permanently fail the sync rather than retry
        # forever; the matcher keys on the stable status text + URL prefix shared by every domain.
        errors = CoralogixSource().get_non_retryable_errors()
        assert any(pattern in raised_message and friendly for pattern, friendly in errors.items())
