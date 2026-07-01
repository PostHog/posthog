"""Helpers for the revamped-notebooks DataV2 run flow (Journey 1 slice).

The run endpoint dispatches a run to the notebook sandbox, which fabricates a
result envelope and POSTs it back to the token-authed callback endpoint. The
callback token is a stateless signed token for the slice; hardening (step 6)
swaps it for the RS256 sandbox event-ingest JWT used by PostHog Code.
"""

import json

from django.conf import settings
from django.core import signing

import structlog
import posthoganalytics

from posthog.models.user import User
from posthog.models.utils import uuid7

from products.notebooks.backend.models import KernelRuntime, Notebook, NotebookNodeRun
from products.tasks.backend.facade.sandbox import get_sandbox_class_for_backend

logger = structlog.get_logger(__name__)

REVAMPED_PY_NOTEBOOKS_FLAG = "revamped-py-notebooks"

_CALLBACK_TOKEN_SALT = "notebooks.data_v2.callback"
_CALLBACK_TOKEN_MAX_AGE_SECONDS = 3600


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


def _build_run_snippet(callback_url: str, token: str, envelope: dict) -> str:
    # Runs in the sandbox with stdlib only (no third-party deps assumed). Values are
    # embedded via json.dumps so no interpolation can break out of the literals.
    return (
        "import json, urllib.request\n"
        f"_url = {json.dumps(callback_url)}\n"
        f"_token = {json.dumps(token)}\n"
        f"_envelope = {json.dumps(envelope)}\n"
        '_data = json.dumps({"envelope": _envelope}).encode()\n'
        "_req = urllib.request.Request(\n"
        "    _url,\n"
        "    data=_data,\n"
        '    headers={"Authorization": "Bearer " + _token, "Content-Type": "application/json"},\n'
        '    method="POST",\n'
        ")\n"
        "try:\n"
        "    urllib.request.urlopen(_req, timeout=15)\n"
        "except Exception as _exc:\n"
        '    print("data_v2 callback failed", _exc)\n'
    )


def dispatch_data_v2_run(notebook: Notebook, user: User | None, run: NotebookNodeRun) -> None:
    """Fabricate the Journey 1 result (42) in the sandbox and have it call back.

    Slice stand-in for a real in-sandbox kernel-server /run route: writes a stdlib
    snippet into the sandbox and runs it detached so this call returns immediately.
    """
    runtime = _find_running_runtime(notebook, user)
    if runtime is None:
        raise DataV2KernelNotRunning()

    sandbox_class = get_sandbox_class_for_backend(runtime.backend)
    sandbox = sandbox_class.get_by_id(runtime.sandbox_id)

    result_id = str(uuid7())
    envelope = {
        "status": "ok",
        "columns": ["count"],
        "row_count": 1,
        "first_page": [[42]],
        "result_id": result_id,
    }
    token = mint_callback_token(str(run.id), notebook.team_id)
    callback_url = build_callback_url(str(run.id))
    snippet = _build_run_snippet(callback_url, token, envelope)

    path = f"/tmp/data_v2_run_{run.id}.py"
    sandbox.write_file(path, snippet.encode())
    # Detached (&) so execute returns immediately — the run stays async and the
    # result arrives via the callback, not this request.
    sandbox.execute(f"nohup python3 {path} >/tmp/data_v2_run_{run.id}.log 2>&1 &", timeout_seconds=15)
