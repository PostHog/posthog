import pytest
from unittest.mock import MagicMock, patch

import django.db

from posthog.models.team.team import Team

from products.warehouse_sources.backend.temporal.data_imports.sources.common.fanout_reuse_flag import (
    is_fanout_warehouse_reuse_enabled,
)


class TestFanoutReuseFlagFailsClosed:
    # Fail-closed is the contract every consumer relies on: a falsy result keeps the legacy
    # parent-API path. If the try/except narrows, a flag-service blip becomes failed sync runs.

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

    def test_transient_db_connection_drop_retries_then_succeeds(self):
        # A pooled connection dropped once (pgbouncer recycle) must not be reported as an
        # exception nor fail the gate closed — the retry should recover it transparently.
        mock_team = MagicMock()
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.fanout_reuse_flag.Team"
            ) as team_cls,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.fanout_reuse_flag.posthoganalytics.feature_enabled",
                return_value=True,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.fanout_reuse_flag.capture_exception"
            ) as mock_capture,
        ):
            team_cls.DoesNotExist = Team.DoesNotExist
            team_cls.objects.only.return_value.get.side_effect = [
                django.db.OperationalError("connection closed"),
                mock_team,
            ]
            assert is_fanout_warehouse_reuse_enabled(1) is True
            mock_capture.assert_not_called()

    def test_persistent_db_connection_drop_returns_false(self):
        # A second failure after the retry means a genuinely degraded DB, not a transient
        # blip — this should still be reported and the gate should still fail closed.
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.fanout_reuse_flag.Team"
            ) as team_cls,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.fanout_reuse_flag.capture_exception"
            ) as mock_capture,
        ):
            team_cls.DoesNotExist = Team.DoesNotExist
            team_cls.objects.only.return_value.get.side_effect = django.db.OperationalError("connection closed")
            assert is_fanout_warehouse_reuse_enabled(1) is False
            mock_capture.assert_called_once()
