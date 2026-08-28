"""Render the PR-facing review body (stored as `ReviewReport.report_markdown` and posted to GitHub).

The body opens with a one-line severity tally of the findings this turn publishes. The findings
themselves go out as inline comments from `publish_review` (read from the durable finding/verdict
rows), so the tally is all the body says about them — nobody reads a summary of the diff they just
wrote. The one exception is a finding GitHub can't take an inline comment on: those are written out
in full in the "Other findings" section below the tally, because the body is the only place they can
appear at all.
"""

from products.review_hog.backend.reviewer.constants import PRIORITIES_BY_URGENCY, PRIORITY_LABELS, effective_priority
from products.review_hog.backend.reviewer.diff_position import (
    build_diff_line_map,
    find_diff_position,
    format_line_ranges,
)
from products.review_hog.backend.reviewer.models.github_meta import PRFile
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority


def build_review_body(
    *,
    issues: list[Issue],
    validations: dict[str, IssueValidation],
    pr_files: list[PRFile],
    published_priorities: set[IssuePriority],
) -> str:
    """Render the PR-facing review body from this turn's in-process pipeline objects.

    `validations` is keyed by the live issue id (`{pass}-{chunk}-{issue}`); only issues the
    validator ruled valid are counted. `pr_files` (this turn's reviewed diff) decides which
    valid findings can't be anchored to an inline comment — those are surfaced in an "Other findings"
    section instead of being silently dropped at publish. `published_priorities` is the acting user's
    urgency-threshold set (`published_priorities_for`), shared with the publisher so the tally and the
    posted comments agree.
    """
    counts = _published_counts(issues, validations, published_priorities)
    off_diff = _off_diff_publishable_findings(issues, validations, pr_files, published_priorities)
    return _render_review_body(counts, off_diff)


def _published_counts(
    issues: list[Issue],
    validations: dict[str, IssueValidation],
    published_priorities: set[IssuePriority],
) -> dict[IssuePriority, int]:
    """Validated, publishable findings tallied by effective (validator-wins) severity."""
    counts = dict.fromkeys(IssuePriority, 0)
    for issue in issues:
        validation = validations.get(issue.id)
        if validation is None or not validation.is_valid:
            continue
        priority = effective_priority(issue.priority, validation.adjusted_priority)
        if priority in published_priorities:
            counts[priority] += 1
    return counts


def _off_diff_publishable_findings(
    issues: list[Issue],
    validations: dict[str, IssueValidation],
    pr_files: list[PRFile],
    published_priorities: set[IssuePriority],
) -> list[tuple[Issue, IssueValidation]]:
    """Valid publishable findings whose line isn't on the diff, so they get no inline comment.

    GitHub only takes inline comments on changed lines, so a valid finding on a changed file but an
    unchanged line would otherwise vanish at publish. The body surfaces these instead of dropping them.
    """
    diff_lines = build_diff_line_map(pr_files)
    out: list[tuple[Issue, IssueValidation]] = []
    for issue in issues:
        validation = validations.get(issue.id)
        if validation is None or not validation.is_valid:
            continue
        if effective_priority(issue.priority, validation.adjusted_priority) not in published_priorities:
            continue
        if find_diff_position(issue.file, issue.lines, diff_lines) is not None:
            continue  # has an inline anchor → posted inline, not here
        out.append((issue, validation))
    return out


def _render_review_body(
    counts: dict[IssuePriority, int],
    off_diff_findings: list[tuple[Issue, IssueValidation]],
) -> str:
    """Render the review body: the severity tally plus any off-diff findings section."""
    lines = [
        "# PostHog Review",
        "",
    ]

    breakdown = ", ".join(
        f"**{counts[priority]} {PRIORITY_LABELS[priority]}**" for priority in PRIORITIES_BY_URGENCY if counts[priority]
    )
    lines.extend([f"Found {breakdown}." if breakdown else "No issues to report.", ""])

    lines.extend(_render_off_diff_section(off_diff_findings))
    return "\n".join(lines)


def _render_off_diff_section(findings: list[tuple[Issue, IssueValidation]]) -> list[str]:
    """Render valid findings with no inline position as a body section (empty when there are none)."""
    if not findings:
        return []
    lines = [
        "## Other findings (outside the changed lines)",
        "",
        "_Valid issues on this PR's files that sit on lines GitHub won't let us comment on inline._",
        "",
    ]
    for issue, validation in findings:
        priority = effective_priority(issue.priority, validation.adjusted_priority)
        meta = [f"**Priority:** {priority.value}", f"**File:** `{issue.file}:{format_line_ranges(issue.lines)}`"]
        if validation.category:
            meta.append(f"**Category:** {validation.category}")
        lines.extend(
            [
                f"### {issue.title}",
                "",
                " | ".join(meta),
                "",
                "<details>",
                "<summary><strong>Why we think it's a valid issue</strong></summary>",
                "<br>",
                "",
                validation.argumentation,
                "",
                "</details>",
                "",
                "<details>",
                "<summary><strong>Issue description</strong></summary>",
                "<br>",
                "",
                issue.issue,
                "",
                "</details>",
                "",
                "<details>",
                "<summary><strong>Suggested fix</strong></summary>",
                "<br>",
                "",
                issue.suggestion,
                "",
                "</details>",
                "",
            ]
        )
    return lines
