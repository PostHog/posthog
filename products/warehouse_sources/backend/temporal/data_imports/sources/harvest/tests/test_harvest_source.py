from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.harvest import (
    HarvestSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harvest.settings import HARVEST_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.harvest.source import HarvestSource

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.harvest.source.validate_harvest_credentials"
)
SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.harvest.source.harvest_source"


def _config() -> HarvestSourceConfig:
    return HarvestSourceConfig(account_id="123456", access_token="pat-secret")


class TestHarvestSource:
    def test_api_version_pins_the_path_the_code_calls(self) -> None:
        assert HarvestSource.supported_versions == ("v2",)
        assert HarvestSource.default_version == "v2"

    @parameterized.expand(
        [
            ("valid", True, None, True, None),
            ("invalid", False, 401, False, "Invalid Harvest account ID"),
            ("no_scope", False, 403, False, "does not have permission"),
            ("unreachable", False, None, False, "Could not reach Harvest"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, probe_ok: bool, status: int | None, expected_ok: bool, expected_error: str | None
    ) -> None:
        # Distinct messages keep a 403 (missing permission) and an unreachable probe from both
        # reading as "bad credentials", which would send the user chasing the wrong fix.
        with patch(VALIDATE_PATCH, return_value=(probe_ok, status)):
            ok, error = HarvestSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        if expected_error is None:
            assert error is None
        else:
            assert error is not None and expected_error in error

    def test_partition_keys_are_creation_time_only(self) -> None:
        # An `updated_at` partition key would rewrite every partition on each sync.
        partition_keys = {c.partition_key for c in HARVEST_ENDPOINTS.values() if c.partition_key}
        assert partition_keys == {"created_at"}

    def test_page_size_stays_within_the_api_cap(self) -> None:
        # Harvest rejects per_page above 2000 with a 422.
        assert all(0 < c.page_size <= 2000 for c in HARVEST_ENDPOINTS.values())
