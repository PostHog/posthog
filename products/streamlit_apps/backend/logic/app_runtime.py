from __future__ import annotations

import os
import time
from collections.abc import Callable
from io import BytesIO
from urllib.parse import urlparse
from zipfile import ZipFile

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

import structlog

from posthog.cloud_utils import is_cloud
from posthog.ph_client import PH_EU_API_KEY, PH_EU_HOST, PH_US_API_KEY, PH_US_HOST
from posthog.utils import get_instance_region

from products.streamlit_apps.backend.logic.oauth import create_sandbox_bridge_token, get_streamlit_oauth_app
from products.streamlit_apps.backend.logic.zip_validator import MAX_UNCOMPRESSED_SIZE, is_safe_zip_path
from products.streamlit_apps.backend.models import (
    MAX_CPU_CORES,
    MAX_MEMORY_GB,
    MIN_CPU_CORES,
    MIN_MEMORY_GB,
    StreamlitApp,
    StreamlitAppSandbox,
    StreamlitAppVersion,
)
from products.streamlit_apps.backend.tasks import reset_streamlit_app_restart_count_if_stable
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.sandbox import SandboxBase, SandboxConfig, SandboxTemplate, get_sandbox_class

logger = structlog.get_logger(__name__)

STREAMLIT_PORT = 8501
AUTH_PROXY_PORT = 8080
STREAMLIT_APP_PATH = "/app"
BRIDGE_TOKEN_PATH = "/run/bridge_token"
MAX_RESTART_COUNT = 3
STARTING_TIMEOUT_SECONDS = 600
# Wall-clock budgets for boot health checks; together they bound how long a
# lifecycle task can occupy a Celery worker on a sandbox that never comes up.
AUTH_PROXY_HEALTH_DEADLINE_SECONDS = 30
STREAMLIT_HEALTH_DEADLINE_SECONDS = 60
# Sandbox must stay RUNNING for this long before restart_count resets; shorter
# lifecycles are treated as part of the same crash loop that incremented it.
RESTART_COUNT_STABILITY_SECONDS = 5 * 60
# Set on `last_error` when a Modal sandbox dies on its own (e.g. exceeds its
# 24h TTL). The auto-restart task keys off this exact string to distinguish
# crashes from user/idle stops.
TTL_TIMEOUT_LAST_ERROR = "Sandbox terminated (TTL timeout)"


class AppRuntimeError(Exception):
    pass


class AppRuntimeConcurrencyError(AppRuntimeError):
    """Raised when a lifecycle action collides with one already in flight."""

    pass


def _get_sandbox_callback_url() -> str:
    """URL that sandboxes use to call back to PostHog (OAuth introspect, bridge queries).

    Docker sandboxes reach the host directly via host.docker.internal (applied by
    DockerSandbox to SITE_URL), so they ignore STREAMLIT_SANDBOX_CALLBACK_URL — that
    public-tunnel override exists only for Modal, whose cloud workers can't reach
    localhost. Honoring a stale tunnel here would point a local Docker sandbox at a
    dead URL and break token introspection.
    """
    from django.conf import settings

    if getattr(settings, "SANDBOX_PROVIDER", None) == "docker":
        return settings.SITE_URL

    return os.environ.get("STREAMLIT_SANDBOX_CALLBACK_URL") or settings.SITE_URL


def _get_otel_logs_config(callback_url: str) -> tuple[str, str]:
    """Return (endpoint, token) for sandbox proxy OTEL log export.

    Mirrors posthog.ph_client.get_regional_ph_client. On cloud, logs ship to
    PH-on-PH; in dev/self-hosted they ship back via the callback URL.
    """
    if is_cloud():
        region = get_instance_region()
        if region == "EU":
            return f"{PH_EU_HOST}/i/v1/logs", PH_EU_API_KEY
        return f"{PH_US_HOST}/i/v1/logs", PH_US_API_KEY

    # phc_local is the dev token that maps to team_id=1 in capture-logs.
    return f"{callback_url.rstrip('/')}/i/v1/logs", "phc_local"


def _outbound_allowlist(*urls: str) -> list[str] | None:
    """Hostnames the sandbox may reach — everything else is fenced off by Modal.

    User app code runs in the sandbox, so without this an app author could probe
    internal/metadata endpoints on the runtime network. Loopback-style hosts are
    dropped (Modal rejects them as invalid domains; the Docker provider has no
    fence and ignores the field, so local dev is unaffected).
    """
    hosts: list[str] = []
    for url in urls:
        host = urlparse(url).hostname
        if host and "." in host and host != "host.docker.internal" and host not in hosts:
            hosts.append(host)
    return hosts or None


def _build_sandbox_config(app: StreamlitApp, version: StreamlitAppVersion) -> SandboxConfig:
    callback_url = _get_sandbox_callback_url()
    otel_endpoint, otel_token = _get_otel_logs_config(callback_url)
    otel_resource_attrs = ",".join(
        [
            "service.name=streamlit-auth-proxy",
            f"posthog.team_id={app.team_id}",
            f"posthog.app_id={app.id}",
            f"posthog.app_short_id={app.short_id}",
        ]
    )

    config = SandboxConfig(
        name=f"streamlit-{app.short_id}",
        template=SandboxTemplate.STREAMLIT_BASE,
        cpu_cores=min(max(app.cpu_cores, MIN_CPU_CORES), MAX_CPU_CORES),
        memory_gb=min(max(app.memory_gb, MIN_MEMORY_GB), MAX_MEMORY_GB),
        # TODO: Ideally we'd add a auto_suspend config the user can set that defines the TTL.
        #       After X minutes of inactivity, kill the sandbox.
        ttl_seconds=60 * 15,
        # Egress locked to the hosts the proxy itself needs (introspect/bridge +
        # OTEL logs); per-app egress domains can be added as a feature later.
        outbound_domain_allowlist=_outbound_allowlist(callback_url, otel_endpoint),
        # TODO: We might need to allow the creator of the Streamlit to add more env vars.
        environment_variables={
            "POSTHOG_SITE_URL": callback_url,
            # Per-sandbox team + app bindings; the auth proxy refuses tokens
            # that don't match both, so leaks can't unlock this sandbox.
            "POSTHOG_TEAM_ID": str(app.team_id),
            "POSTHOG_STREAMLIT_CLIENT_ID": get_streamlit_oauth_app().client_id,
            # Standard OTEL env vars — read directly by the SDK in the proxy.
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": otel_endpoint,
            "OTEL_EXPORTER_OTLP_HEADERS": f"authorization=Bearer {otel_token}",
            "OTEL_RESOURCE_ATTRIBUTES": otel_resource_attrs,
        },
    )
    if version.snapshot_id:
        config.snapshot_id = version.snapshot_id
    return config


def _upload_app_files(sandbox: SandboxBase, zip_content: bytes) -> None:
    """Upload zip contents to sandbox, bounded by actual bytes read (not zip metadata)."""
    total_bytes = 0
    files_to_write: list[tuple[str, bytes]] = []
    requirements_seen = False
    with ZipFile(BytesIO(zip_content)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if not is_safe_zip_path(info.filename):
                raise AppRuntimeError(f"Unsafe file path in zip: {info.filename}")
            normalized = os.path.normpath(info.filename)
            if normalized == "requirements.txt":
                requirements_seen = True
                continue
            content = zf.read(info.filename)
            total_bytes += len(content)
            if total_bytes > MAX_UNCOMPRESSED_SIZE:
                raise AppRuntimeError(f"Zip uncompressed size exceeds limit ({MAX_UNCOMPRESSED_SIZE} bytes)")
            files_to_write.append((f"{STREAMLIT_APP_PATH}/{normalized}", content))

    for dest_path, content in files_to_write:
        sandbox.write_file(dest_path, content)

    if requirements_seen:
        logger.info("streamlit_requirements_ignored")


def _write_bridge_token(sandbox: SandboxBase, token: str) -> None:
    """Drop the bridge bearer token at /run/bridge_token with mode 600.

    MUST run before _start_auth_proxy — the proxy reads and unlinks the file
    on boot, so a later write would race the unlink.
    """
    sandbox.write_file(BRIDGE_TOKEN_PATH, token.encode("utf-8"))
    result = sandbox.execute(f"chmod 600 {BRIDGE_TOKEN_PATH}", timeout_seconds=5)
    if result.exit_code != 0:
        raise AppRuntimeError(f"Failed to chmod bridge token file: {result.stderr}")


def _start_auth_proxy(sandbox: SandboxBase) -> None:
    # setsid -f double-forks into a new session; exit 0 only means "spawned",
    # so the real liveness check is _wait_for_health below.
    result = sandbox.execute(
        "setsid -f sh -c 'python /usr/local/bin/streamlit_auth_proxy.py >/tmp/auth_proxy.log 2>&1'",
        timeout_seconds=10,
    )
    if result.exit_code != 0:
        raise AppRuntimeError(f"Failed to start auth proxy: {result.stderr}")


def _start_streamlit_process(sandbox: SandboxBase) -> None:
    """Boot Streamlit as the non-root `streamlit` user.

    Files land in /app root-owned, so we chown before launch. /run/bridge_token
    stays root-owned mode 600 — the whole point is that this uid can't read it.
    """
    chown_result = sandbox.execute(
        f"chown -R streamlit:streamlit {STREAMLIT_APP_PATH}",
        timeout_seconds=5,
    )
    if chown_result.exit_code != 0:
        raise AppRuntimeError(f"Failed to chown {STREAMLIT_APP_PATH} to streamlit user: {chown_result.stderr}")

    # runuser (from util-linux) is a non-interactive "become user" wrapper —
    # preferred over `su` because it doesn't load a login shell or need a tty.
    result = sandbox.execute(
        "setsid -f runuser -u streamlit -- sh -c '"
        f"streamlit run {STREAMLIT_APP_PATH}/app.py "
        f"--server.port {STREAMLIT_PORT} "
        f"--server.headless true "
        f">/tmp/streamlit.log 2>&1'",
        timeout_seconds=10,
    )
    if result.exit_code != 0:
        raise AppRuntimeError(f"Failed to start Streamlit: {result.stderr}")


def _wait_for_health(
    sandbox: SandboxBase, url: str, name: str, deadline_seconds: float, poll_interval_seconds: float = 1.0
) -> bool:
    """Poll the URL until it returns 200 or the wall-clock deadline passes.

    Deadline-based rather than attempt-based: each attempt can cost up to ~6s
    (5s curl budget + the sleep), so N attempts could otherwise occupy a
    Celery worker for ~6N seconds on a sandbox that never becomes ready.
    """
    health_cmd = f"curl -s -o /dev/null -w '%{{http_code}}' {url}"
    deadline = time.monotonic() + deadline_seconds
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        result = sandbox.execute(health_cmd, timeout_seconds=5)
        if result.stdout.strip() == "200":
            logger.info(f"{name} health check passed on attempt {attempt}")
            return True
        time.sleep(poll_interval_seconds)
    return False


def _schedule_restart_count_reset(app_id: str, team_id: int) -> None:
    """Defer the restart_count reset so a brief RUNNING bounce can't wipe the counter."""
    reset_streamlit_app_restart_count_if_stable.apply_async(
        kwargs={"app_id": app_id, "team_id": team_id},
        countdown=RESTART_COUNT_STABILITY_SECONDS,
    )


_SYNC_FAILURE_THRESHOLD = 3
_SYNC_FAILURE_TTL_SECONDS = 600


def _sync_failure_key(sandbox_record: StreamlitAppSandbox) -> str:
    # Fall back to the PK while STARTING (no Modal handle assigned yet).
    return f"streamlit_sandbox_sync_failures:{sandbox_record.sandbox_id or sandbox_record.id}"


def _track_sync_failure(sandbox_record: StreamlitAppSandbox) -> int:
    from django.core.cache import cache

    key = _sync_failure_key(sandbox_record)
    try:
        new_value = cache.incr(key)
    except ValueError:
        cache.set(key, 1, _SYNC_FAILURE_TTL_SECONDS)
        return 1
    # Refresh TTL so slow-drip failures still trip the circuit.
    try:
        cache.touch(key, _SYNC_FAILURE_TTL_SECONDS)
    except (AttributeError, NotImplementedError):
        cache.set(key, new_value, _SYNC_FAILURE_TTL_SECONDS)
    return new_value


def _clear_sync_failures(sandbox_record: StreamlitAppSandbox) -> None:
    from django.core.cache import cache

    cache.delete(_sync_failure_key(sandbox_record))


def sync_sandbox_status(sandbox_record: StreamlitAppSandbox) -> StreamlitAppSandbox:
    """Sync DB sandbox status with the Modal sandbox state.

    Handles only RUNNING→STOPPED (died) and STARTING→ERROR (timed out).
    Never promotes STARTING→RUNNING — that transition only happens in
    start_app after both readiness probes pass. Consecutive failures
    short-circuit to ERROR after _SYNC_FAILURE_THRESHOLD strikes.
    """
    if sandbox_record.status not in (StreamlitAppSandbox.Status.RUNNING, StreamlitAppSandbox.Status.STARTING):
        return sandbox_record

    if sandbox_record.status == StreamlitAppSandbox.Status.STARTING:
        reference = sandbox_record.started_at or sandbox_record.created_at
        age = (timezone.now() - reference).total_seconds()
        if age > STARTING_TIMEOUT_SECONDS:
            sandbox_record.status = StreamlitAppSandbox.Status.ERROR
            sandbox_record.last_error = "Startup timed out"
            sandbox_record.save(update_fields=["status", "last_error"])
        return sandbox_record

    try:
        sandbox_class = get_sandbox_class()
        sandbox = sandbox_class.get_by_id(sandbox_record.sandbox_id)
        is_running = sandbox.is_running()

        if sandbox_record.status == StreamlitAppSandbox.Status.RUNNING and not is_running:
            sandbox_record.status = StreamlitAppSandbox.Status.STOPPED
            sandbox_record.last_error = TTL_TIMEOUT_LAST_ERROR
            sandbox_record.save(update_fields=["status", "last_error"])

        _clear_sync_failures(sandbox_record)
    except Exception:
        failures = _track_sync_failure(sandbox_record)
        logger.warning(
            "sandbox_status_sync_failed",
            sandbox_id=sandbox_record.sandbox_id,
            app_id=str(sandbox_record.app_id),
            consecutive_failures=failures,
            exc_info=True,
        )
        if failures >= _SYNC_FAILURE_THRESHOLD:
            sandbox_record.status = StreamlitAppSandbox.Status.ERROR
            sandbox_record.last_error = f"Status sync failed {failures} times in a row."
            sandbox_record.save(update_fields=["status", "last_error"])
            _clear_sync_failures(sandbox_record)

    return sandbox_record


class AppRuntimeService:
    def __init__(self, download_zip: Callable[[str], bytes] | None = None) -> None:
        self._download_zip = download_zip

    def start_app(self, app: StreamlitApp, zip_content: bytes | None = None) -> StreamlitAppSandbox:
        version = app.active_version
        if version is None:
            raise AppRuntimeError("App has no active version")

        with transaction.atomic():
            existing = StreamlitAppSandbox.objects.select_for_update().filter(app=app).first()
            if existing and existing.status in (
                StreamlitAppSandbox.Status.RUNNING,
                StreamlitAppSandbox.Status.STARTING,
            ):
                return existing

            try:
                sandbox_record, _ = StreamlitAppSandbox.objects.update_or_create(
                    app=app,
                    defaults={
                        "version": version,
                        "sandbox_id": "",
                        "status": StreamlitAppSandbox.Status.STARTING,
                        "last_error": "",
                        "started_at": timezone.now(),
                    },
                )
            except IntegrityError:
                return StreamlitAppSandbox.objects.get(app=app)

        sandbox = None
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

                _upload_app_files(sandbox, zip_content)

                modal_image_id = sandbox.create_snapshot()

                snapshot_id = tasks_facade.create_completed_sandbox_snapshot(external_id=modal_image_id)
                version.snapshot_id = str(snapshot_id)
                version.snapshot_created_at = timezone.now()
                version.save(update_fields=["snapshot_id", "snapshot_created_at"])

            # Write before the proxy boots so it can read+unlink the file.
            bridge_token = create_sandbox_bridge_token(user=app.created_by, team_id=app.team_id)
            _write_bridge_token(sandbox, bridge_token)

            _start_auth_proxy(sandbox)
            _start_streamlit_process(sandbox)

            proxy_url = f"http://localhost:{AUTH_PROXY_PORT}/healthz"
            if not _wait_for_health(
                sandbox, proxy_url, "Auth proxy", deadline_seconds=AUTH_PROXY_HEALTH_DEADLINE_SECONDS
            ):
                try:
                    tail_result = sandbox.execute(
                        "tail -n 20 /tmp/auth_proxy.log 2>/dev/null || true", timeout_seconds=5
                    )
                    tail = (tail_result.stdout or "").strip()
                except Exception:
                    tail = ""
                raise AppRuntimeError("Auth proxy failed to become ready" + (f": {tail}" if tail else ""))

            # Streamlit's HTTP port opens a few seconds after the proxy is
            # live; without this second gate the iframe 502s against upstream.
            streamlit_url = f"http://localhost:{STREAMLIT_PORT}/_stcore/health"
            if not _wait_for_health(
                sandbox, streamlit_url, "Streamlit", deadline_seconds=STREAMLIT_HEALTH_DEADLINE_SECONDS
            ):
                raise AppRuntimeError("Streamlit failed to become ready")

            now = timezone.now()
            updated = StreamlitAppSandbox.objects.filter(id=sandbox_record.id).update(
                status=StreamlitAppSandbox.Status.RUNNING,
                started_at=now,
                last_activity_at=now,
                last_error="",
            )
            if updated:
                sandbox_record.refresh_from_db()
            else:
                logger.warning("sandbox_record_deleted_during_start", app_id=str(app.id))

            _schedule_restart_count_reset(str(app.id), app.team_id)

            return sandbox_record

        except Exception as e:
            StreamlitAppSandbox.objects.filter(id=sandbox_record.id).update(
                status=StreamlitAppSandbox.Status.ERROR,
                last_error=str(e),
            )
            if sandbox is not None:
                try:
                    sandbox.destroy()
                except Exception:
                    logger.warning("orphaned_sandbox_destroy_failed", app_id=str(app.id))
            raise

    def stop_app(self, app: StreamlitApp) -> None:
        with transaction.atomic():
            sandbox_record = StreamlitAppSandbox.objects.select_for_update().filter(app=app).first()
            if not sandbox_record:
                return

            sandbox_record.status = StreamlitAppSandbox.Status.STOPPING
            sandbox_record.save(update_fields=["status"])

        # Destroy outside the transaction — it hits Modal over the network.
        destroy_error: str | None = None
        if sandbox_record.sandbox_id:
            try:
                sandbox_class = get_sandbox_class()
                sandbox = sandbox_class.get_by_id(sandbox_record.sandbox_id)
                sandbox.destroy()
            except Exception as exc:
                destroy_error = str(exc) or "destroy() raised"
                logger.exception(
                    "streamlit_sandbox_destroy_failed",
                    app_id=str(app.id),
                    sandbox_id=sandbox_record.sandbox_id,
                )

        if destroy_error is None:
            sandbox_record.status = StreamlitAppSandbox.Status.STOPPED
            sandbox_record.save(update_fields=["status"])
        else:
            # Modal may still be running; TTL or cleanup will reclaim it.
            sandbox_record.status = StreamlitAppSandbox.Status.ERROR
            sandbox_record.last_error = f"Stop failed: {destroy_error}"[:1000]
            sandbox_record.save(update_fields=["status", "last_error"])

    def get_status(self, app: StreamlitApp) -> dict:
        sandbox_record = StreamlitAppSandbox.objects.filter(app=app).first()
        if not sandbox_record:
            return {
                "status": "stopped",
                "restart_count": app.restart_count,
            }

        sandbox_record = sync_sandbox_status(sandbox_record)

        return {
            "status": sandbox_record.status,
            "started_at": sandbox_record.started_at,
            "restart_count": app.restart_count,
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

        sandbox_record = sync_sandbox_status(sandbox_record)
        if sandbox_record.status != StreamlitAppSandbox.Status.RUNNING:
            return None

        try:
            sandbox_class = get_sandbox_class()
            sandbox = sandbox_class.get_by_id(sandbox_record.sandbox_id)
            credentials = sandbox.get_connect_credentials()
            return {"url": credentials.url, "token": credentials.token}
        except Exception:
            logger.exception("streamlit_connect_url_failed", extra={"app_id": str(app.id)})
            return None

    def restart_app(self, app: StreamlitApp, zip_content: bytes | None = None) -> StreamlitAppSandbox:
        # Lock the app row so concurrent restart_count check+increment serialize.
        with transaction.atomic():
            StreamlitApp.objects.select_for_update().get(id=app.id)

            sandbox_record = StreamlitAppSandbox.objects.filter(app=app).first()
            if sandbox_record and sandbox_record.status in (
                StreamlitAppSandbox.Status.STOPPING,
                StreamlitAppSandbox.Status.STARTING,
            ):
                raise AppRuntimeConcurrencyError("Another restart is already in progress.")

            current_count = StreamlitApp.objects.filter(id=app.id).values_list("restart_count", flat=True).first() or 0
            if current_count >= MAX_RESTART_COUNT:
                if sandbox_record:
                    sandbox_record.status = StreamlitAppSandbox.Status.ERROR
                    sandbox_record.last_error = f"Max restart count ({MAX_RESTART_COUNT}) exceeded"
                    sandbox_record.save(update_fields=["status", "last_error"])
                raise AppRuntimeError(f"Max restart count ({MAX_RESTART_COUNT}) exceeded")

            StreamlitApp.objects.filter(id=app.id).update(restart_count=F("restart_count") + 1)

        # Stop+start run outside the app lock — they each take their own
        # sandbox-row locks and hit Modal over the network.
        try:
            self.stop_app(app)
            return self.start_app(app, zip_content=zip_content)
        except Exception:
            # Roll the counter back so a transient Modal flap doesn't eat the cap.
            StreamlitApp.objects.filter(id=app.id).update(restart_count=F("restart_count") - 1)
            raise
