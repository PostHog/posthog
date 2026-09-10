import pytest

from products.review_hog.backend.reviewer.constants import published_priorities_for
from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRFileUpdate
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.tools.prepare_validation_markdown import build_review_body

# The should_fix threshold: publishes should_fix and must_fix, drops consider. These tests use it to
# exercise the publish gate, not the default (consider), which publishes everything.
_SHOULD_FIX_PUBLISHED = published_priorities_for(IssuePriority.SHOULD_FIX)


def _issue(issue_id: str, priority: IssuePriority = IssuePriority.MUST_FIX) -> Issue:
    return Issue(
        id=issue_id,
        title=f"Issue {issue_id}",
        file="src/auth.py",
        lines=[LineRange(start=1, end=2)],
        issue="problem",
        suggestion="fix",
        priority=priority,
    )


def _pr_files() -> list[PRFile]:
    # The reviewed diff touches lines 1-2 of src/auth.py, so a finding there is on-diff (inline-able).
    return [
        PRFile(
            filename="src/auth.py",
            status="modified",
            additions=2,
            deletions=0,
            changes=[PRFileUpdate(type="addition", new_start_line=1, new_end_line=2, code="x")],
        )
    ]


@pytest.mark.parametrize(
    "findings,expected_line",
    [
        # Only findings the validator ruled valid are tallied.
        (
            [(IssuePriority.MUST_FIX, None, True), (IssuePriority.MUST_FIX, None, False)],
            "Found **1 must fix**.",
        ),
        # Severities read most urgent first, and consider sits below the threshold so it never counts.
        (
            [
                (IssuePriority.CONSIDER, None, True),
                (IssuePriority.SHOULD_FIX, None, True),
                (IssuePriority.MUST_FIX, None, True),
            ],
            "Found **1 must fix**, **1 should fix**.",
        ),
        # Validator-wins: an upgrade joins the tally under its new severity.
        ([(IssuePriority.CONSIDER, IssuePriority.SHOULD_FIX, True)], "Found **1 should fix**."),
        # And a downgrade below the threshold leaves nothing to publish.
        ([(IssuePriority.SHOULD_FIX, IssuePriority.CONSIDER, True)], "No issues to report."),
    ],
)
def test_body_tallies_publishable_findings_by_severity(
    findings: list[tuple[IssuePriority, IssuePriority | None, bool]], expected_line: str
) -> None:
    # The body is a severity tally, so its one line has to count exactly what gets published: valid
    # findings at or above the acting user's threshold, bucketed by EFFECTIVE (validator-wins) severity.
    # A miscount here is the whole message being wrong. Asserting the WHOLE body (on-diff lines keep the
    # off-diff section out) also guards the point of the tally: no chunk headers, file lists, or diff
    # narrative creeping back in.
    issues = [_issue(f"1-1-{index}", priority=priority) for index, (priority, _, _) in enumerate(findings)]
    validations = {
        issue.id: IssueValidation(is_valid=is_valid, argumentation="reason", category="bug", adjusted_priority=adjusted)
        for issue, (_, adjusted, is_valid) in zip(issues, findings)
    }

    body = build_review_body(
        issues=issues,
        validations=validations,
        pr_files=_pr_files(),
        published_priorities=_SHOULD_FIX_PUBLISHED,
    )

    assert body == f"# PostHog Review\n\n{expected_line}\n"


@pytest.mark.parametrize(
    "priority,adjusted_priority,is_valid,line,expected_in_section",
    [
        (IssuePriority.SHOULD_FIX, None, True, 240, True),  # valid should_fix off-diff → surfaced, not dropped
        (IssuePriority.MUST_FIX, None, True, 240, True),  # valid must_fix off-diff → surfaced
        (IssuePriority.CONSIDER, None, True, 240, False),  # below the default should_fix threshold → not surfaced
        (IssuePriority.SHOULD_FIX, None, False, 240, False),  # invalid → not surfaced
        (IssuePriority.SHOULD_FIX, None, True, 1, False),  # on-diff → goes inline, not the body section
        (IssuePriority.CONSIDER, IssuePriority.SHOULD_FIX, True, 240, True),  # validator upgrade surfaces it
        (IssuePriority.SHOULD_FIX, IssuePriority.CONSIDER, True, 240, False),  # validator downgrade suppresses it
    ],
)
def test_other_findings_section_membership(
    priority: IssuePriority,
    adjusted_priority: IssuePriority | None,
    is_valid: bool,
    line: int,
    expected_in_section: bool,
) -> None:
    # The "Other findings" body section must contain exactly the valid findings whose EFFECTIVE priority
    # (validator-wins) is must/should-fix and which have no inline anchor (off-diff) — so an off-diff
    # valid finding isn't silently dropped at publish, while consider / invalid / on-diff findings don't
    # leak in, and a validator upgrade/downgrade moves the finding in or out. The title renders only in
    # this section (the tally lists no titles), so its presence is the membership signal.
    issue = Issue(
        id="1-1-1",
        title="Membership marker finding",
        file="src/auth.py",
        lines=[LineRange(start=line, end=line)],
        issue="problem",
        suggestion="fix",
        priority=priority,
    )
    validations = {
        "1-1-1": IssueValidation(
            is_valid=is_valid, argumentation="reason", category="bug", adjusted_priority=adjusted_priority
        )
    }

    body = build_review_body(
        issues=[issue],
        validations=validations,
        pr_files=_pr_files(),
        published_priorities=_SHOULD_FIX_PUBLISHED,
    )

    assert ("Membership marker finding" in body) is expected_in_section


def test_off_diff_finding_sections_lead_with_validation() -> None:
    # The off-diff section must render its collapsed blocks in the same deliberate reading order as
    # the inline comment (verdict first, then description, then fix). The two renderers are separate
    # templates, so the inline-comment order test can't catch _render_off_diff_section flipping back
    # to description-first.
    issue = Issue(
        id="1-1-1",
        title="Off-diff finding",
        file="src/auth.py",
        lines=[LineRange(start=240, end=240)],
        issue="problem",
        suggestion="fix",
        priority=IssuePriority.SHOULD_FIX,
    )
    validations = {"1-1-1": IssueValidation(is_valid=True, argumentation="verified", category="bug")}

    body = build_review_body(
        issues=[issue],
        validations=validations,
        pr_files=_pr_files(),
        published_priorities=_SHOULD_FIX_PUBLISHED,
    )

    positions = [
        body.index(f"<summary><strong>{label}</strong></summary>")
        for label in ("Why we think it's a valid issue", "Issue description", "Suggested fix")
    ]
    assert positions == sorted(positions)
