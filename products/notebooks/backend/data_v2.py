"""Helpers for the revamped-notebooks DataV2 run flow (Journey 1 slice).

The backend dispatches a run to the in-sandbox kernel-server with a single HTTP
POST (mirroring PostHog Code's agent-server), which fabricates a result and POSTs
it back to the token-authed callback endpoint. The control plane (write_file /
execute) is used only once, to launch the kernel-server — never per run.

The callback token is a stateless signed token for the slice; hardening swaps it
for the RS256 sandbox event-ingest JWT used by PostHog Code.
"""

import time

from django.conf import settings
from django.core import signing

import requests
import structlog
import posthoganalytics

from posthog.models.user import User

from products.notebooks.backend.data_v2_kernel_server import KERNEL_SERVER_SOURCE
from products.notebooks.backend.models import KernelRuntime, Notebook, NotebookNodeRun
from products.tasks.backend.facade.sandbox import get_sandbox_class_for_backend

logger = structlog.get_logger(__name__)

REVAMPED_PY_NOTEBOOKS_FLAG = "revamped-py-notebooks"

_CALLBACK_TOKEN_SALT = "notebooks.data_v2.callback"
_CALLBACK_TOKEN_MAX_AGE_SECONDS = 3600

# The container port the sandbox already exposes (mapped to a host port at create
# time). Mirrors docker_sandbox.AGENT_SERVER_PORT (47821) and
# modal_sandbox.AGENT_SERVER_PORT (8080) — the kernel-server binds it inside the sandbox.
_CONTAINER_PORT_BY_BACKEND = {
    KernelRuntime.Backend.DOCKER: 47821,
    KernelRuntime.Backend.MODAL: 8080,
}
_KERNEL_SERVER_PATH = "/tmp/nb_data_v2_kernel_server.py"
_SERVER_READY_TIMEOUT_SECONDS = 15
_RUN_POST_TIMEOUT_SECONDS = 10


class DataV2KernelNotRunning(Exception):
    """Raised when a run is dispatched but the notebook has no running sandbox."""


def is_data_v2_enabled(user: User | None) -> bool:
    if user is None or not getattr(user, "distinct_id", None):
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


def _backend_base_url() -> str:
    # The sandbox reaches the host backend here. Docker maps localhost -> host.docker.internal,
    # so default to that for local dev; SANDBOX_API_URL overrides (e.g. ngrok for Modal).
    base = getattr(settings, "SANDBOX_API_URL", None) or "http://host.docker.internal:8000"
    return base.rstrip("/")


def build_callback_url(run_id: str) -> str:
    return f"{_backend_base_url()}/internal/notebooks/runs/{run_id}/result/"


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


def _wait_for_server_ready(server_url: str, connect_token: str | None) -> None:
    health_url = _with_connect_token(f"{server_url.rstrip('/')}/health", connect_token)
    deadline = time.monotonic() + _SERVER_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            if requests.get(health_url, timeout=2).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.3)
    raise RuntimeError("DataV2 kernel-server did not become ready")


def ensure_data_v2_server(notebook: Notebook, user: User | None) -> tuple[str, str | None]:
    """Start the in-sandbox kernel-server once; return its (url, connect_token).

    Idempotent — reuses the URL persisted on the runtime after the first start.
    This is the only place the control plane (write_file/execute) is used, and only
    to launch the server, exactly as Code bootstraps its agent-server. Per-run
    dispatch is a plain HTTP POST.
    """
    runtime = _find_running_runtime(notebook, user)
    if runtime is None:
        raise DataV2KernelNotRunning()

    if runtime.server_url:
        return runtime.server_url, runtime.server_connect_token

    sandbox_class = get_sandbox_class_for_backend(runtime.backend)
    sandbox = sandbox_class.get_by_id(runtime.sandbox_id)

    port = _CONTAINER_PORT_BY_BACKEND.get(runtime.backend, 47821)
    sandbox.write_file(_KERNEL_SERVER_PATH, KERNEL_SERVER_SOURCE.encode())
    sandbox.execute(
        f"nohup python3 {_KERNEL_SERVER_PATH} {port} > /tmp/nb_data_v2_kernel_server.log 2>&1 &",
        timeout_seconds=15,
    )

    credentials = sandbox.get_connect_credentials()
    _wait_for_server_ready(credentials.url, credentials.token)

    runtime.server_url = credentials.url
    runtime.server_connect_token = credentials.token
    runtime.save(update_fields=["server_url", "server_connect_token"])
    return credentials.url, credentials.token


def dispatch_data_v2_run(notebook: Notebook, user: User | None, run: NotebookNodeRun, code: str) -> None:
    """Dispatch a run to the in-sandbox kernel-server with a single HTTP POST.

    Returns as soon as the server accepts (202); the result arrives via the callback.
    """
    server_url, connect_token = ensure_data_v2_server(notebook, user)
    callback_token = mint_callback_token(str(run.id), notebook.team_id)
    response = requests.post(
        _with_connect_token(f"{server_url.rstrip('/')}/run", connect_token),
        json={
            "run_id": str(run.id),
            "code": code,
            "callback_url": build_callback_url(str(run.id)),
            "callback_token": callback_token,
        },
        timeout=_RUN_POST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
