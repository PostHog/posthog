"""Harvest pi-autoresearch campaign artifacts out of a sandbox.

Pure helpers the smoke command uses to pull workspace artifacts back to the
host via ``sandbox.execute`` — no Temporal/Task machinery needed.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field

from django.conf import settings

from products.tasks.backend.services.sandbox import SandboxBase

# Must match run_campaign.py's DEFAULT_WORKSPACE.
WORKSPACE_PATH = "/tmp/autoresearch-campaign"

# Re-used from posthog/llm/gateway_client.py's Product literal.
LLM_GATEWAY_PRODUCT_SLUG = "background_agents"


def resolve_anthropic_base_url() -> str | None:
    """Gateway URL to hand pi's Anthropic SDK as `ANTHROPIC_BASE_URL`.

    Returns `<gateway>/<product-slug>`; the SDK appends `/v1/messages`.
    """
    gateway_url = getattr(settings, "SANDBOX_LLM_GATEWAY_URL", None)
    if not gateway_url:
        return None
    return f"{gateway_url.rstrip('/')}/{LLM_GATEWAY_PRODUCT_SLUG}"


@dataclass
class RunAutoresearchCampaignOutput:
    """Workspace snapshot after pi exits. Any field may be empty —
    a campaign with zero wins is still a successful harvest."""

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


def _read_sandbox_file(sandbox: SandboxBase, path: str) -> str:
    """Return file contents, or empty string when missing."""
    result = sandbox.execute(f"cat {shlex.quote(path)} 2>/dev/null || true", timeout_seconds=30)
    return result.stdout or ""


def _list_sandbox_dir(sandbox: SandboxBase, dir_path: str) -> list[str]:
    """Return basenames of files directly inside ``dir_path``."""
    cmd = f"find {shlex.quote(dir_path)} -maxdepth 1 -type f -printf '%f\\n' 2>/dev/null || true"
    result = sandbox.execute(cmd, timeout_seconds=15)
    return [line for line in (result.stdout or "").splitlines() if line]


def _collect_markdown_dir(sandbox: SandboxBase, dir_path: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name in sorted(_list_sandbox_dir(sandbox, dir_path)):
        if not name.endswith(".md") or name == "README.md":
            continue
        contents = _read_sandbox_file(sandbox, f"{dir_path}/{name}")
        if contents:
            out.append((name, contents))
    return out


def _best_run_metrics(sandbox: SandboxBase) -> str:
    """Return metrics.json for the fastest run whose comparator said matches=true.

    A faster-but-wrong candidate must never be crowned the winner, so we
    require the adjacent comparison.json to report ``matches == True`` before
    admitting a run into the ranking.
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
        comparison_path = path.rsplit("/", 1)[0] + "/comparison.json"
        comparison_raw = _read_sandbox_file(sandbox, comparison_path)
        if not comparison_raw:
            continue
        try:
            comparison = json.loads(comparison_raw)
        except json.JSONDecodeError:
            continue
        if comparison.get("matches") is not True:
            continue
        if best_value is None or value < best_value:
            best_value = value
            best_contents = raw
    return best_contents


def harvest_artifacts(
    sandbox: SandboxBase,
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
