"""Helpers for the revamped-notebooks SQLV2 run flow (Journey 1).

The backend dispatches a run to the in-sandbox kernel-server with a single HTTP
POST (mirroring PostHog Code's agent-server). The kernel-server fetches the
node's capped result page from the data-plane endpoint (real ClickHouse data via
HogQL) and POSTs the envelope back to the token-authed callback endpoint. The
control plane (write_file / execute) is used only to deploy and launch the
kernel-server package — never per run.

The callback and data-plane tokens are stateless signed tokens for the slice;
hardening swaps them for the RS256 sandbox event-ingest JWTs used by PostHog Code.
"""

import hmac
import time
import hashlib

from django.conf import settings
from django.core import signing

import requests
import structlog
import posthoganalytics

from posthog.models.user import User

from products.notebooks.backend.kernel_package import SANDBOX_PACKAGE_NAME, kernel_package_bytes_and_hash
from products.notebooks.backend.models import KernelRuntime, Notebook, NotebookNodeRun
from products.tasks.backend.facade.sandbox import SandboxBase, get_sandbox_class_for_backend

logger = structlog.get_logger(__name__)

REVAMPED_PY_NOTEBOOKS_FLAG = "revamped-py-notebooks"

_CALLBACK_TOKEN_SALT = "notebooks.sql_v2.callback"
_CALLBACK_TOKEN_MAX_AGE_SECONDS = 3600
_DATA_PLANE_TOKEN_SALT = "notebooks.sql_v2.data_plane"
_DATA_PLANE_TOKEN_MAX_AGE_SECONDS = 3600

# Rows in the display page the kernel fetches for a run. Paging beyond it re-queries
# ClickHouse (push-to-CH: a displayed HogQL node is never fully materialized).
DISPLAY_PAGE_LIMIT = 50

# The container port the sandbox already exposes (mapped to a host port at create
# time). Mirrors docker_sandbox.AGENT_SERVER_PORT (47821) and
# modal_sandbox.AGENT_SERVER_PORT (8080) — the kernel-server binds it inside the sandbox.
_CONTAINER_PORT_BY_BACKEND: dict[str, int] = {
    KernelRuntime.Backend.DOCKER: 47821,
    KernelRuntime.Backend.MODAL: 8080,
}
_PACKAGE_ROOT = "/tmp/nb_kernel_pkg"
_TARBALL_PATH = "/tmp/nb_kernel.tar.gz"
_SECRET_PATH = "/tmp/nb_sql_v2_secret"
_SERVER_LOG_PATH = "/tmp/nb_kernel_server.log"
_SERVER_PID_PATH = "/tmp/nb_kernel_server.pid"
_SERVER_READY_TIMEOUT_SECONDS = 15
_RUN_POST_TIMEOUT_SECONDS = 10
_COMMAND_TOKEN_TTL_SECONDS = 300


class SQLV2KernelNotRunning(Exception):
    """Raised when a run is dispatched but the notebook has no running sandbox."""


def is_sql_v2_enabled(user: User | None) -> bool:
    if user is None or not user.distinct_id:
        return False
    kwargs: dict = {"only_evaluate_locally": False, "send_feature_flag_events": False}
    org = getattr(user, "organization", None)
    if org is not None:
        org_id = str(org.id)
        kwargs["groups"] = {"organization": org_id}
        kwargs["group_properties"] = {"organization": {"id": org_id}}
    return bool(posthoganalytics.feature_enabled(REVAMPED_PY_NOTEBOOKS_FLAG, user.distinct_id, **kwargs))


def mint_callback_token(run_id: str, team_id: int) -> str:
    return signing.dumps({"run_id": run_id, "team_id": team_id}, salt=_CALLBACK_TOKEN_SALT)


def verify_callback_token(token: str) -> tuple[str, int]:
    """Return (run_id, team_id) from a valid token, else raise signing.BadSignature."""
    data = signing.loads(token, salt=_CALLBACK_TOKEN_SALT, max_age=_CALLBACK_TOKEN_MAX_AGE_SECONDS)
    return str(data["run_id"]), int(data["team_id"])


def kernel_server_secret(runtime_id: str) -> str:
    """Per-kernel command-auth secret, derived from Django's signing key.

    Only the backend can derive it (holds SECRET_KEY); a copy is written into the
    sandbox at bootstrap so the kernel-server can verify command tokens. Nothing to
    persist. This is the HMAC analogue of Code's RS256 connection-JWT keypair;
    hardening to RS256 would let the sandbox hold only a public key.
    """
    return hmac.new(
        settings.SECRET_KEY.encode(),
        f"nb-sql-v2-kernel:{runtime_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def mint_command_token(secret: str, run_id: str, ttl_seconds: int = _COMMAND_TOKEN_TTL_SECONDS) -> str:
    """Sign a short-lived, run-scoped command token; `kernel.auth` verifies it in the sandbox."""
    exp = int(time.time()) + ttl_seconds
    signature = hmac.new(secret.encode(), f"{run_id}.{exp}".encode(), hashlib.sha256).hexdigest()
    return f"{run_id}.{exp}.{signature}"


def _backend_base_url() -> str:
    # The sandbox reaches the host backend here. Docker maps localhost -> host.docker.internal,
    # so default to that for local dev; SANDBOX_API_URL overrides (e.g. ngrok for Modal).
    base = getattr(settings, "SANDBOX_API_URL", None) or "http://host.docker.internal:8000"
    return base.rstrip("/")


def build_callback_url(run_id: str) -> str:
    return f"{_backend_base_url()}/internal/notebooks/runs/{run_id}/result/"


def build_data_plane_url() -> str:
    return f"{_backend_base_url()}/internal/notebooks/data_plane/query/"


def mint_data_plane_token(notebook_short_id: str, team_id: int, user_id: int | None) -> str:
    return signing.dumps(
        {"notebook_short_id": notebook_short_id, "team_id": team_id, "user_id": user_id},
        salt=_DATA_PLANE_TOKEN_SALT,
    )


def verify_data_plane_token(token: str) -> tuple[str, int, int | None]:
    """Return (notebook_short_id, team_id, user_id) from a valid token, else raise signing.BadSignature."""
    data = signing.loads(token, salt=_DATA_PLANE_TOKEN_SALT, max_age=_DATA_PLANE_TOKEN_MAX_AGE_SECONDS)
    user_id = data.get("user_id")
    return str(data["notebook_short_id"]), int(data["team_id"]), int(user_id) if user_id is not None else None


def _find_running_runtime(notebook: Notebook, user: User | None) -> KernelRuntime | None:
    runtime = (
        KernelRuntime.objects.filter(
            team_id=notebook.team_id,
            notebook_short_id=notebook.short_id,
            user=user if isinstance(user, User) else None,
        )
        .order_by("-last_used_at")
        .first()
    )
    if runtime is None or not runtime.sandbox_id:
        return None
    if runtime.status not in (KernelRuntime.Status.RUNNING, KernelRuntime.Status.STARTING):
        return None
    return runtime


def _with_connect_token(url: str, connect_token: str | None) -> str:
    return f"{url}?_modal_connect_token={connect_token}" if connect_token else url


def _server_version(server_url: str, connect_token: str | None) -> str | None:
    """The deployed package hash the running server reports, or None if unreachable."""
    health_url = _with_connect_token(f"{server_url.rstrip('/')}/health", connect_token)
    try:
        response = requests.get(health_url, timeout=2)
        if response.status_code != 200:
            return None
        return str(response.json().get("version") or "")
    except (requests.RequestException, ValueError):
        return None


def _wait_for_server_ready(server_url: str, connect_token: str | None, expected_version: str) -> None:
    deadline = time.monotonic() + _SERVER_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _server_version(server_url, connect_token) == expected_version:
            return
        time.sleep(0.3)
    raise RuntimeError("SQLV2 kernel-server did not become ready")


def _deploy_kernel_server(sandbox: SandboxBase, runtime: KernelRuntime, package: bytes, version: str) -> None:
    """Write the kernel package + secret into the sandbox and (re)launch the server.

    This is the only place the control plane (write_file/execute) is used, exactly
    as Code bootstraps its agent-server. Per-run dispatch is a plain authed POST.
    """
    port = _CONTAINER_PORT_BY_BACKEND.get(runtime.backend, 47821)
    sandbox.write_file(_SECRET_PATH, kernel_server_secret(str(runtime.id)).encode())
    sandbox.write_file(_TARBALL_PATH, package)
    # Stop a previous server via its PID file — never pkill by our own name: the
    # pattern would match this very launch command's shell and kill it mid-deploy.
    # The pkill lines only clear pre-package servers (distinct names, safe to
    # match) from sandboxes that predate the PID file; drop them once those age out.
    # `< /dev/null` detaches the server from the exec's pipes so `execute` returns.
    # Prefer the notebook venv python (has pyarrow).
    launch = (
        f"kill $(cat {_SERVER_PID_PATH} 2>/dev/null) 2>/dev/null || true; "
        "pkill -f '[n]b_sql_v2_kernel_server' 2>/dev/null; pkill -f '[n]b_data_v2_kernel_server' 2>/dev/null; "
        f"rm -rf {_PACKAGE_ROOT} && mkdir -p {_PACKAGE_ROOT} && tar -xzf {_TARBALL_PATH} -C {_PACKAGE_ROOT} && "
        'PY=/opt/notebook-venv/bin/python3; [ -x "$PY" ] || PY=python3; '
        f"cd {_PACKAGE_ROOT} && nohup $PY -m {SANDBOX_PACKAGE_NAME}.server "
        f"--port {port} --secret-file {_SECRET_PATH} --version {version} "
        f"> {_SERVER_LOG_PATH} 2>&1 < /dev/null & echo $! > {_SERVER_PID_PATH}"
    )
    sandbox.execute(launch, timeout_seconds=30)


def ensure_sql_v2_server(notebook: Notebook, user: User | None) -> KernelRuntime:
    """Ensure the in-sandbox kernel-server is running the current package version.

    Idempotent — a healthy server at the expected version is reused as-is; a stale
    or unreachable one is redeployed from the freshly built tarball (this is the
    dev loop: edit `kernel/`, next run redeploys, no image rebuild).
    """
    runtime = _find_running_runtime(notebook, user)
    if runtime is None:
        raise SQLV2KernelNotRunning()

    package, version = kernel_package_bytes_and_hash()
    if runtime.server_url and _server_version(runtime.server_url, runtime.server_connect_token) == version:
        return runtime

    sandbox_class = get_sandbox_class_for_backend(runtime.backend)
    assert runtime.sandbox_id  # _find_running_runtime only returns runtimes with a sandbox
    sandbox = sandbox_class.get_by_id(runtime.sandbox_id)
    _deploy_kernel_server(sandbox, runtime, package, version)

    credentials = sandbox.get_connect_credentials()
    _wait_for_server_ready(credentials.url, credentials.token, version)

    runtime.server_url = credentials.url
    runtime.server_connect_token = credentials.token
    runtime.save(update_fields=["server_url", "server_connect_token"])
    return runtime


def dispatch_sql_v2_run(notebook: Notebook, user: User | None, run: NotebookNodeRun, code: str) -> None:
    """Dispatch a run to the in-sandbox kernel-server with a single authed HTTP POST.

    Returns as soon as the server accepts (202); the result arrives via the callback.
    """
    runtime = ensure_sql_v2_server(notebook, user)
    assert runtime.server_url  # ensure_sql_v2_server always returns a runtime with a live server_url
    command_token = mint_command_token(kernel_server_secret(str(runtime.id)), str(run.id))
    user_id = user.id if isinstance(user, User) else None
    response = requests.post(
        _with_connect_token(f"{runtime.server_url.rstrip('/')}/run", runtime.server_connect_token),
        json={
            "run_id": str(run.id),
            "code": code,
            "callback_url": build_callback_url(str(run.id)),
            "callback_token": mint_callback_token(str(run.id), notebook.team_id),
            "data_plane_url": build_data_plane_url(),
            "data_plane_token": mint_data_plane_token(notebook.short_id, notebook.team_id, user_id),
            "page_limit": DISPLAY_PAGE_LIMIT,
        },
        headers={"Authorization": f"Bearer {command_token}"},
        timeout=_RUN_POST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
