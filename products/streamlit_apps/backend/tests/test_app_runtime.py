import zipfile
from datetime import timedelta
from io import BytesIO

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from products.streamlit_apps.backend.logic.app_runtime import (
    MAX_RESTART_COUNT,
    RESTART_COUNT_STABILITY_SECONDS,
    AppRuntimeConcurrencyError,
    AppRuntimeError,
    AppRuntimeService,
    _get_sandbox_callback_url,
)
from products.streamlit_apps.backend.models import StreamlitApp, StreamlitAppSandbox, StreamlitAppVersion


def _make_zip_bytes(files: dict[str, str]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _make_mock_sandbox():
    sandbox = MagicMock()
    sandbox.id = "modal-sandbox-123"
    sandbox.execute.return_value = MagicMock(exit_code=0, stdout="200", stderr="")
    sandbox.write_file.return_value = MagicMock(exit_code=0)
    sandbox.create_snapshot.return_value = "snapshot-abc"
    return sandbox


def _make_mock_sandbox_class(sandbox=None):
    if sandbox is None:
        sandbox = _make_mock_sandbox()
    cls = MagicMock()
    cls.create.return_value = sandbox
    cls.get_by_id.return_value = sandbox
    return cls


@patch("products.streamlit_apps.backend.logic.app_runtime._wait_for_health", return_value=True)
@patch("products.streamlit_apps.backend.logic.app_runtime.get_sandbox_class")
class TestAppRuntimeStartApp(BaseTest):
    def _create_app_with_version(self, snapshot_id=None):
        app = StreamlitApp.objects.create(team=self.team, name="Test App", created_by=self.user)
        version = StreamlitAppVersion.objects.create(
            app=app,
            version_number=1,
            zip_file="s3://bucket/app.zip",
            zip_hash="abc123",
            snapshot_id=snapshot_id,
        )
        app.active_version = version
        app.save(update_fields=["active_version"])
        return app, version

    def test_cold_start_creates_sandbox_and_snapshot(self, mock_get_sandbox_class, _mock_wait):
        mock_sandbox = _make_mock_sandbox()
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, version = self._create_app_with_version()
        zip_content = _make_zip_bytes({"app.py": "import streamlit as st"})

        service = AppRuntimeService()
        record = service.start_app(app, zip_content=zip_content)

        assert record.status == StreamlitAppSandbox.Status.RUNNING
        assert record.sandbox_id == "modal-sandbox-123"
        mock_sandbox.write_file.assert_called()
        mock_sandbox.create_snapshot.assert_called_once()

        version.refresh_from_db()
        assert version.snapshot_id is not None
        assert version.snapshot_created_at is not None

        from products.tasks.backend.facade import api as tasks_facade

        snapshot = tasks_facade.get_sandbox_snapshot(version.snapshot_id)
        assert snapshot is not None
        assert snapshot.external_id == "snapshot-abc"
        assert snapshot.status == tasks_facade.SandboxSnapshotStatus.COMPLETE

    def test_cold_start_ignores_requirements_txt_in_zip(self, mock_get_sandbox_class, _mock_wait):
        """requirements.txt support was deleted: a zip with one is accepted but
        we never run `pip install` and the file is dropped on the way to the
        sandbox so user code can't see it either."""
        mock_sandbox = _make_mock_sandbox()
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _version = self._create_app_with_version()
        zip_content = _make_zip_bytes({"app.py": "pass", "requirements.txt": "pandas\n"})

        service = AppRuntimeService()
        service.start_app(app, zip_content=zip_content)

        pip_calls = [c for c in mock_sandbox.execute.call_args_list if "pip install" in str(c)]
        assert pip_calls == []
        # requirements.txt should NOT be uploaded into the sandbox
        write_paths = [c.args[0] if c.args else c.kwargs.get("path") for c in mock_sandbox.write_file.call_args_list]
        assert not any(p and "requirements.txt" in p for p in write_paths)

    def test_warm_start_skips_upload_and_snapshot(self, mock_get_sandbox_class, _mock_wait):
        mock_sandbox = _make_mock_sandbox()
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _version = self._create_app_with_version(snapshot_id="existing-snapshot")

        service = AppRuntimeService()
        record = service.start_app(app)

        assert record.status == StreamlitAppSandbox.Status.RUNNING
        # The bridge token write to /run/bridge_token still happens on warm
        # starts (it's per-sandbox-boot, not per-cold-start), but no app-file
        # uploads should happen and no snapshot should be created.
        write_paths = [c.args[0] if c.args else c.kwargs.get("path") for c in mock_sandbox.write_file.call_args_list]
        assert all(p and p.startswith("/run/bridge_token") for p in write_paths)
        mock_sandbox.create_snapshot.assert_not_called()

    def test_start_app_no_active_version_raises(self, mock_get_sandbox_class, _mock_wait):
        app = StreamlitApp.objects.create(team=self.team, name="No Version")

        service = AppRuntimeService()
        with self.assertRaises(AppRuntimeError, msg="App has no active version"):
            service.start_app(app)

    def test_start_app_already_running_returns_existing(self, mock_get_sandbox_class, _mock_wait):
        app, version = self._create_app_with_version(snapshot_id="snap")
        existing = StreamlitAppSandbox.objects.create(
            app=app,
            version=version,
            sandbox_id="existing-id",
            status=StreamlitAppSandbox.Status.RUNNING,
        )

        service = AppRuntimeService()
        record = service.start_app(app)
        assert record.id == existing.id

    def test_start_app_error_sets_error_status(self, mock_get_sandbox_class, _mock_wait):
        mock_sandbox = _make_mock_sandbox()
        mock_sandbox.execute.side_effect = Exception("Boom")
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _version = self._create_app_with_version(snapshot_id="snap")

        service = AppRuntimeService()
        with self.assertRaises(Exception):
            service.start_app(app)

        record = StreamlitAppSandbox.objects.get(app=app)
        assert record.status == StreamlitAppSandbox.Status.ERROR
        assert "Boom" in record.last_error

    def test_start_app_starts_auth_proxy_and_streamlit(self, mock_get_sandbox_class, _mock_wait):
        mock_sandbox = _make_mock_sandbox()
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _version = self._create_app_with_version(snapshot_id="snap")

        service = AppRuntimeService()
        service.start_app(app)

        execute_calls = [str(c) for c in mock_sandbox.execute.call_args_list]
        proxy_calls = [c for c in execute_calls if "streamlit_auth_proxy" in c]
        streamlit_calls = [c for c in execute_calls if "streamlit run" in c]
        assert len(proxy_calls) == 1
        assert len(streamlit_calls) == 1

    def test_start_app_runs_streamlit_as_non_root(self, mock_get_sandbox_class, _mock_wait):
        """Streamlit must be launched via `runuser -u streamlit` so user code
        executes as a non-root uid. The auth proxy still runs as root so it can
        read the mode-600 bridge token file, but the Streamlit process (which
        runs arbitrary user code) must not have root privileges."""
        mock_sandbox = _make_mock_sandbox()
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _version = self._create_app_with_version(snapshot_id="snap")

        service = AppRuntimeService()
        service.start_app(app)

        execute_calls = [str(c) for c in mock_sandbox.execute.call_args_list]

        # The streamlit-run invocation must go through runuser.
        streamlit_calls = [c for c in execute_calls if "streamlit run" in c]
        assert len(streamlit_calls) == 1
        assert "runuser -u streamlit" in streamlit_calls[0]

        # The auth proxy invocation must NOT go through runuser (it stays
        # as root so it can read /run/bridge_token).
        proxy_calls = [c for c in execute_calls if "streamlit_auth_proxy" in c]
        assert len(proxy_calls) == 1
        assert "runuser" not in proxy_calls[0]

        # /app needs to be chown'd to streamlit before the streamlit process
        # launches — otherwise the non-root user can't read uploaded files.
        chown_calls = [c for c in execute_calls if "chown -R streamlit:streamlit /app" in c]
        assert len(chown_calls) == 1

    def test_start_app_fails_when_proxy_not_ready(self, mock_get_sandbox_class, mock_wait):
        mock_wait.return_value = False
        mock_sandbox = _make_mock_sandbox()
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _version = self._create_app_with_version(snapshot_id="snap")

        service = AppRuntimeService()
        with self.assertRaises(AppRuntimeError, msg="Auth proxy failed to become ready"):
            service.start_app(app)


@patch("products.streamlit_apps.backend.logic.app_runtime.get_sandbox_class")
class TestAppRuntimeStopApp(BaseTest):
    def test_stop_destroys_sandbox(self, mock_get_sandbox_class):
        mock_sandbox = _make_mock_sandbox()
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(
            app=app,
            version_number=1,
            zip_file="a.zip",
            zip_hash="a",
        )
        StreamlitAppSandbox.objects.create(
            app=app,
            version=version,
            sandbox_id="modal-123",
            status=StreamlitAppSandbox.Status.RUNNING,
        )

        service = AppRuntimeService()
        service.stop_app(app)

        record = StreamlitAppSandbox.objects.get(app=app)
        assert record.status == StreamlitAppSandbox.Status.STOPPED
        mock_sandbox.destroy.assert_called_once()

    def test_stop_no_sandbox_is_noop(self, mock_get_sandbox_class):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        service = AppRuntimeService()
        service.stop_app(app)


@patch("products.streamlit_apps.backend.logic.app_runtime.get_sandbox_class")
class TestAppRuntimeGetStatus(BaseTest):
    def test_get_status_no_sandbox(self, mock_get_sandbox_class):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        service = AppRuntimeService()
        status = service.get_status(app)
        assert status["status"] == "stopped"

    def test_get_status_error(self, mock_get_sandbox_class):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        StreamlitAppSandbox.objects.create(
            app=app, version=version, sandbox_id="modal-123", status=StreamlitAppSandbox.Status.ERROR
        )
        service = AppRuntimeService()
        status = service.get_status(app)
        assert status["status"] == "error"

    def test_get_status_running_sandbox_still_alive(self, mock_get_sandbox_class):
        mock_sandbox = _make_mock_sandbox()
        mock_sandbox.is_running.return_value = True
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        StreamlitAppSandbox.objects.create(
            app=app, version=version, sandbox_id="modal-123", status=StreamlitAppSandbox.Status.RUNNING
        )

        service = AppRuntimeService()
        status = service.get_status(app)
        assert status["status"] == "running"

    def test_get_status_detects_timed_out_sandbox(self, mock_get_sandbox_class):
        mock_sandbox = _make_mock_sandbox()
        mock_sandbox.is_running.return_value = False
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        StreamlitAppSandbox.objects.create(
            app=app, version=version, sandbox_id="modal-123", status=StreamlitAppSandbox.Status.RUNNING
        )

        service = AppRuntimeService()
        status = service.get_status(app)
        assert status["status"] == "stopped"

        record = StreamlitAppSandbox.objects.get(app=app)
        assert record.status == StreamlitAppSandbox.Status.STOPPED


@patch("products.streamlit_apps.backend.logic.app_runtime._wait_for_health", return_value=True)
@patch("products.streamlit_apps.backend.logic.app_runtime.get_sandbox_class")
class TestAppRuntimeRestartApp(BaseTest):
    def _make_restartable_app(self, restart_count: int = 0, sandbox_status=None):
        app = StreamlitApp.objects.create(team=self.team, name="Test App", restart_count=restart_count)
        version = StreamlitAppVersion.objects.create(
            app=app,
            version_number=1,
            zip_file="a.zip",
            zip_hash="a",
            snapshot_id="snap",
        )
        app.active_version = version
        app.save(update_fields=["active_version"])
        if sandbox_status is not None:
            StreamlitAppSandbox.objects.create(
                app=app,
                version=version,
                sandbox_id="old",
                status=sandbox_status,
            )
        return app, version

    def test_restart_increments_count_and_defers_reset(self, mock_get_sandbox_class, _mock_wait):
        """A successful restart increments restart_count but does NOT reset
        it inline. The reset is handed to a Celery task scheduled with a
        stability countdown, so a crash-loop that briefly reaches RUNNING
        before dying can't wipe the counter."""
        mock_sandbox = _make_mock_sandbox()
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _version = self._make_restartable_app(sandbox_status=StreamlitAppSandbox.Status.ERROR)

        service = AppRuntimeService()
        with patch("products.streamlit_apps.backend.logic.app_runtime._schedule_restart_count_reset") as mock_schedule:
            record = service.restart_app(app)

        assert record.status == StreamlitAppSandbox.Status.RUNNING
        app.refresh_from_db()
        assert app.restart_count == 1
        mock_schedule.assert_called_once_with(str(app.id), app.team_id)

    def test_restart_count_rolls_back_on_failure(self, mock_get_sandbox_class, _mock_wait):
        """When start_app raises mid-restart, restart_count decrements so a
        transient Modal flap doesn't permanently ratchet the cap."""
        mock_sandbox = _make_mock_sandbox()
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _version = self._make_restartable_app(restart_count=1, sandbox_status=StreamlitAppSandbox.Status.ERROR)

        service = AppRuntimeService()
        with patch.object(service, "start_app", side_effect=AppRuntimeError("boom")):
            with self.assertRaises(AppRuntimeError):
                service.restart_app(app)

        app.refresh_from_db()
        # Bumped from 1 → 2 inside restart_app, then rolled back to 1 on the
        # start_app failure. The cap survives the blip.
        assert app.restart_count == 1

    def test_restart_count_race_does_not_exceed_cap(self, mock_get_sandbox_class, _mock_wait):
        """Sequential restart_app calls serialize on the StreamlitApp row
        lock, so N+1 restarts where the first N succeed must cap out on the
        (N+1)-th without allowing more than MAX_RESTART_COUNT increments."""
        mock_sandbox = _make_mock_sandbox()
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _version = self._make_restartable_app()

        service = AppRuntimeService()
        with patch("products.streamlit_apps.backend.logic.app_runtime._schedule_restart_count_reset"):
            for _ in range(MAX_RESTART_COUNT):
                service.restart_app(app)

        app.refresh_from_db()
        assert app.restart_count == MAX_RESTART_COUNT

        with self.assertRaises(AppRuntimeError):
            service.restart_app(app)

    def test_restart_concurrency_raises_concurrency_error(self, mock_get_sandbox_class, _mock_wait):
        """A second restart while a previous lifecycle is still STARTING or
        STOPPING raises AppRuntimeConcurrencyError, not the generic runtime
        error — the task wrapper uses the specific subclass to pass through
        without stamping the sandbox ERROR."""
        app, _version = self._make_restartable_app(sandbox_status=StreamlitAppSandbox.Status.STARTING)

        service = AppRuntimeService()
        with self.assertRaises(AppRuntimeConcurrencyError):
            service.restart_app(app)

        # Cap was untouched — the concurrent-restart path never entered the
        # increment block.
        app.refresh_from_db()
        assert app.restart_count == 0

    def test_restart_exceeds_max_raises(self, mock_get_sandbox_class, _mock_wait):
        app, _version = self._make_restartable_app(
            restart_count=MAX_RESTART_COUNT, sandbox_status=StreamlitAppSandbox.Status.ERROR
        )

        service = AppRuntimeService()
        with self.assertRaises(AppRuntimeError, msg="Max restart count"):
            service.restart_app(app)

    def test_start_app_fails_when_streamlit_not_ready(self, mock_get_sandbox_class, _mock_wait):
        """Even after the auth proxy is ready, the sandbox must not be
        promoted to RUNNING until Streamlit itself passes its readiness
        probe — otherwise the iframe opens on a 502."""
        mock_sandbox = _make_mock_sandbox()
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _version = self._make_restartable_app()

        service = AppRuntimeService()
        with patch(
            "products.streamlit_apps.backend.logic.app_runtime._wait_for_health",
            side_effect=lambda sandbox, url, name, deadline_seconds, poll_interval_seconds=1.0: name == "Auth proxy",
        ):
            with self.assertRaises(AppRuntimeError, msg="Streamlit failed to become ready"):
                service.start_app(app)


class TestWaitForHealth(BaseTest):
    def test_returns_true_on_200(self):
        from products.streamlit_apps.backend.logic.app_runtime import _wait_for_health

        sandbox = MagicMock()
        sandbox.execute.return_value = MagicMock(stdout="200")
        assert _wait_for_health(sandbox, "http://x/healthz", "x", deadline_seconds=5) is True
        assert sandbox.execute.call_count == 1

    def test_stops_at_deadline_when_never_healthy(self):
        from products.streamlit_apps.backend.logic.app_runtime import _wait_for_health

        sandbox = MagicMock()
        sandbox.execute.return_value = MagicMock(stdout="502")
        assert (
            _wait_for_health(sandbox, "http://x/healthz", "x", deadline_seconds=0.05, poll_interval_seconds=0) is False
        )
        assert sandbox.execute.call_count >= 1


class TestResetRestartCountIfStable(BaseTest):
    """The deferred reset task fires after a stability window and only resets
    restart_count if the sandbox is still RUNNING at fire time."""

    def _make_sandbox(self, *, restart_count: int, status, started_at):
        app = StreamlitApp.objects.create(team=self.team, name="T", restart_count=restart_count)
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        StreamlitAppSandbox.objects.create(
            app=app,
            version=version,
            sandbox_id="sb",
            status=status,
            started_at=started_at,
        )
        return app

    def test_reset_when_running_and_stable(self):
        app = self._make_sandbox(
            restart_count=2,
            status=StreamlitAppSandbox.Status.RUNNING,
            started_at=timezone.now() - timedelta(seconds=RESTART_COUNT_STABILITY_SECONDS + 10),
        )

        from products.streamlit_apps.backend.tasks import reset_streamlit_app_restart_count_if_stable

        reset_streamlit_app_restart_count_if_stable(str(app.id), team_id=app.team_id)

        app.refresh_from_db()
        assert app.restart_count == 0

    def test_skip_when_not_running(self):
        app = self._make_sandbox(
            restart_count=2,
            status=StreamlitAppSandbox.Status.ERROR,
            started_at=timezone.now() - timedelta(seconds=RESTART_COUNT_STABILITY_SECONDS + 10),
        )

        from products.streamlit_apps.backend.tasks import reset_streamlit_app_restart_count_if_stable

        reset_streamlit_app_restart_count_if_stable(str(app.id), team_id=app.team_id)

        app.refresh_from_db()
        assert app.restart_count == 2

    def test_skip_when_too_recent(self):
        app = self._make_sandbox(
            restart_count=2,
            status=StreamlitAppSandbox.Status.RUNNING,
            started_at=timezone.now() - timedelta(seconds=60),
        )

        from products.streamlit_apps.backend.tasks import reset_streamlit_app_restart_count_if_stable

        reset_streamlit_app_restart_count_if_stable(str(app.id), team_id=app.team_id)

        app.refresh_from_db()
        assert app.restart_count == 2


class TestSyncSandboxStatus(BaseTest):
    """sync_sandbox_status must never promote STARTING → RUNNING — that
    path is reserved for start_app after both readiness probes pass."""

    def test_sync_does_not_promote_starting_to_running(self):
        from products.streamlit_apps.backend.logic.app_runtime import sync_sandbox_status

        app = StreamlitApp.objects.create(team=self.team, name="T")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        sandbox_record = StreamlitAppSandbox.objects.create(
            app=app,
            version=version,
            sandbox_id="modal-123",
            status=StreamlitAppSandbox.Status.STARTING,
        )

        with patch("products.streamlit_apps.backend.logic.app_runtime.get_sandbox_class") as mock_cls:
            mock_sandbox = MagicMock()
            mock_sandbox.is_running.return_value = True
            mock_cls.return_value.get_by_id.return_value = mock_sandbox
            result = sync_sandbox_status(sandbox_record)

        assert result.status == StreamlitAppSandbox.Status.STARTING

    def test_sync_expires_stuck_starting_to_error(self):
        from products.streamlit_apps.backend.logic.app_runtime import STARTING_TIMEOUT_SECONDS, sync_sandbox_status

        app = StreamlitApp.objects.create(team=self.team, name="T")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        # Backdate started_at past the startup budget: started_at is the
        # reference sync_sandbox_status uses for the STARTING age check,
        # and start_app stamps it on every new attempt.
        sandbox_record = StreamlitAppSandbox.objects.create(
            app=app,
            version=version,
            sandbox_id="",
            status=StreamlitAppSandbox.Status.STARTING,
            started_at=timezone.now() - timedelta(seconds=STARTING_TIMEOUT_SECONDS + 10),
        )

        result = sync_sandbox_status(sandbox_record)
        assert result.status == StreamlitAppSandbox.Status.ERROR
        assert "timed out" in result.last_error.lower()

    def test_sync_does_not_time_out_starting_record_with_stale_created_at(self):
        """Regression: the OneToOne sandbox row is reused across lifecycles,
        so created_at quickly becomes ancient. A STARTING record whose
        created_at is hours old but whose started_at reflects a recent
        attempt must NOT be marked as timed out — the age check uses
        started_at which tracks this particular attempt.
        """
        from products.streamlit_apps.backend.logic.app_runtime import STARTING_TIMEOUT_SECONDS, sync_sandbox_status

        app = StreamlitApp.objects.create(team=self.team, name="T")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        now = timezone.now()
        sandbox_record = StreamlitAppSandbox.objects.create(
            app=app,
            version=version,
            sandbox_id="sb-recent",
            status=StreamlitAppSandbox.Status.STARTING,
            started_at=now - timedelta(seconds=10),
        )
        # Push created_at way into the past to simulate a row reused
        # across multiple sandbox lifecycles.
        StreamlitAppSandbox.objects.filter(id=sandbox_record.id).update(
            created_at=now - timedelta(seconds=STARTING_TIMEOUT_SECONDS + 3600)
        )
        sandbox_record.refresh_from_db()

        result = sync_sandbox_status(sandbox_record)

        assert result.status == StreamlitAppSandbox.Status.STARTING
        assert result.last_error == ""


class TestBuildSandboxConfig(BaseTest):
    def test_config_sets_snapshot_when_available(self):
        from products.streamlit_apps.backend.logic.app_runtime import _build_sandbox_config

        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(
            app=app, version_number=1, zip_file="a.zip", zip_hash="a", snapshot_id="snap-123"
        )

        config = _build_sandbox_config(app, version)
        assert config.snapshot_id == "snap-123"

    def test_config_no_snapshot_when_absent(self):
        from products.streamlit_apps.backend.logic.app_runtime import _build_sandbox_config

        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")

        config = _build_sandbox_config(app, version)
        assert config.snapshot_id is None

    @parameterized.expand(
        [
            (0.01, 64, 0.25, 16.0),
            (100, 0.1, 8.0, 0.5),
            (2, 4, 2.0, 4.0),
        ]
    )
    def test_config_clamps_resources_to_server_side_bounds(self, cpu, memory, expected_cpu, expected_memory):
        from products.streamlit_apps.backend.logic.app_runtime import _build_sandbox_config

        app = StreamlitApp.objects.create(team=self.team, name="Test App", cpu_cores=cpu, memory_gb=memory)
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")

        config = _build_sandbox_config(app, version)
        assert config.cpu_cores == expected_cpu
        assert config.memory_gb == expected_memory

    @override_settings(SITE_URL="https://us.posthog.com")
    @patch.dict("os.environ", {"STREAMLIT_SANDBOX_CALLBACK_URL": ""})
    def test_config_locks_outbound_egress_to_posthog_hosts(self):
        from products.streamlit_apps.backend.logic.app_runtime import _build_sandbox_config

        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")

        config = _build_sandbox_config(app, version)
        assert config.outbound_domain_allowlist == ["us.posthog.com"]

    @override_settings(SITE_URL="http://localhost:8000")
    @patch.dict("os.environ", {"STREAMLIT_SANDBOX_CALLBACK_URL": ""})
    def test_config_skips_allowlist_for_loopback_hosts(self):
        from products.streamlit_apps.backend.logic.app_runtime import _build_sandbox_config

        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")

        config = _build_sandbox_config(app, version)
        assert config.outbound_domain_allowlist is None

    def test_config_does_not_inject_bridge_env_vars(self):
        """The bridge token is delivered via /run/bridge_token (file-based),
        never as an env var. POSTHOG_BRIDGE_URL was removed too — the in-sandbox
        shim talks to the localhost auth proxy instead.
        """
        from products.streamlit_apps.backend.logic.app_runtime import _build_sandbox_config

        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")

        config = _build_sandbox_config(app, version)
        assert config.environment_variables is not None
        assert "POSTHOG_BRIDGE_URL" not in config.environment_variables
        assert "POSTHOG_BRIDGE_TOKEN" not in config.environment_variables
        assert config.environment_variables["POSTHOG_TEAM_ID"] == str(app.team_id)

    def test_config_injects_streamlit_client_id(self):
        """The proxy needs POSTHOG_STREAMLIT_CLIENT_ID to reject tokens minted
        against other OAuth applications even when they carry matching
        scoped_teams. Missing this env var makes the proxy refuse to start."""
        from products.streamlit_apps.backend.logic.app_runtime import _build_sandbox_config
        from products.streamlit_apps.backend.logic.oauth import STREAMLIT_OAUTH_CLIENT_ID

        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")

        config = _build_sandbox_config(app, version)
        assert config.environment_variables is not None
        assert config.environment_variables["POSTHOG_STREAMLIT_CLIENT_ID"] == STREAMLIT_OAUTH_CLIENT_ID

    def test_config_includes_otel_env_vars(self):
        from products.streamlit_apps.backend.logic.app_runtime import _build_sandbox_config

        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")

        config = _build_sandbox_config(app, version)
        env = config.environment_variables
        assert env is not None
        # Endpoint points at the /i/v1/logs path on whatever callback URL we use
        assert env["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"].endswith("/i/v1/logs")
        # Authorization header carries the bearer token
        assert env["OTEL_EXPORTER_OTLP_HEADERS"].startswith("authorization=Bearer ")
        # Resource attrs identify the service and the owning app
        attrs = env["OTEL_RESOURCE_ATTRIBUTES"]
        assert "service.name=streamlit-auth-proxy" in attrs
        assert f"posthog.team_id={app.team_id}" in attrs
        assert f"posthog.app_id={app.id}" in attrs


class TestGetOtelLogsConfig(BaseTest):
    @parameterized.expand(
        [
            ("dev_or_self_hosted", False, None, "https://example.ngrok.io/i/v1/logs", "phc_local"),
            (
                "cloud_us",
                True,
                "US",
                "https://us.i.posthog.com/i/v1/logs",
                "sTMFPsFhdP1Ssg",
            ),
            (
                "cloud_eu",
                True,
                "EU",
                "https://eu.i.posthog.com/i/v1/logs",
                "phc_dZ4GK1LRjhB97XozMSkEwPXx7OVANaJEwLErkY1phUF",
            ),
            (
                "cloud_unknown_region_defaults_to_us",
                True,
                None,
                "https://us.i.posthog.com/i/v1/logs",
                "sTMFPsFhdP1Ssg",
            ),
        ]
    )
    def test_endpoint_and_token(self, _name, is_cloud, region, expected_endpoint, expected_token):
        from products.streamlit_apps.backend.logic import app_runtime

        # Patch the bound names inside app_runtime, NOT the original module —
        # `from posthog.cloud_utils import is_cloud` copies the reference into
        # app_runtime's namespace, so patching the source has no effect.
        with (
            patch.object(app_runtime, "is_cloud", return_value=is_cloud),
            patch.object(app_runtime, "get_instance_region", return_value=region),
        ):
            endpoint, token = app_runtime._get_otel_logs_config("https://example.ngrok.io")

        assert endpoint == expected_endpoint
        assert token == expected_token


@patch("products.streamlit_apps.backend.logic.app_runtime.get_sandbox_class")
class TestAppRuntimeConnectUrl(BaseTest):
    def _create_running_app(self):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        app.active_version = version
        app.save(update_fields=["active_version"])
        sandbox = StreamlitAppSandbox.objects.create(
            app=app, version=version, sandbox_id="modal-123", status=StreamlitAppSandbox.Status.RUNNING
        )
        return app, sandbox

    def test_get_connect_url_returns_url_and_token(self, mock_get_sandbox_class):
        mock_sandbox = MagicMock()
        creds = MagicMock()
        creds.url = "https://abc.modal.run"
        creds.token = "tok_abc123"
        mock_sandbox.is_running.return_value = True
        mock_sandbox.get_connect_credentials.return_value = creds
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _sandbox = self._create_running_app()
        service = AppRuntimeService()
        result = service.get_connect_url(app, user_id=1, team_id=1)
        assert result == {"url": "https://abc.modal.run", "token": "tok_abc123"}

    @parameterized.expand(
        [
            ("stopped", StreamlitAppSandbox.Status.STOPPED),
            ("starting", StreamlitAppSandbox.Status.STARTING),
            ("error", StreamlitAppSandbox.Status.ERROR),
        ]
    )
    def test_get_connect_url_returns_none_for_non_running(self, mock_get_sandbox_class, _name, sandbox_status):
        mock_get_sandbox_class.return_value.get_by_id.return_value.is_running.return_value = False

        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        StreamlitAppSandbox.objects.create(app=app, version=version, sandbox_id="modal-123", status=sandbox_status)

        service = AppRuntimeService()
        assert service.get_connect_url(app, user_id=1, team_id=1) is None

    def test_get_connect_url_returns_none_when_no_sandbox(self, mock_get_sandbox_class):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        service = AppRuntimeService()
        assert service.get_connect_url(app, user_id=1, team_id=1) is None

    def test_get_connect_url_calls_get_connect_credentials(self, mock_get_sandbox_class):
        # The auth proxy inside the sandbox identifies the user via the OAuth
        # access token injected into the URL, so we don't need to pass user
        # metadata through the Modal connect token itself.
        mock_sandbox = MagicMock()
        creds = MagicMock()
        creds.url = "https://x.modal.run"
        creds.token = "tok"
        mock_sandbox.is_running.return_value = True
        mock_sandbox.get_connect_credentials.return_value = creds
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _sandbox = self._create_running_app()
        service = AppRuntimeService()
        service.get_connect_url(app, user_id=42, team_id=7)

        mock_sandbox.get_connect_credentials.assert_called_once()

    def test_get_connect_url_detects_timed_out_sandbox(self, mock_get_sandbox_class):
        mock_sandbox = MagicMock()
        mock_sandbox.is_running.return_value = False
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _sandbox = self._create_running_app()
        service = AppRuntimeService()
        result = service.get_connect_url(app, user_id=1, team_id=1)

        assert result is None
        record = StreamlitAppSandbox.objects.get(app=app)
        assert record.status == StreamlitAppSandbox.Status.STOPPED


class TestSandboxCallbackUrl(BaseTest):
    """Docker sandboxes reach the host via host.docker.internal (applied to
    SITE_URL by DockerSandbox), so they must ignore the STREAMLIT_SANDBOX_CALLBACK_URL
    tunnel override that only Modal needs. Honoring a stale tunnel here points a
    Docker sandbox at a dead URL and breaks token introspection."""

    @override_settings(SANDBOX_PROVIDER="docker", SITE_URL="http://localhost:8000")
    @patch.dict("os.environ", {"STREAMLIT_SANDBOX_CALLBACK_URL": "https://stale-tunnel.ngrok.dev"})
    def test_docker_ignores_tunnel_override(self):
        assert _get_sandbox_callback_url() == "http://localhost:8000"

    @override_settings(SANDBOX_PROVIDER="modal", SITE_URL="http://localhost:8000")
    @patch.dict("os.environ", {"STREAMLIT_SANDBOX_CALLBACK_URL": "https://tunnel.ngrok.dev"})
    def test_modal_uses_tunnel_override(self):
        assert _get_sandbox_callback_url() == "https://tunnel.ngrok.dev"

    @override_settings(SANDBOX_PROVIDER="modal", SITE_URL="http://localhost:8000")
    @patch.dict("os.environ", {}, clear=True)
    def test_modal_falls_back_to_site_url(self):
        assert _get_sandbox_callback_url() == "http://localhost:8000"
