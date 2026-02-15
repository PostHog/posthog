import zipfile
from io import BytesIO

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.streamlit_apps.backend.models import StreamlitApp, StreamlitAppSandbox, StreamlitAppVersion
from products.streamlit_apps.backend.services.app_runtime import MAX_RESTART_COUNT, AppRuntimeError, AppRuntimeService


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


@patch("products.streamlit_apps.backend.services.app_runtime._wait_for_proxy_ready", return_value=True)
@patch("products.streamlit_apps.backend.services.app_runtime.get_sandbox_class")
class TestAppRuntimeStartApp(BaseTest):
    def _create_app_with_version(self, has_requirements=False, snapshot_id=None):
        app = StreamlitApp.objects.create(team=self.team, name="Test App", created_by=self.user)
        version = StreamlitAppVersion.objects.create(
            app=app,
            version_number=1,
            zip_file="s3://bucket/app.zip",
            zip_hash="abc123",
            has_requirements=has_requirements,
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
        assert version.snapshot_id == "snapshot-abc"
        assert version.snapshot_created_at is not None

    def test_cold_start_with_requirements_runs_pip_install(self, mock_get_sandbox_class, _mock_wait):
        mock_sandbox = _make_mock_sandbox()
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _version = self._create_app_with_version(has_requirements=True)
        zip_content = _make_zip_bytes({"app.py": "pass", "requirements.txt": "pandas\n"})

        service = AppRuntimeService()
        service.start_app(app, zip_content=zip_content)

        pip_calls = [c for c in mock_sandbox.execute.call_args_list if "pip install" in str(c)]
        assert len(pip_calls) == 1

    def test_warm_start_skips_upload_and_snapshot(self, mock_get_sandbox_class, _mock_wait):
        mock_sandbox = _make_mock_sandbox()
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _version = self._create_app_with_version(snapshot_id="existing-snapshot")

        service = AppRuntimeService()
        record = service.start_app(app)

        assert record.status == StreamlitAppSandbox.Status.RUNNING
        mock_sandbox.write_file.assert_not_called()
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

    def test_start_app_fails_when_proxy_not_ready(self, mock_get_sandbox_class, mock_wait):
        mock_wait.return_value = False
        mock_sandbox = _make_mock_sandbox()
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _version = self._create_app_with_version(snapshot_id="snap")

        service = AppRuntimeService()
        with self.assertRaises(AppRuntimeError, msg="Auth proxy failed to become ready"):
            service.start_app(app)


@patch("products.streamlit_apps.backend.services.app_runtime.get_sandbox_class")
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


class TestAppRuntimeGetStatus(BaseTest):
    @parameterized.expand(
        [
            ("no_sandbox", None, "stopped"),
            ("running", StreamlitAppSandbox.Status.RUNNING, "running"),
            ("error", StreamlitAppSandbox.Status.ERROR, "error"),
        ]
    )
    def test_get_status(self, _name, sandbox_status, expected):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")

        if sandbox_status is not None:
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
                status=sandbox_status,
            )

        service = AppRuntimeService()
        status = service.get_status(app)
        assert status["status"] == expected


@patch("products.streamlit_apps.backend.services.app_runtime._wait_for_proxy_ready", return_value=True)
@patch("products.streamlit_apps.backend.services.app_runtime.get_sandbox_class")
class TestAppRuntimeRestartApp(BaseTest):
    def test_restart_increments_count(self, mock_get_sandbox_class, _mock_wait):
        mock_sandbox = _make_mock_sandbox()
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(
            app=app,
            version_number=1,
            zip_file="a.zip",
            zip_hash="a",
            snapshot_id="snap",
        )
        app.active_version = version
        app.save(update_fields=["active_version"])
        StreamlitAppSandbox.objects.create(
            app=app,
            version=version,
            sandbox_id="old",
            status=StreamlitAppSandbox.Status.ERROR,
        )

        service = AppRuntimeService()
        record = service.restart_app(app)
        assert record.restart_count == 1
        assert record.status == StreamlitAppSandbox.Status.RUNNING

    def test_restart_exceeds_max_raises(self, mock_get_sandbox_class, _mock_wait):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(
            app=app,
            version_number=1,
            zip_file="a.zip",
            zip_hash="a",
        )
        app.active_version = version
        app.save(update_fields=["active_version"])
        StreamlitAppSandbox.objects.create(
            app=app,
            version=version,
            sandbox_id="old",
            status=StreamlitAppSandbox.Status.ERROR,
            restart_count=MAX_RESTART_COUNT,
        )

        service = AppRuntimeService()
        with self.assertRaises(AppRuntimeError, msg="Max restart count"):
            service.restart_app(app)


class TestBuildSandboxConfig(BaseTest):
    def test_config_has_no_encrypted_ports(self):
        from products.streamlit_apps.backend.services.app_runtime import _build_sandbox_config

        app = StreamlitApp.objects.create(team=self.team, name="Test App", cpu_cores=1.0, memory_gb=2.0)
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")

        config = _build_sandbox_config(app, version)
        assert config.encrypted_ports is None

    def test_config_sets_snapshot_when_available(self):
        from products.streamlit_apps.backend.services.app_runtime import _build_sandbox_config

        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(
            app=app, version_number=1, zip_file="a.zip", zip_hash="a", snapshot_id="snap-123"
        )

        config = _build_sandbox_config(app, version)
        assert config.snapshot_id == "snap-123"

    def test_config_no_snapshot_when_absent(self):
        from products.streamlit_apps.backend.services.app_runtime import _build_sandbox_config

        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")

        config = _build_sandbox_config(app, version)
        assert config.snapshot_id is None


@patch("products.streamlit_apps.backend.services.app_runtime.get_sandbox_class")
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
        mock_sandbox._sandbox.create_connect_token.return_value = creds
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
    def test_get_connect_url_returns_none_for_non_running(self, _name, sandbox_status, mock_get_sandbox_class):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        StreamlitAppSandbox.objects.create(app=app, version=version, sandbox_id="modal-123", status=sandbox_status)

        service = AppRuntimeService()
        assert service.get_connect_url(app, user_id=1, team_id=1) is None

    def test_get_connect_url_returns_none_when_no_sandbox(self, mock_get_sandbox_class):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        service = AppRuntimeService()
        assert service.get_connect_url(app, user_id=1, team_id=1) is None

    def test_get_connect_url_passes_user_metadata(self, mock_get_sandbox_class):
        mock_sandbox = MagicMock()
        creds = MagicMock()
        creds.url = "https://x.modal.run"
        creds.token = "tok"
        mock_sandbox._sandbox.create_connect_token.return_value = creds
        mock_get_sandbox_class.return_value = _make_mock_sandbox_class(mock_sandbox)

        app, _sandbox = self._create_running_app()
        service = AppRuntimeService()
        service.get_connect_url(app, user_id=42, team_id=7)

        mock_sandbox._sandbox.create_connect_token.assert_called_once_with(
            user_metadata={"user_id": "42", "team_id": "7"}
        )
