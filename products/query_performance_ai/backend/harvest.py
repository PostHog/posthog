"""Harvest pi-autoresearch campaign artifacts out of a sandbox.

Pure helpers used by the smoke command to pull ``best.sql``, baseline /
best-run metrics, lane / hypothesis / review notes, and operator hunches
out of ``/tmp/autoresearch-campaign/`` inside a sandbox. Keeping this as
a separate module (rather than a Temporal activity) means the smoke
doesn't need to go through Temporal + Task machinery; a sandbox +
``sandbox.execute`` is enough.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field

from django.conf import settings

from products.tasks.backend.services.sandbox import Sandbox

# Where run_campaign.py initializes the campaign workspace inside the sandbox.
# Keeping it at a stable path makes the "cat this file back" harvesting step
# straightforward.
WORKSPACE_PATH = "/tmp/autoresearch-campaign"

# Which gateway product slug to route LLM calls under. "background_agents"
# already exists in posthog/llm/gateway_client.py's Product literal, so no
# gateway-side registration is needed.
LLM_GATEWAY_PRODUCT_SLUG = "background_agents"


def resolve_anthropic_base_url() -> str | None:
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


@dataclass
class RunAutoresearchCampaignOutput:
    """Structured snapshot of a campaign's workspace after pi exits.

    Any field can be empty if the campaign didn't produce it; a campaign
    with zero lane wins is still a successful run from the harvester's
    perspective.
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


def _read_sandbox_file(sandbox: Sandbox, path: str) -> str:
    """Return file contents or empty string when missing.

    We don't have a ``sandbox.read_file`` primitive today, so we ``cat``
    the path and rely on exit code 0 for presence. Paths are shell-quoted.
    """
    result = sandbox.execute(f"cat {shlex.quote(path)} 2>/dev/null || true", timeout_seconds=30)
    return result.stdout or ""


def _list_sandbox_dir(sandbox: Sandbox, dir_path: str) -> list[str]:
    """Return basenames of files directly inside ``dir_path``."""
    cmd = f"find {shlex.quote(dir_path)} -maxdepth 1 -type f -printf '%f\\n' 2>/dev/null || true"
    result = sandbox.execute(cmd, timeout_seconds=15)
    return [line for line in (result.stdout or "").splitlines() if line]


def _collect_markdown_dir(sandbox: Sandbox, dir_path: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name in sorted(_list_sandbox_dir(sandbox, dir_path)):
        if not name.endswith(".md") or name == "README.md":
            continue
        contents = _read_sandbox_file(sandbox, f"{dir_path}/{name}")
        if contents:
            out.append((name, contents))
    return out


def _best_run_metrics(sandbox: Sandbox) -> str:
    """Return ``runs/<best>/metrics.json`` contents, best == lowest primary value.

    pi tracks the best variant via ``query/best.sql``; this function
    surfaces the matching numeric metrics by scanning every run directory
    and picking the lowest ``primary.value``.
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


def harvest_artifacts(
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
