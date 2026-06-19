"""Render the consolidated dreaming-cleanup PR content from detected gaps.

The dreaming cleanup PR is intentionally a *pure instrumentation/cleanup* artifact: it does
not rewrite product code. Instead it consolidates every detected instrumentation gap into a
single tracked checklist file (``.posthog/dreaming-instrumentation-todo.md``) plus a PR body
that resurfaces the same findings for reviewers.

Writing a checklist file (rather than auto-editing the gapped files) keeps the singleton PR
safe to open unattended — it never touches product logic, only adds a reviewable to-do that a
human (or a follow-up coding task) can act on. The file is fully regenerated each run so the
amended PR always reflects the latest 24h of merges, never accreting stale entries.

This module is pure so the rendered content is unit-testable without GitHub.
"""

from __future__ import annotations

from products.signals.backend.temporal.dreaming.cleanup_pr import CleanupFileEdit
from products.signals.backend.temporal.dreaming.instrumentation_gaps import InstrumentationKind, PullRequestGaps

CLEANUP_FILE_PATH = ".posthog/dreaming-instrumentation-todo.md"

CLEANUP_PR_TITLE = "chore(dreaming): instrumentation cleanup"

_KIND_LABELS: dict[InstrumentationKind, str] = {
    InstrumentationKind.PRODUCT_ANALYTICS: "Product analytics",
    InstrumentationKind.ERROR_TRACKING: "Error tracking",
    InstrumentationKind.LLM_ANALYTICS: "LLM analytics",
}


def _render_body_lines(pr_gaps: list[PullRequestGaps]) -> list[str]:
    lines: list[str] = []
    for pr in pr_gaps:
        lines.append(f"### #{pr.pr_number} — {pr.pr_title}")
        lines.append("")
        for gap in pr.gaps:
            label = _KIND_LABELS.get(gap.kind, str(gap.kind))
            lines.append(f"- **{label}** in `{gap.file_path}`")
            if gap.line_hint:
                lines.append(f"  - `{gap.line_hint}`")
            lines.append(f"  - {gap.rationale}")
        lines.append("")
    return lines


def render_cleanup_file(pr_gaps: list[PullRequestGaps]) -> str:
    """Render the tracked checklist file content (fully regenerated each run)."""
    total = sum(len(pr.gaps) for pr in pr_gaps)
    lines = [
        "# Dreaming Agent — instrumentation cleanup",
        "",
        "_Auto-generated nightly by the PostHog Dreaming Agent. Regenerated each run._",
        "",
        f"Detected **{total}** instrumentation gap(s) across **{len(pr_gaps)}** recently merged PR(s).",
        "",
    ]
    lines.extend(_render_body_lines(pr_gaps))
    return "\n".join(lines).rstrip() + "\n"


def render_pr_body(pr_gaps: list[PullRequestGaps]) -> str:
    """Render the PR description that resurfaces the findings for reviewers."""
    total = sum(len(pr.gaps) for pr in pr_gaps)
    lines = [
        "## 🌙 Dreaming Agent — instrumentation cleanup",
        "",
        "The nightly Dreaming Agent reviewed recently merged PRs and found instrumentation that "
        "should likely accompany those changes. This PR consolidates the findings into "
        f"`{CLEANUP_FILE_PATH}` for review.",
        "",
        f"**{total}** gap(s) across **{len(pr_gaps)}** PR(s):",
        "",
    ]
    lines.extend(_render_body_lines(pr_gaps))
    lines.append("---")
    lines.append("")
    lines.append(
        "_This is the single, always-updated dreaming cleanup PR. Each nightly run refreshes "
        "it in place rather than opening a new one._"
    )
    return "\n".join(lines)


def build_cleanup_edits(pr_gaps: list[PullRequestGaps]) -> list[CleanupFileEdit]:
    """Build the file edits for the cleanup PR (one consolidated checklist file)."""
    if not pr_gaps:
        return []
    return [
        CleanupFileEdit(
            path=CLEANUP_FILE_PATH,
            content=render_cleanup_file(pr_gaps),
            commit_message="chore(dreaming): refresh instrumentation cleanup checklist",
        )
    ]
