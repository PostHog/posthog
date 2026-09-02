import pytest
from unittest.mock import patch

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.source import BasetenSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.baseten import (
    BasetenSourceConfig,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.baseten.source"


class TestBasetenSourceConfig:
    def test_config_metadata(self) -> None:
        config = BasetenSource().get_source_config
        # Alpha + unreleased per the task's staged-rollout requirement.
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/baseten"


class TestBasetenSchemas:
    def test_lists_all_endpoints_as_full_refresh(self) -> None:
        schemas = BasetenSource().get_schemas(BasetenSourceConfig(api_key="k"), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No Baseten list endpoint exposes a server-side timestamp filter, so nothing is incremental.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)


class TestBasetenCredentials:
    @pytest.mark.parametrize(("valid", "expected_ok"), [(True, True), (False, False)])
    def test_validate_credentials(self, valid: bool, expected_ok: bool) -> None:
        with patch(f"{MODULE}.validate_baseten_credentials", return_value=valid):
            ok, error = BasetenSource().validate_credentials(BasetenSourceConfig(api_key="k"), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_non_retryable_errors_cover_403(self) -> None:
        errors = BasetenSource().get_non_retryable_errors()
        # Baseten answers a bad key with 403, not 401 — the 403 entry is the one that matters.
        assert any("403 Client Error" in key and "https://api.baseten.co" in key for key in errors)
