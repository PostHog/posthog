import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.fanout_reuse_flag import (
    is_fanout_warehouse_reuse_enabled,
)


class TestFanoutReuseFlagFailsClosed:
    # Fail-closed is the contract every consumer relies on: a falsy result keeps the legacy
    # parent-API path. If the try/except narrows, a flag-service blip becomes user-facing
    # 500s in the schema API and failed sync runs.

    def test_flag_service_error_returns_false(self):
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.fanout_reuse_flag.Team"
            ) as team_cls,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.fanout_reuse_flag.posthoganalytics.feature_enabled",
                side_effect=RuntimeError("flags endpoint down"),
            ),
        ):
            team_cls.objects.get.return_value.uuid = "u"
            assert is_fanout_warehouse_reuse_enabled(1) is False

    @pytest.mark.django_db
    def test_missing_team_returns_false(self):
        assert is_fanout_warehouse_reuse_enabled(999999999) is False
