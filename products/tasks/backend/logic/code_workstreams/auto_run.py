from collections.abc import Mapping
from typing import Any, Optional

# Pure decision + prompt-building helpers for auto-running Home quick actions.
# The Temporal activity owns the DB reads/writes and task creation; everything
# here is side-effect free so it can be unit-tested without a worker.


def select_auto_actions(bindings: Mapping[str, Any], primary_situation: Optional[str]) -> list[dict]:
    """Auto-enabled actions bound to a workstream's primary situation.

    We only consider the primary situation (not every situation the workstream is
    in) so at most one situation's actions can fire per workstream per cycle.
    Skips malformed entries and actions without a usable id.
    """
    if not primary_situation:
        return []
    actions = bindings.get(primary_situation) or []
    if not isinstance(actions, list):
        return []
    return [
        action
        for action in actions
        if isinstance(action, dict) and action.get("auto") is True and str(action.get("id", "")).strip()
    ]


def build_skill_prompt(skill_id: Optional[str], prompt: Optional[str]) -> str:
    """`/<skill-id>\\n\\n<body>` — the `/<skill-id>` prefix is how the agent finds the skill.

    Mirrors `buildSkillPrompt` in packages/core/src/home/workstreamPrompt.ts.
    """
    body = (prompt or "").strip()
    skill = (skill_id or "").strip()
    if not skill:
        return body
    command = f"/{skill}"
    return f"{command}\n\n{body}" if body else command


def build_workstream_context(
    *,
    repo_full_path: Optional[str],
    branch: Optional[str],
    pr_url: Optional[str],
    pr: Optional[Mapping[str, Any]],
) -> str:
    """Anchor the run to the PR/branch it should act on so it doesn't ask the user.

    Mirrors `buildWorkstreamContext` in packages/core/src/home/workstreamPrompt.ts.
    `pr` is the per-user-resolved PrSnapshot wire dict stored on `CodeWorkstream.pr`.
    """
    lines: list[str] = []
    if repo_full_path:
        lines.append(f"- Repository: {repo_full_path}")
    if branch:
        lines.append(f"- Branch: {branch}")
    if pr:
        lines.append(f"- Pull request #{pr.get('number')}: {pr.get('title')}")
        lines.append(f"  {pr.get('url')}")
        lines.append(f"  CI: {pr.get('ciStatus')}")
        if pr.get("reviewDecision"):
            lines.append(f"  Review: {pr.get('reviewDecision')}")
        if (pr.get("unresolvedThreads") or 0) > 0:
            lines.append(f"  Unresolved review threads: {pr.get('unresolvedThreads')}")
    elif pr_url:
        lines.append(f"- Pull request: {pr_url}")
    if not lines:
        return ""
    header = "Context for this task (already known — don't ask the user for it):"
    return "\n\n" + header + "\n" + "\n".join(lines)


def build_auto_run_prompt(
    action: Mapping[str, Any],
    *,
    repo_full_path: Optional[str],
    branch: Optional[str],
    pr_url: Optional[str],
    pr: Optional[Mapping[str, Any]],
) -> str:
    """Full prompt for an auto-fired quick action.

    Mirrors `buildQuickActionPrompt` (the manual quick action's client-side prompt)
    so an auto run reaches the agent with the same skill + workstream context.
    """
    return build_skill_prompt(action.get("skillId"), action.get("prompt")) + build_workstream_context(
        repo_full_path=repo_full_path,
        branch=branch,
        pr_url=pr_url,
        pr=pr,
    )
