"""Activity that drives the ``autoresearch_campaign`` Task mode.

Instead of starting an agent-server and waiting for Claude to run experiments,
this activity directly invokes ``products/query_performance_ai/scripts/run_campaign.py``
inside the sandbox. The script handles pi toolchain install, campaign init
through the proxy, baseline capture, and the pi LLM loop.

The activity reads the task description as JSON, mints a scoped OAuth token,
passes both through the sandbox via env vars, and then harvests the workspace
artifacts (``best.sql``, ``operator-hunches.md``, lane/hypothesis notes, …)
into a structured :class:`RunAutoresearchCampaignOutput` for downstream
handoff to the PR-writing Task.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field

from django.conf import settings

from temporalio import activity

from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import Task
from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.exceptions import SandboxExecutionError, TaskInvalidStateError
from products.tasks.backend.temporal.oauth import create_oauth_access_token
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution

from .get_task_processing_context import TaskProcessingContext

logger = get_logger(__name__)

# Where run_campaign.py initializes the campaign workspace inside the sandbox.
# Keeping it at a stable path makes the "cat this file back" harvesting step
# straightforward.
WORKSPACE_PATH = "/tmp/autoresearch-campaign"

# Which gateway product slug to route LLM calls under. "background_agents"
# already exists in posthog/llm/gateway_client.py's Product literal, so no
# gateway-side registration is needed.
LLM_GATEWAY_PRODUCT_SLUG = "background_agents"


def _resolve_anthropic_base_url() -> str | None:
    """Build the Anthropic-compatible gateway URL for pi-coding-agent.

    The gateway exposes native Anthropic-format ``/v1/messages`` under the
    product-scoped path ``/{product}/v1/messages`` (see
    ``services/llm-gateway/src/llm_gateway/api/anthropic.py``), so the
    ANTHROPIC_BASE_URL we hand the SDK is just
    ``<gateway>/{product}`` — the SDK itself appends ``/v1/messages``.
    """
    gateway_url = getattr(settings, "SANDBOX_LLM_GATEWAY_URL", None)
    if not gateway_url:
        return None
    return f"{gateway_url.rstrip('/')}/{LLM_GATEWAY_PRODUCT_SLUG}"


# Campaign runs are long (LLM loop + many CH round-trips). The overall
# Temporal activity timeout is set generously; inside, we still cap the child
# processes so a hung pi call doesn't burn the whole budget.
CAMPAIGN_SCRIPT_TIMEOUT_S = 45 * 60


@dataclass
class RunAutoresearchCampaignInput:
    context: TaskProcessingContext
    sandbox_id: str


@dataclass
class RunAutoresearchCampaignOutput:
    """Structured handoff to the PR-writing Task.

    Any field can be empty if the campaign failed to produce it, but the
    activity itself only fails on setup or unrecoverable errors — a campaign
    that produces zero lane wins is still a successful run.
    """

    original_sql: str
    query_id: str
    baseline_metrics_json: str = ""
    best_sql: str = ""
    best_metrics_json: str = ""
    last_run_json: str = ""
    operator_hunches: str = ""
    suggestions: str = ""
    lanes: list[tuple[str, str]] = field(default_factory=list)  # (filename, contents)
    hypotheses: list[tuple[str, str]] = field(default_factory=list)
    reviews: list[tuple[str, str]] = field(default_factory=list)
    campaign_stdout_tail: str = ""


def _parse_task_description(task: Task) -> tuple[str, str]:
    """Extract ``(sql, query_id)`` from a QUERY_PERFORMANCE task.

    Expected payload shape::

        {"sql": "SELECT ...", "query_id": "slow-query-abc"}

    We tolerate either ``query_id`` missing (generated from task id) or the
    whole thing being a bare SQL string (useful for manual invocations).
    """
    description = (task.description or "").strip()
    if not description:
        raise TaskInvalidStateError(
            f"Task {task.id} has no description; cannot run autoresearch",
            {"task_id": task.id},
            cause=RuntimeError("empty description"),
        )
    try:
        payload = json.loads(description)
        if isinstance(payload, dict) and "sql" in payload:
            sql = str(payload["sql"]).strip()
            query_id = str(payload.get("query_id") or f"task-{task.id}").strip()
            return sql, query_id
    except json.JSONDecodeError:
        pass
    return description, f"task-{task.id}"


def _read_sandbox_file(sandbox: Sandbox, path: str, *, optional: bool = True) -> str:
    """Return file contents or empty string when missing.

    We don't have a ``sandbox.read_file`` primitive today, so we use
    ``cat`` and rely on exit code 0 for presence. Paths are shell-quoted.
    """
    result = sandbox.execute(f"cat {shlex.quote(path)} 2>/dev/null || true", timeout_seconds=30)
    contents = result.stdout or ""
    if not contents and not optional:
        raise SandboxExecutionError(
            f"required file missing in sandbox: {path}",
            {"path": path, "sandbox_id": sandbox.id},
            cause=RuntimeError("file missing"),
        )
    return contents


def _list_sandbox_files(sandbox: Sandbox, glob: str) -> list[str]:
    """Return filenames matching a glob (basename only, not paths)."""
    # ``find -printf '%f\n'`` is portable; ``maxdepth 1`` so we only pick up
    # the matching dir's direct children.
    cmd = f"find {shlex.quote(glob)} -maxdepth 1 -type f -printf '%f\\n' 2>/dev/null || true"
    result = sandbox.execute(cmd, timeout_seconds=15)
    return [line for line in (result.stdout or "").splitlines() if line]


def _collect_markdown_dir(sandbox: Sandbox, dir_path: str) -> list[tuple[str, str]]:
    names = _list_sandbox_files(sandbox, dir_path)
    out: list[tuple[str, str]] = []
    for name in sorted(names):
        if not name.endswith(".md"):
            continue
        if name == "README.md":
            continue
        contents = _read_sandbox_file(sandbox, f"{dir_path}/{name}")
        if contents:
            out.append((name, contents))
    return out


def _best_run_metrics(sandbox: Sandbox) -> str:
    """Return ``runs/<best>/metrics.json`` contents, best == lowest latency_ms.

    We let the agent pick "best" inside the campaign by tracking ``best.sql``;
    this function surfaces the numeric metrics alongside, scanning all runs.
    """
    cmd = f'for m in {WORKSPACE_PATH}/runs/*/metrics.json; do   [ -f "$m" ] && echo "$m"; done'
    result = sandbox.execute(cmd, timeout_seconds=15)
    metric_paths = [p for p in (result.stdout or "").splitlines() if p]
    best_value: float | None = None
    best_contents = ""
    for path in metric_paths:
        raw = _read_sandbox_file(sandbox, path)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        value = (data.get("primary") or {}).get("value")
        if not isinstance(value, int | float) or value < 0:
            continue
        if best_value is None or value < best_value:
            best_value = value
            best_contents = raw
    return best_contents


def _harvest_artifacts(
    sandbox: Sandbox,
    *,
    original_sql: str,
    query_id: str,
    campaign_stdout_tail: str,
) -> RunAutoresearchCampaignOutput:
    return RunAutoresearchCampaignOutput(
        original_sql=original_sql,
        query_id=query_id,
        baseline_metrics_json=_read_sandbox_file(sandbox, f"{WORKSPACE_PATH}/baseline/metrics.json"),
        best_sql=_read_sandbox_file(sandbox, f"{WORKSPACE_PATH}/query/best.sql") or original_sql,
        best_metrics_json=_best_run_metrics(sandbox),
        last_run_json=_read_sandbox_file(sandbox, f"{WORKSPACE_PATH}/runtime/last_run.json"),
        operator_hunches=_read_sandbox_file(sandbox, f"{WORKSPACE_PATH}/operator-hunches.md"),
        suggestions=_read_sandbox_file(sandbox, f"{WORKSPACE_PATH}/suggestions.md"),
        lanes=_collect_markdown_dir(sandbox, f"{WORKSPACE_PATH}/lanes"),
        hypotheses=_collect_markdown_dir(sandbox, f"{WORKSPACE_PATH}/hypotheses"),
        reviews=_collect_markdown_dir(sandbox, f"{WORKSPACE_PATH}/reviews"),
        campaign_stdout_tail=campaign_stdout_tail,
    )


@activity.defn
@asyncify
def run_autoresearch_campaign_in_sandbox(
    input: RunAutoresearchCampaignInput,
) -> RunAutoresearchCampaignOutput:
    ctx = input.context
    sandbox = Sandbox.get_by_id(input.sandbox_id)

    with log_activity_execution(
        "run_autoresearch_campaign_in_sandbox",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        task = Task.objects.select_related("created_by").get(id=ctx.task_id)
        sql, query_id = _parse_task_description(task)

        scope = "clickhouse_perf:test_read"
        emit_agent_log(ctx.run_id, "info", f"Minting scoped OAuth token (scope={scope})")
        token = create_oauth_access_token(task, scopes=[scope])

        # The sandbox reaches PostHog via POSTHOG_API_URL, set by sandbox
        # provisioning; fall back to SITE_URL for local/dev runs where the
        # sandbox shares the host's network.
        posthog_url = getattr(settings, "POSTHOG_API_URL", None) or settings.SITE_URL

        if not ctx.repository:
            raise TaskInvalidStateError(
                f"Task {task.id} has no repository; autoresearch needs the posthog source cloned",
                {"task_id": task.id},
                cause=RuntimeError("missing repository"),
            )
        org, repo = ctx.repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        emit_agent_log(ctx.run_id, "info", f"Invoking run_campaign.py for query_id={query_id}")

        # Route pi-coding-agent's Anthropic SDK calls through PostHog's LLM
        # gateway. The gateway auto-accepts our scoped token (llm_gateway:read
        # is in INTERNAL_SCOPES) and the Anthropic SDK POSTs to
        # {ANTHROPIC_BASE_URL}/v1/messages, which matches the gateway's
        # product-scoped route.
        anthropic_base_url = _resolve_anthropic_base_url()
        if not anthropic_base_url:
            emit_agent_log(
                ctx.run_id,
                "warn",
                "SANDBOX_LLM_GATEWAY_URL is unset; pi-coding-agent will fall back to "
                "the sandbox's ANTHROPIC_API_KEY (if any) and hit Anthropic directly",
            )

        env_values = {
            "POSTHOG_URL": posthog_url,
            "POSTHOG_OAUTH_TOKEN": token,
            "CAMPAIGN_SQL": sql,
            "CAMPAIGN_QUERY_ID": query_id,
        }
        if anthropic_base_url:
            env_values["ANTHROPIC_BASE_URL"] = anthropic_base_url
            env_values["ANTHROPIC_API_KEY"] = token

        env_assignments = " ".join(
            f"{name}={shlex.quote(value)}" for name, value in env_values.items() if value is not None
        )
        command = (
            f"cd {shlex.quote(repo_path)} && "
            f"env {env_assignments} "
            f"python3 products/query_performance_ai/scripts/run_campaign.py"
        )

        try:
            result = sandbox.execute(command, timeout_seconds=CAMPAIGN_SCRIPT_TIMEOUT_S)
        except Exception as e:
            raise SandboxExecutionError(
                "run_campaign.py failed to execute",
                {"sandbox_id": input.sandbox_id, "task_id": task.id},
                cause=e,
            )

        stdout_tail = (result.stdout or "")[-4000:]
        if result.exit_code != 0:
            emit_agent_log(
                ctx.run_id,
                "error",
                f"run_campaign.py exited {result.exit_code}. Tail:\n{stdout_tail}\n---stderr---\n{(result.stderr or '')[-2000:]}",
            )
            raise SandboxExecutionError(
                f"run_campaign.py exited with {result.exit_code}",
                {
                    "sandbox_id": input.sandbox_id,
                    "task_id": task.id,
                    "exit_code": result.exit_code,
                    "stdout_tail": stdout_tail,
                    "stderr_tail": (result.stderr or "")[-2000:],
                },
                cause=RuntimeError(f"exit code {result.exit_code}"),
            )

        emit_agent_log(ctx.run_id, "info", "Campaign completed; harvesting artifacts")
        return _harvest_artifacts(
            sandbox,
            original_sql=sql,
            query_id=query_id,
            campaign_stdout_tail=stdout_tail,
        )
