from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sonarcloud import (
    SonarCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.source import SonarCloudSource


def _config() -> SonarCloudSourceConfig:
    return SonarCloudSourceConfig(token="tok", organization="org", region="eu")


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("bad_token", 401, None, False),
            ("forbidden_at_create", 403, None, True),
            ("forbidden_for_schema", 403, "issues", False),
            ("transport_error", 0, None, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        with patch.object(source_module, "validate_sonar_cloud_credentials", return_value=status):
            ok, _ = SonarCloudSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok
