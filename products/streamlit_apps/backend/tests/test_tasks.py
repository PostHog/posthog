from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team

from products.streamlit_apps.backend.logic.app_runtime import MAX_RESTART_COUNT, TTL_TIMEOUT_LAST_ERROR
from products.streamlit_apps.backend.models import StreamlitApp, StreamlitAppSandbox, StreamlitAppVersion
from products.streamlit_apps.backend.tasks.tasks import (
    _IDLE_TIMEOUT_MINUTES,
    _VERSION_RETENTION_DAYS,
    auto_restart_crashed_streamlit_sandboxes,
    prune_old_streamlit_app_versions,
    stop_idle_streamlit_sandboxes,
)


class _LifecycleTestMixin:
    """Shared helpers to spin up app + version + sandbox rows."""

    team: Team

    def _make_app(self, **kwargs) -> StreamlitApp:
        defaults = {"team": self.team, "name": "T"}
        defaults.update(kwargs)
        return StreamlitApp.objects.create(**defaults)

    def _make_version(self, app: StreamlitApp, number: int = 1, **kwargs) -> StreamlitAppVersion:
        defaults = {
            "app": app,
            "version_number": number,
            "zip_file": f"streamlit_apps/{app.team_id}/{app.id}/v{number}.zip",
            "zip_hash": f"hash_{number}",
        }
        defaults.update(kwargs)
        return StreamlitAppVersion.objects.create(**defaults)

    def _make_sandbox(self, app, version, *, status, last_activity_at=None, started_at=None, last_error=""):
        return StreamlitAppSandbox.objects.create(
            app=app,
            version=version,
            sandbox_id=f"sb_{app.short_id}",
            status=status,
            last_activity_at=last_activity_at,
            started_at=started_at,
            last_error=last_error,
        )


class TestStopIdleStreamlitSandboxes(_LifecycleTestMixin, BaseTest):
    @patch("products.streamlit_apps.backend.logic.app_runtime.AppRuntimeService")
    def test_idle_running_sandbox_gets_stopped(self, runtime_cls):
        app = self._make_app()
        v = self._make_version(app)
        idle_at = timezone.now() - timedelta(minutes=_IDLE_TIMEOUT_MINUTES + 1)
        self._make_sandbox(app, v, status=StreamlitAppSandbox.Status.RUNNING, last_activity_at=idle_at)

        stopped = stop_idle_streamlit_sandboxes()

        assert stopped == 1
        runtime_cls.return_value.stop_app.assert_called_once_with(app)

    @patch("products.streamlit_apps.backend.logic.app_runtime.AppRuntimeService")
    def test_fresh_running_sandbox_is_left_alone(self, runtime_cls):
        app = self._make_app()
        v = self._make_version(app)
        recent = timezone.now() - timedelta(minutes=_IDLE_TIMEOUT_MINUTES - 5)
        self._make_sandbox(app, v, status=StreamlitAppSandbox.Status.RUNNING, last_activity_at=recent)

        stopped = stop_idle_streamlit_sandboxes()

        assert stopped == 0
        runtime_cls.return_value.stop_app.assert_not_called()

    @patch("products.streamlit_apps.backend.logic.app_runtime.AppRuntimeService")
    def test_null_last_activity_falls_back_to_started_at(self, runtime_cls):
        """A sandbox booted long ago that received zero proxy traffic should
        still count as idle — otherwise `last_activity_at IS NULL` apps leak."""
        app = self._make_app()
        v = self._make_version(app)
        started = timezone.now() - timedelta(minutes=_IDLE_TIMEOUT_MINUTES + 1)
        self._make_sandbox(
            app,
            v,
            status=StreamlitAppSandbox.Status.RUNNING,
            last_activity_at=None,
            started_at=started,
        )

        stopped = stop_idle_streamlit_sandboxes()

        assert stopped == 1
        runtime_cls.return_value.stop_app.assert_called_once_with(app)

    @parameterized.expand(
        [
            (StreamlitAppSandbox.Status.STOPPED,),
            (StreamlitAppSandbox.Status.STOPPING,),
            (StreamlitAppSandbox.Status.STARTING,),
            (StreamlitAppSandbox.Status.ERROR,),
        ]
    )
    @patch("products.streamlit_apps.backend.logic.app_runtime.AppRuntimeService")
    def test_non_running_sandboxes_are_skipped(self, sandbox_status, runtime_cls):
        app = self._make_app()
        v = self._make_version(app)
        idle_at = timezone.now() - timedelta(minutes=_IDLE_TIMEOUT_MINUTES + 1)
        self._make_sandbox(app, v, status=sandbox_status, last_activity_at=idle_at)

        stopped = stop_idle_streamlit_sandboxes()

        assert stopped == 0
        runtime_cls.return_value.stop_app.assert_not_called()

    @patch("products.streamlit_apps.backend.logic.app_runtime.AppRuntimeService")
    def test_one_failure_does_not_block_other_stops(self, runtime_cls):
        """A flaky Modal call on one sandbox shouldn't strand the rest of the batch."""
        a = self._make_app(name="A")
        b = self._make_app(name="B")
        va, vb = self._make_version(a), self._make_version(b)
        idle_at = timezone.now() - timedelta(minutes=_IDLE_TIMEOUT_MINUTES + 1)
        self._make_sandbox(a, va, status=StreamlitAppSandbox.Status.RUNNING, last_activity_at=idle_at)
        self._make_sandbox(b, vb, status=StreamlitAppSandbox.Status.RUNNING, last_activity_at=idle_at)

        # Fail on A, succeed on B (order is non-deterministic; both legs must
        # be tolerated).
        def fake_stop(app):
            if app.name == "A":
                raise RuntimeError("Modal down")

        runtime_cls.return_value.stop_app.side_effect = fake_stop

        stopped = stop_idle_streamlit_sandboxes()
        assert stopped == 1
        assert runtime_cls.return_value.stop_app.call_count == 2


class TestAutoRestartCrashedStreamlitSandboxes(_LifecycleTestMixin, BaseTest):
    @patch("products.streamlit_apps.backend.tasks.run_streamlit_app_lifecycle.delay")
    def test_ttl_crash_triggers_restart(self, lifecycle_delay):
        app = self._make_app(restart_count=1)
        v = self._make_version(app)
        self._make_sandbox(app, v, status=StreamlitAppSandbox.Status.STOPPED, last_error=TTL_TIMEOUT_LAST_ERROR)

        restarted = auto_restart_crashed_streamlit_sandboxes()

        assert restarted == 1
        lifecycle_delay.assert_called_once_with(str(app.id), "restart", team_id=app.team_id)

    @patch("products.streamlit_apps.backend.tasks.run_streamlit_app_lifecycle.delay")
    def test_user_stopped_sandbox_is_not_restarted(self, lifecycle_delay):
        app = self._make_app()
        v = self._make_version(app)
        # Any last_error other than the TTL marker counts as non-crash.
        self._make_sandbox(app, v, status=StreamlitAppSandbox.Status.STOPPED, last_error="")

        restarted = auto_restart_crashed_streamlit_sandboxes()

        assert restarted == 0
        lifecycle_delay.assert_not_called()

    @patch("products.streamlit_apps.backend.tasks.run_streamlit_app_lifecycle.delay")
    def test_restart_count_cap_is_honored(self, lifecycle_delay):
        app = self._make_app(restart_count=MAX_RESTART_COUNT)
        v = self._make_version(app)
        self._make_sandbox(app, v, status=StreamlitAppSandbox.Status.STOPPED, last_error=TTL_TIMEOUT_LAST_ERROR)

        restarted = auto_restart_crashed_streamlit_sandboxes()

        assert restarted == 0
        lifecycle_delay.assert_not_called()

    @patch("products.streamlit_apps.backend.tasks.run_streamlit_app_lifecycle.delay")
    def test_deleted_app_is_skipped(self, lifecycle_delay):
        app = self._make_app(deleted=True)
        v = self._make_version(app)
        self._make_sandbox(app, v, status=StreamlitAppSandbox.Status.STOPPED, last_error=TTL_TIMEOUT_LAST_ERROR)

        restarted = auto_restart_crashed_streamlit_sandboxes()

        assert restarted == 0
        lifecycle_delay.assert_not_called()


class TestPruneOldStreamlitAppVersions(_LifecycleTestMixin, BaseTest):
    def _make_old_version(self, app, number, age_days):
        v = self._make_version(app, number)
        # auto_now_add can't be overridden in create(); update after the fact.
        StreamlitAppVersion.objects.filter(id=v.id).update(created_at=timezone.now() - timedelta(days=age_days))
        v.refresh_from_db()
        return v

    @patch("posthog.storage.object_storage")
    def test_prunes_old_non_active_version(self, mock_storage):
        app = self._make_app()
        v1 = self._make_old_version(app, 1, _VERSION_RETENTION_DAYS + 1)
        v2 = self._make_version(app, 2)
        app.active_version = v2
        app.save()

        pruned = prune_old_streamlit_app_versions()

        assert pruned == 1
        mock_storage.delete.assert_called_once_with(v1.zip_file)
        assert not StreamlitAppVersion.objects.filter(id=v1.id).exists()
        assert StreamlitAppVersion.objects.filter(id=v2.id).exists()

    @patch("posthog.storage.object_storage")
    def test_keeps_active_version_even_if_old(self, mock_storage):
        """Active version must survive pruning even past the retention window —
        an app whose owner ran it once and never updated should still work."""
        app = self._make_app()
        v1 = self._make_old_version(app, 1, _VERSION_RETENTION_DAYS + 30)
        app.active_version = v1
        app.save()

        pruned = prune_old_streamlit_app_versions()

        assert pruned == 0
        mock_storage.delete.assert_not_called()
        assert StreamlitAppVersion.objects.filter(id=v1.id).exists()

    @patch("posthog.storage.object_storage")
    def test_keeps_recent_non_active_version(self, mock_storage):
        app = self._make_app()
        self._make_old_version(app, 1, _VERSION_RETENTION_DAYS - 1)  # not yet old enough
        v2 = self._make_version(app, 2)
        app.active_version = v2
        app.save()

        pruned = prune_old_streamlit_app_versions()

        assert pruned == 0
        mock_storage.delete.assert_not_called()

    @patch("posthog.storage.object_storage")
    def test_skips_versions_on_deleted_apps(self, mock_storage):
        """Deleted-app cleanup is owned by cleanup_deleted_streamlit_app_zips —
        this task must not double-handle that path."""
        app = self._make_app(deleted=True)
        self._make_old_version(app, 1, _VERSION_RETENTION_DAYS + 1)

        pruned = prune_old_streamlit_app_versions()

        assert pruned == 0
        mock_storage.delete.assert_not_called()

    @patch("posthog.storage.object_storage")
    def test_storage_failure_keeps_row_for_retry(self, mock_storage):
        app = self._make_app()
        v1 = self._make_old_version(app, 1, _VERSION_RETENTION_DAYS + 1)
        v2 = self._make_version(app, 2)
        app.active_version = v2
        app.save()
        mock_storage.delete.side_effect = RuntimeError("S3 unavailable")

        pruned = prune_old_streamlit_app_versions()

        assert pruned == 0
        # Row survives so the next run can retry.
        assert StreamlitAppVersion.objects.filter(id=v1.id).exists()
