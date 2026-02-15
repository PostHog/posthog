from __future__ import annotations

import time
import logging
from io import BytesIO
from zipfile import ZipFile

from django.utils import timezone

from products.streamlit_apps.backend.models import StreamlitApp, StreamlitAppSandbox, StreamlitAppVersion
from products.tasks.backend.services.sandbox import SandboxConfig, SandboxProtocol, SandboxTemplate, get_sandbox_class

logger = logging.getLogger(__name__)

STREAMLIT_PORT = 8501
AUTH_PROXY_PORT = 8080
STREAMLIT_APP_PATH = "/app"
MAX_RESTART_COUNT = 3


class AppRuntimeError(Exception):
    pass


def _build_sandbox_config(app: StreamlitApp, version: StreamlitAppVersion) -> SandboxConfig:
    config = SandboxConfig(
        name=f"streamlit-{app.short_id}",
        template=SandboxTemplate.STREAMLIT_BASE,
        cpu_cores=app.cpu_cores,
        memory_gb=app.memory_gb,
        ttl_seconds=60 * 15,
    )
    if version.snapshot_id:
        config.snapshot_id = version.snapshot_id
    return config


def _upload_app_files(sandbox: SandboxProtocol, zip_content: bytes) -> bool:
    """Upload zip contents to sandbox. Returns True if requirements.txt exists."""
    has_requirements = False
    with ZipFile(BytesIO(zip_content)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            content = zf.read(info.filename)
            dest_path = f"{STREAMLIT_APP_PATH}/{info.filename}"
            sandbox.write_file(dest_path, content)
            if info.filename == "requirements.txt":
                has_requirements = True
    return has_requirements


def _start_auth_proxy(sandbox: SandboxProtocol) -> None:
    result = sandbox.execute(
        "nohup python /usr/local/bin/streamlit_auth_proxy.py > /tmp/auth_proxy.log 2>&1 &",
        timeout_seconds=10,
    )
    if result.exit_code != 0:
        raise AppRuntimeError(f"Failed to start auth proxy: {result.stderr}")


def _start_streamlit_process(sandbox: SandboxProtocol) -> None:
    result = sandbox.execute(
        f"nohup streamlit run {STREAMLIT_APP_PATH}/app.py "
        f"--server.port {STREAMLIT_PORT} "
        f"--server.headless true "
        f"> /tmp/streamlit.log 2>&1 &",
        timeout_seconds=10,
    )
    if result.exit_code != 0:
        raise AppRuntimeError(f"Failed to start Streamlit: {result.stderr}")


def _wait_for_proxy_ready(sandbox: SandboxProtocol, max_attempts: int = 20, delay_seconds: float = 1.0) -> bool:
    health_cmd = f"curl -s -o /dev/null -w '%{{http_code}}' http://localhost:{AUTH_PROXY_PORT}/healthz"
    for attempt in range(max_attempts):
        result = sandbox.execute(health_cmd, timeout_seconds=5)
        if result.stdout.strip() == "200":
            logger.info(f"Auth proxy health check passed on attempt {attempt + 1}")
            return True
        time.sleep(delay_seconds)
    return False


class AppRuntimeService:
    def __init__(self, download_zip=None):
        self._download_zip = download_zip

    def start_app(self, app: StreamlitApp, zip_content: bytes | None = None) -> StreamlitAppSandbox:
        version = app.active_version
        if version is None:
            raise AppRuntimeError("App has no active version")

        existing = StreamlitAppSandbox.objects.filter(app=app).first()
        if existing and existing.status == StreamlitAppSandbox.Status.RUNNING:
            return existing

        if existing:
            existing.delete()

        sandbox_record = StreamlitAppSandbox.objects.create(
            app=app,
            version=version,
            sandbox_id="",
            status=StreamlitAppSandbox.Status.STARTING,
        )

        try:
            config = _build_sandbox_config(app, version)
            sandbox_class = get_sandbox_class()
            sandbox = sandbox_class.create(config)
            sandbox_record.sandbox_id = sandbox.id
            sandbox_record.save(update_fields=["sandbox_id"])

            is_warm_start = version.snapshot_id is not None

            if not is_warm_start:
                if zip_content is None and self._download_zip:
                    zip_content = self._download_zip(version.zip_file)
                if zip_content is None:
                    raise AppRuntimeError("No zip content available for cold start")

                has_requirements = _upload_app_files(sandbox, zip_content)

                if has_requirements:
                    result = sandbox.execute(
                        f"pip install -r {STREAMLIT_APP_PATH}/requirements.txt",
                        timeout_seconds=300,
                    )
                    if result.exit_code != 0:
                        raise AppRuntimeError(f"pip install failed: {result.stderr}")

                snapshot_id = sandbox.create_snapshot()
                version.snapshot_id = snapshot_id
                version.snapshot_created_at = timezone.now()
                version.save(update_fields=["snapshot_id", "snapshot_created_at"])

            _start_auth_proxy(sandbox)
            _start_streamlit_process(sandbox)

            if not _wait_for_proxy_ready(sandbox):
                raise AppRuntimeError("Auth proxy failed to become ready")

            sandbox_record.status = StreamlitAppSandbox.Status.RUNNING
            sandbox_record.started_at = timezone.now()
            sandbox_record.last_activity_at = timezone.now()
            sandbox_record.save(update_fields=["status", "started_at", "last_activity_at"])

            return sandbox_record

        except Exception as e:
            sandbox_record.status = StreamlitAppSandbox.Status.ERROR
            sandbox_record.last_error = str(e)
            sandbox_record.save(update_fields=["status", "last_error"])
            raise

    def stop_app(self, app: StreamlitApp) -> None:
        sandbox_record = StreamlitAppSandbox.objects.filter(app=app).first()
        if not sandbox_record:
            return

        sandbox_record.status = StreamlitAppSandbox.Status.STOPPING
        sandbox_record.save(update_fields=["status"])

        if sandbox_record.sandbox_id:
            try:
                sandbox_class = get_sandbox_class()
                sandbox = sandbox_class.get_by_id(sandbox_record.sandbox_id)
                sandbox.destroy()
            except Exception:
                logger.warning("streamlit_sandbox_destroy_failed", extra={"app_id": str(app.id)})

        sandbox_record.status = StreamlitAppSandbox.Status.STOPPED
        sandbox_record.save(update_fields=["status"])

    def get_status(self, app: StreamlitApp) -> dict:
        sandbox_record = StreamlitAppSandbox.objects.filter(app=app).first()
        if not sandbox_record:
            return {
                "status": "stopped",
                "current_viewers": 0,
                "max_viewers": 20,
            }
        return {
            "status": sandbox_record.status,
            "current_viewers": sandbox_record.current_viewers,
            "max_viewers": sandbox_record.max_viewers,
            "started_at": sandbox_record.started_at,
            "restart_count": sandbox_record.restart_count,
            "last_error": sandbox_record.last_error or None,
        }

    def get_connect_url(self, app: StreamlitApp, user_id: int, team_id: int) -> dict | None:
        """Get connect URL and token for authenticated access to the sandbox.

        Modal connect tokens provide authenticated HTTP access to port 8080.
        Returns {"url": str, "token": str} or None if sandbox is not running.
        """
        sandbox_record = StreamlitAppSandbox.objects.filter(app=app).first()
        if not sandbox_record or not sandbox_record.sandbox_id:
            return None
        if sandbox_record.status != StreamlitAppSandbox.Status.RUNNING:
            return None

        try:
            sandbox_class = get_sandbox_class()
            sandbox = sandbox_class.get_by_id(sandbox_record.sandbox_id)
            credentials = sandbox._sandbox.create_connect_token(
                user_metadata={"user_id": str(user_id), "team_id": str(team_id)}
            )
            return {"url": credentials.url, "token": credentials.token}
        except Exception:
            logger.warning("streamlit_connect_url_failed", extra={"app_id": str(app.id)})
            return None

    def restart_app(self, app: StreamlitApp, zip_content: bytes | None = None) -> StreamlitAppSandbox:
        sandbox_record = StreamlitAppSandbox.objects.filter(app=app).first()
        if sandbox_record and sandbox_record.restart_count >= MAX_RESTART_COUNT:
            sandbox_record.status = StreamlitAppSandbox.Status.ERROR
            sandbox_record.last_error = f"Max restart count ({MAX_RESTART_COUNT}) exceeded"
            sandbox_record.save(update_fields=["status", "last_error"])
            raise AppRuntimeError(f"Max restart count ({MAX_RESTART_COUNT}) exceeded")

        self.stop_app(app)

        sandbox_record = StreamlitAppSandbox.objects.filter(app=app).first()
        restart_count = (sandbox_record.restart_count + 1) if sandbox_record else 1
        if sandbox_record:
            sandbox_record.delete()

        new_record = self.start_app(app, zip_content=zip_content)
        new_record.restart_count = restart_count
        new_record.save(update_fields=["restart_count"])
        return new_record
