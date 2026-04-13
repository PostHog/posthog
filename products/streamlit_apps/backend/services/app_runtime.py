from __future__ import annotations

import os
import time
from io import BytesIO
from zipfile import ZipFile

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

import structlog

from products.streamlit_apps.backend.models import StreamlitApp, StreamlitAppSandbox, StreamlitAppVersion
from products.tasks.backend.services.sandbox import SandboxConfig, SandboxProtocol, SandboxTemplate, get_sandbox_class

logger = structlog.get_logger(__name__)

STREAMLIT_PORT = 8501
AUTH_PROXY_PORT = 8080
STREAMLIT_APP_PATH = "/app"
BRIDGE_TOKEN_PATH = "/run/bridge_token"
MAX_RESTART_COUNT = 3
STARTING_TIMEOUT_SECONDS = 600


class AppRuntimeError(Exception):
    pass


def _get_sandbox_callback_url() -> str:
    """URL that sandboxes use to call back to PostHog (OAuth introspect, bridge queries).

    Reads STREAMLIT_SANDBOX_CALLBACK_URL from the env, falling back to SITE_URL.
    For local dev, set STREAMLIT_SANDBOX_CALLBACK_URL to a public tunnel URL
    (e.g. ngrok) since Modal sandboxes can't reach localhost.
    """
    from django.conf import settings

    return os.environ.get("STREAMLIT_SANDBOX_CALLBACK_URL") or settings.SITE_URL


def _get_otel_logs_config(callback_url: str) -> tuple[str, str]:
    """Return (endpoint, token) for sandbox proxy OTEL log export.

    Mirrors the region-based selection in posthog.ph_client.get_regional_ph_client.
    On PostHog Cloud, sandbox proxy logs ship to the same PH-on-PH project that
    owns PostHog's own telemetry. In dev / self-hosted they ship back to the
    local instance via the same callback URL the sandbox already uses.
    """
    from posthog.cloud_utils import is_cloud
    from posthog.ph_client import PH_EU_API_KEY, PH_EU_HOST, PH_US_API_KEY, PH_US_HOST
    from posthog.utils import get_instance_region

    if is_cloud():
        region = get_instance_region()
        if region == "EU":
            return f"{PH_EU_HOST}/i/v1/logs", PH_EU_API_KEY
        # Default to US for unknown regions (matches get_regional_ph_client behavior)
        return f"{PH_US_HOST}/i/v1/logs", PH_US_API_KEY

    # Dev / self-hosted: ship to the local instance via the callback URL.
    # `phc_local` is the magic dev token that maps to team_id=1 in capture-logs.
    return f"{callback_url.rstrip('/')}/i/v1/logs", "phc_local"


def _build_sandbox_config(app: StreamlitApp, version: StreamlitAppVersion) -> SandboxConfig:
    from products.streamlit_apps.backend.services.oauth import get_streamlit_oauth_app

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
        cpu_cores=app.cpu_cores,
        memory_gb=app.memory_gb,
        ttl_seconds=60 * 15,
        environment_variables={
            "POSTHOG_SITE_URL": callback_url,
            # Per-sandbox team binding — the auth proxy refuses any introspected
            # token whose scoped_teams doesn't include this id, so a token from
            # another team can't unlock this sandbox even if its bytes leak.
            "POSTHOG_TEAM_ID": str(app.team_id),
            # Per-application binding — the auth proxy refuses tokens minted
            # against any OAuth application other than the Streamlit Apps one,
            # even if they have matching scoped_teams. This stops e.g. an
            # MCP-app token with query:read scope from unlocking the sandbox.
            "POSTHOG_STREAMLIT_CLIENT_ID": get_streamlit_oauth_app().client_id,
            # Standard OTEL env vars — the SDK reads these directly when the
            # proxy constructs OTLPLogExporter and Resource.create(). We don't
            # need to parse them in the proxy code.
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": otel_endpoint,
            "OTEL_EXPORTER_OTLP_HEADERS": f"authorization=Bearer {otel_token}",
            "OTEL_RESOURCE_ATTRIBUTES": otel_resource_attrs,
        },
    )
    if version.snapshot_id:
        config.snapshot_id = version.snapshot_id
    return config


def _upload_app_files(sandbox: SandboxProtocol, zip_content: bytes) -> None:
    """Upload zip contents to sandbox.

    Enforces uncompressed size limit by counting actual bytes read (defense-in-depth
    against forged zip header metadata). A `requirements.txt` in the upload is
    silently ignored — base-image packages are the only supported runtime.
    """
    from products.streamlit_apps.backend.services.zip_validator import MAX_UNCOMPRESSED_SIZE, is_safe_zip_path

    total_bytes = 0
    requirements_seen = False
    with ZipFile(BytesIO(zip_content)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if not is_safe_zip_path(info.filename):
                raise AppRuntimeError(f"Unsafe file path in zip: {info.filename}")
            normalized = os.path.normpath(info.filename)
            if normalized == "requirements.txt":
                # We dropped pip-install support — keep accepting old uploads but
                # don't propagate the file into the sandbox to avoid confusion.
                requirements_seen = True
                continue
            content = zf.read(info.filename)
            total_bytes += len(content)
            if total_bytes > MAX_UNCOMPRESSED_SIZE:
                raise AppRuntimeError(f"Zip uncompressed size exceeds limit ({MAX_UNCOMPRESSED_SIZE} bytes)")
            dest_path = f"{STREAMLIT_APP_PATH}/{normalized}"
            sandbox.write_file(dest_path, content)
    if requirements_seen:
        logger.info("streamlit_requirements_ignored")


def _write_bridge_token(sandbox: SandboxProtocol, token: str) -> None:
    """Drop the bridge bearer token at /run/bridge_token with mode 600.

    The auth proxy reads this once at startup and unlinks the file. Writing
    after the proxy starts would race the unlink, so this MUST happen before
    `_start_auth_proxy`. We use chmod via execute() because Modal's write_file
    doesn't expose mode bits directly.
    """
    sandbox.write_file(BRIDGE_TOKEN_PATH, token.encode("utf-8"))
    result = sandbox.execute(f"chmod 600 {BRIDGE_TOKEN_PATH}", timeout_seconds=5)
    if result.exit_code != 0:
        raise AppRuntimeError(f"Failed to chmod bridge token file: {result.stderr}")


def _start_auth_proxy(sandbox: SandboxProtocol) -> None:
    # `setsid -f` double-forks into a new session, fully detaching from the
    # control shell. The shell exit code is the exit of setsid itself, which
    # is 0 once the child has been spawned — we still rely on the readiness
    # poll below to detect a daemon that died on startup.
    result = sandbox.execute(
        "setsid -f sh -c 'python /usr/local/bin/streamlit_auth_proxy.py >/tmp/auth_proxy.log 2>&1'",
        timeout_seconds=10,
    )
    if result.exit_code != 0:
        raise AppRuntimeError(f"Failed to start auth proxy: {result.stderr}")


def _start_streamlit_process(sandbox: SandboxProtocol) -> None:
    """Boot Streamlit as the non-root `streamlit` user.

    Files uploaded via `sandbox.write_file` land in /app owned by root (the
    Modal shell runs as root), so we chown the dir over to the streamlit user
    before launching — Streamlit needs both read access on the app code and
    write access on /app for its internal cache. The bridge token at
    /run/bridge_token stays root-owned mode 600, which is the whole point:
    unreadable to this uid.
    """
    chown_result = sandbox.execute(
        f"chown -R streamlit:streamlit {STREAMLIT_APP_PATH}",
        timeout_seconds=5,
    )
    if chown_result.exit_code != 0:
        raise AppRuntimeError(f"Failed to chown {STREAMLIT_APP_PATH} to streamlit user: {chown_result.stderr}")

    # `runuser -u streamlit --` is a non-interactive "become this user" wrapper
    # from util-linux; preferred over `su` because it doesn't load the target
    # user's login shell and doesn't need a tty. The setsid -f double-forks so
    # the exec() returns immediately and the readiness poll below is the real
    # health check.
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


def _wait_for_proxy_ready(sandbox: SandboxProtocol, max_attempts: int = 20, delay_seconds: float = 1.0) -> bool:
    health_cmd = f"curl -s -o /dev/null -w '%{{http_code}}' http://localhost:{AUTH_PROXY_PORT}/healthz"
    for attempt in range(max_attempts):
        result = sandbox.execute(health_cmd, timeout_seconds=5)
        if result.stdout.strip() == "200":
            logger.info(f"Auth proxy health check passed on attempt {attempt + 1}")
            return True
        time.sleep(delay_seconds)
    return False


def _tail_proxy_log(sandbox: SandboxProtocol) -> str:
    """Best-effort tail of /tmp/auth_proxy.log for surfacing in last_error."""
    try:
        result = sandbox.execute("tail -n 20 /tmp/auth_proxy.log 2>/dev/null || true", timeout_seconds=5)
        return (result.stdout or "").strip()
    except Exception:
        return ""


_SYNC_FAILURE_THRESHOLD = 3
_SYNC_FAILURE_TTL_SECONDS = 600  # Reset counter after 10 minutes of no activity


def _sync_failure_key(sandbox_record: StreamlitAppSandbox) -> str:
    # Fall back to the PK when sandbox_id isn't set yet (STARTING, no Modal handle).
    return f"streamlit_sandbox_sync_failures:{sandbox_record.sandbox_id or sandbox_record.id}"


def _track_sync_failure(sandbox_record: StreamlitAppSandbox) -> int:
    from django.core.cache import cache

    key = _sync_failure_key(sandbox_record)
    try:
        new_value = cache.incr(key)
    except ValueError:
        cache.set(key, 1, _SYNC_FAILURE_TTL_SECONDS)
        return 1
    # Refresh the TTL on every increment so a slow drip of failures eventually
    # crosses the threshold (without this, a failure every 11 minutes would
    # never trip the circuit because incr() doesn't reset the original TTL).
    try:
        cache.touch(key, _SYNC_FAILURE_TTL_SECONDS)
    except (AttributeError, NotImplementedError):
        # Some Django cache backends don't implement touch — fall back to set.
        cache.set(key, new_value, _SYNC_FAILURE_TTL_SECONDS)
    return new_value


def _clear_sync_failures(sandbox_record: StreamlitAppSandbox) -> None:
    from django.core.cache import cache

    cache.delete(_sync_failure_key(sandbox_record))


def _sync_sandbox_status(sandbox_record: StreamlitAppSandbox) -> StreamlitAppSandbox:
    """Sync the DB sandbox status with the actual Modal sandbox state.

    Handles two cases:
    - RUNNING sandbox that has died → update to STOPPED
    - STARTING sandbox that is actually running → update to RUNNING

    Tracks consecutive failures via Django cache; after 3 strikes the record
    is marked ERROR so the UI reflects the broken state instead of spinning.
    """
    if sandbox_record.status not in (StreamlitAppSandbox.Status.RUNNING, StreamlitAppSandbox.Status.STARTING):
        return sandbox_record

    # Catch stale STARTING records (Celery task crashed before completion).
    # Use the sandbox row's own created_at — app.updated_at moves whenever any
    # field on the app changes, so we used to incorrectly extend this window.
    if sandbox_record.status == StreamlitAppSandbox.Status.STARTING and not sandbox_record.sandbox_id:
        age = (timezone.now() - sandbox_record.created_at).total_seconds()
        if age > STARTING_TIMEOUT_SECONDS:
            sandbox_record.status = StreamlitAppSandbox.Status.ERROR
            sandbox_record.last_error = "Startup timed out"
            sandbox_record.save(update_fields=["status", "last_error"])
            return sandbox_record
        return sandbox_record

    try:
        sandbox_class = get_sandbox_class()
        sandbox = sandbox_class.get_by_id(sandbox_record.sandbox_id)
        is_running = sandbox.is_running()

        if sandbox_record.status == StreamlitAppSandbox.Status.RUNNING and not is_running:
            sandbox_record.status = StreamlitAppSandbox.Status.STOPPED
            sandbox_record.last_error = "Sandbox terminated (TTL timeout)"
            sandbox_record.save(update_fields=["status", "last_error"])
        elif sandbox_record.status == StreamlitAppSandbox.Status.STARTING and is_running:
            sandbox_record.status = StreamlitAppSandbox.Status.RUNNING
            sandbox_record.started_at = timezone.now()
            sandbox_record.last_activity_at = timezone.now()
            sandbox_record.save(update_fields=["status", "started_at", "last_activity_at"])

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
    def __init__(self, download_zip=None):
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

            # Update the existing row in place rather than delete+recreate.
            # The previous flow lost any field that wasn't explicitly re-set,
            # which is how restart_count ended up needing a separate home.
            try:
                sandbox_record, _ = StreamlitAppSandbox.objects.update_or_create(
                    app=app,
                    defaults={
                        "version": version,
                        "sandbox_id": "",
                        "status": StreamlitAppSandbox.Status.STARTING,
                        "last_error": "",
                    },
                )
            except IntegrityError:
                # Another request won the race — return their record
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
                from products.tasks.backend.models import SandboxSnapshot

                snapshot = SandboxSnapshot.objects.create(
                    external_id=modal_image_id,
                    status=SandboxSnapshot.Status.COMPLETE,
                )
                version.snapshot_id = str(snapshot.id)
                version.snapshot_created_at = timezone.now()
                version.save(update_fields=["snapshot_id", "snapshot_created_at"])

            # File-based bridge token: write before the proxy boots so the
            # proxy can read+unlink it on its own startup. The token never
            # appears in /proc/<pid>/environ.
            from products.streamlit_apps.backend.services.oauth import create_sandbox_bridge_token

            bridge_token = create_sandbox_bridge_token(user=app.created_by, team_id=app.team_id)
            _write_bridge_token(sandbox, bridge_token)

            _start_auth_proxy(sandbox)
            _start_streamlit_process(sandbox)

            if not _wait_for_proxy_ready(sandbox):
                tail = _tail_proxy_log(sandbox)
                raise AppRuntimeError("Auth proxy failed to become ready" + (f": {tail}" if tail else ""))

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

            # On a confirmed-stable run, reset the per-app restart_count so a
            # later transient hiccup doesn't permanently ratchet the counter.
            StreamlitApp.objects.filter(id=app.id).update(restart_count=0)

            return sandbox_record

        except Exception as e:
            StreamlitAppSandbox.objects.filter(id=sandbox_record.id).update(
                status=StreamlitAppSandbox.Status.ERROR,
                last_error=str(e),
            )
            # Destroy orphaned sandbox to avoid resource leaks
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

        # Destroy outside transaction (network call to Modal)
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
            # The Modal sandbox may still be running; mark ERROR so the UI reflects
            # the broken state. Modal's TTL or a later cleanup pass will reclaim it.
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

        sandbox_record = _sync_sandbox_status(sandbox_record)

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

        sandbox_record = _sync_sandbox_status(sandbox_record)
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
        with transaction.atomic():
            sandbox_record = StreamlitAppSandbox.objects.select_for_update().filter(app=app).first()

            # If another restart is already in flight (we see STOPPING or a fresh
            # STARTING record), bail rather than stacking a second stop/start pair.
            # We can't just hold the row lock across stop_app + start_app — those
            # involve Modal network calls and would hold the Postgres row lock
            # for the full restart window, risking long lock waits elsewhere.
            if sandbox_record and sandbox_record.status in (
                StreamlitAppSandbox.Status.STOPPING,
                StreamlitAppSandbox.Status.STARTING,
            ):
                raise AppRuntimeError("Another restart is already in progress.")

            # restart_count now lives on the app row, so the cap survives across
            # sandbox lifecycles.
            current_count = StreamlitApp.objects.filter(id=app.id).values_list("restart_count", flat=True).first() or 0
            if current_count >= MAX_RESTART_COUNT:
                if sandbox_record:
                    sandbox_record.status = StreamlitAppSandbox.Status.ERROR
                    sandbox_record.last_error = f"Max restart count ({MAX_RESTART_COUNT}) exceeded"
                    sandbox_record.save(update_fields=["status", "last_error"])
                raise AppRuntimeError(f"Max restart count ({MAX_RESTART_COUNT}) exceeded")

            # Atomically increment so concurrent Celery tasks can't both read
            # the same count and bypass the cap.
            StreamlitApp.objects.filter(id=app.id).update(restart_count=F("restart_count") + 1)

        self.stop_app(app)
        return self.start_app(app, zip_content=zip_content)
