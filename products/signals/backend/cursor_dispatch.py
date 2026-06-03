"""Dispatch a signal report to a Cursor Cloud Agent.

Behind the ``signals-cursor-dispatch`` feature flag. Reads the report's research
artefacts (summary, priority, the relevant code paths and commits, selected repo)
and hands Cursor a localized brief via ``POST /v1/agents``. The agent runs on
Cursor's cloud and opens a PR. Dedup across double-clicks relies on Cursor's
``agentId`` idempotency key, derived from the report id.
"""

import json
from dataclasses import dataclass, field

import requests
import structlog

from products.signals.backend.models import SignalReport, SignalReportArtefact

logger = structlog.get_logger(__name__)

SIGNALS_CURSOR_DISPATCH_FLAG = "signals-cursor-dispatch"

CURSOR_AGENTS_API_URL = "https://api.cursor.com/v1/agents"
CURSOR_AGENT_WEB_URL_BASE = "https://cursor.com/agents"
CURSOR_REQUEST_TIMEOUT_SECONDS = 30

POSTHOG_MCP_URL = "https://mcp.posthog.com/mcp"

DEFAULT_BRANCH = "main"


class CursorDispatchError(Exception):
    """Raised when dispatching a report to Cursor cannot proceed or fails."""


@dataclass
class CursorDispatchContext:
    repository: str | None
    title: str
    summary: str
    report_url: str
    default_branch: str = DEFAULT_BRANCH
    priority: str | None = None
    priority_reason: str | None = None
    code_paths: list[str] = field(default_factory=list)
    commit_hashes: list[str] = field(default_factory=list)


@dataclass
class CursorDispatchResult:
    agent_id: str | None
    agent_url: str | None
    agent_status: str | None


def agent_id_for_report(report_id: str) -> str:
    # Cursor requires the idempotency key in the format bc-<uuid>; the report id is a UUID.
    return f"bc-{report_id}"


def _github_url(repository: str) -> str:
    if repository.startswith("http://") or repository.startswith("https://"):
        return repository
    return f"https://github.com/{repository}"


def _latest_artefact_content(report: SignalReport, artefact_type: str) -> dict | None:
    artefact = report.artefacts.filter(type=artefact_type).order_by("-created_at").first()
    if artefact is None:
        return None
    try:
        parsed = json.loads(artefact.content)
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "signals.cursor_dispatch.bad_artefact_json", report_id=str(report.id), artefact_type=artefact_type
        )
        return None
    return parsed if isinstance(parsed, dict) else None


def _gather_findings(report: SignalReport) -> tuple[list[str], list[str]]:
    """Union the relevant code paths and commit hashes across all signal_finding artefacts."""
    code_paths: list[str] = []
    commit_hashes: list[str] = []
    findings = report.artefacts.filter(type=SignalReportArtefact.ArtefactType.SIGNAL_FINDING).order_by("created_at")
    for artefact in findings:
        try:
            content = json.loads(artefact.content)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(content, dict):
            continue
        for path in content.get("relevant_code_paths") or []:
            if path not in code_paths:
                code_paths.append(path)
        commits = content.get("relevant_commit_hashes") or {}
        if isinstance(commits, dict):
            for commit_hash in commits:
                if commit_hash not in commit_hashes:
                    commit_hashes.append(commit_hash)
    return code_paths, commit_hashes


def build_cursor_dispatch_context(report: SignalReport, site_url: str) -> CursorDispatchContext:
    repo_selection = _latest_artefact_content(report, SignalReportArtefact.ArtefactType.REPO_SELECTION) or {}
    priority_judgment = _latest_artefact_content(report, SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT) or {}
    code_paths, commit_hashes = _gather_findings(report)

    repository = repo_selection.get("repository")

    return CursorDispatchContext(
        repository=repository if isinstance(repository, str) else None,
        title=report.title or "Signal report",
        summary=report.summary or "",
        report_url=f"{site_url.rstrip('/')}/project/{report.team_id}/inbox/{report.id}",
        priority=priority_judgment.get("priority"),
        priority_reason=priority_judgment.get("explanation"),
        code_paths=code_paths,
        commit_hashes=commit_hashes,
    )


def build_cursor_agent_prompt(context: CursorDispatchContext) -> str:
    lines: list[str] = [context.summary, ""]
    if context.priority:
        reason = f" — {context.priority_reason}" if context.priority_reason else ""
        lines.append(f"Priority: {context.priority}{reason}")
    if context.repository:
        lines.append(f"Repository: {context.repository}")
    if context.code_paths:
        lines.append("Relevant files:")
        lines.extend(f"- {path}" for path in context.code_paths)
    if context.commit_hashes:
        lines.append(f"Relevant commits: {', '.join(context.commit_hashes)}")
    lines.extend(
        [
            "",
            "Investigate the root cause, implement a minimal fix, and open a PR.",
            f"Link this report in the PR description footer: {context.report_url}",
        ]
    )
    return "\n".join(lines)


def build_cursor_agent_request(
    context: CursorDispatchContext,
    *,
    agent_id: str,
    model: str | None = None,
    posthog_mcp_token: str | None = None,
) -> dict:
    if not context.repository:
        raise CursorDispatchError("Report has no selected repository to act on")

    body: dict = {
        "prompt": {"text": build_cursor_agent_prompt(context)},
        "repos": [{"url": _github_url(context.repository), "startingRef": context.default_branch}],
        "autoCreatePR": True,
        "agentId": agent_id,
    }
    if model:
        body["model"] = {"id": model}
    if posthog_mcp_token:
        body["mcpServers"] = [
            {
                "name": "posthog",
                "url": POSTHOG_MCP_URL,
                "headers": {"Authorization": f"Bearer {posthog_mcp_token}"},
            }
        ]
    return body


def dispatch_report_to_cursor(
    report: SignalReport,
    *,
    api_key: str,
    site_url: str,
    posthog_mcp_token: str | None = None,
) -> CursorDispatchResult:
    context = build_cursor_dispatch_context(report, site_url)
    body = build_cursor_agent_request(
        context,
        agent_id=agent_id_for_report(str(report.id)),
        posthog_mcp_token=posthog_mcp_token,
    )

    try:
        response = requests.post(
            CURSOR_AGENTS_API_URL,
            json=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=CURSOR_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise CursorDispatchError(f"Request to Cursor failed: {e}") from e

    if response.status_code == 409:
        # Cursor rejects a duplicate agentId; this report was already dispatched.
        existing_id = agent_id_for_report(str(report.id))
        return CursorDispatchResult(
            agent_id=existing_id,
            agent_url=f"{CURSOR_AGENT_WEB_URL_BASE}/{existing_id}",
            agent_status="already_dispatched",
        )

    if response.status_code >= 400:
        raise CursorDispatchError(f"Cursor returned {response.status_code}: {response.text[:500]}")

    try:
        data = response.json()
    except ValueError as e:
        raise CursorDispatchError(f"Cursor returned a non-JSON response: {e}") from e

    agent = data.get("agent") or {}
    return CursorDispatchResult(
        agent_id=agent.get("id"),
        agent_url=agent.get("url"),
        agent_status=agent.get("status"),
    )
