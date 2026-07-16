import pytest

from products.review_hog.backend.reviewer.constants import published_priorities_for
from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRFileUpdate
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, ChunksList, FileInfo
from products.review_hog.backend.reviewer.tools.prepare_validation_markdown import build_review_body

# The default (should_fix) threshold — matches the pre-threshold PUBLISHED_PRIORITIES behavior these
# tests were written against.
_DEFAULT_PUBLISHED = published_priorities_for(IssuePriority.SHOULD_FIX)


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


def _chunk(chunk_id: int, chunk_type: str) -> Chunk:
    return Chunk(chunk_id=chunk_id, files=[FileInfo(filename="src/auth.py")], chunk_type=chunk_type, key_changes=[])


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


def test_only_validated_issues_count_and_chunk_appears() -> None:
    # One valid + one invalid issue on the same chunk: the body shows the chunk (with a humanized
    # header) and counts only the valid one.
    chunks_data = ChunksList(chunks=[_chunk(1, "business_logic")])
    issues = [_issue("1-1-1"), _issue("1-1-2")]
    validations = {
        "1-1-1": IssueValidation(is_valid=True, argumentation="real bug", category="bug"),
        "1-1-2": IssueValidation(is_valid=False, argumentation="not a bug", category="code_quality"),
    }

    body = build_review_body(
        chunks_data=chunks_data,
        issues=issues,
        validations=validations,
        pr_files=_pr_files(),
        published_priorities=_DEFAULT_PUBLISHED,
    )

    assert "# ReviewHog Report" in body
    assert "## Business logic" in body  # chunk_type humanized into the header
    assert "**Issues:** 1 issue" in body  # only the valid issue counts


def test_chunk_with_no_valid_issue_is_skipped() -> None:
    # chunk 2 has no validated issue, so it must not clutter the body (which summarizes findings, not
    # coverage); chunk 1 has a valid finding and appears.
    chunks_data = ChunksList(chunks=[_chunk(1, "bugfix"), _chunk(2, "frontend")])
    issues = [_issue("1-1-1")]
    validations = {"1-1-1": IssueValidation(is_valid=True, argumentation="real", category="bug")}

    body = build_review_body(
        chunks_data=chunks_data,
        issues=issues,
        validations=validations,
        pr_files=_pr_files(),
        published_priorities=_DEFAULT_PUBLISHED,
    )

    assert "## Bugfix" in body
    assert "## Frontend" not in body


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
    # this section (the per-chunk summary lists no titles), so its presence is the membership signal.
    chunks_data = ChunksList(chunks=[_chunk(1, "bugfix")])
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
        chunks_data=chunks_data,
        issues=[issue],
        validations=validations,
        pr_files=_pr_files(),
        published_priorities=_DEFAULT_PUBLISHED,
    )

    assert ("Membership marker finding" in body) is expected_in_section


@pytest.mark.parametrize(
    "base,adjusted,expected_count_line",
    [
        (IssuePriority.CONSIDER, IssuePriority.SHOULD_FIX, "**Issues:** 1 issue"),  # upgrade joins the count
        (IssuePriority.SHOULD_FIX, IssuePriority.CONSIDER, None),  # downgrade drops out of the count
    ],
)
def test_chunk_count_reflects_effective_priority(
    base: IssuePriority, adjusted: IssuePriority, expected_count_line: str | None
) -> None:
    # The per-chunk "Issues: N" count must reflect the validator's override, not the reviewer's frozen
    # priority — a finding downgraded to consider stops counting, an upgraded one starts. Uses an
    # on-diff line so the off-diff section never interferes with the count signal.
    chunks_data = ChunksList(chunks=[_chunk(1, "bugfix")])
    issue = _issue("1-1-1", priority=base)
    validations = {
        "1-1-1": IssueValidation(is_valid=True, argumentation="reason", category="bug", adjusted_priority=adjusted)
    }

    body = build_review_body(
        chunks_data=chunks_data,
        issues=[issue],
        validations=validations,
        pr_files=_pr_files(),
        published_priorities=_DEFAULT_PUBLISHED,
    )

    if expected_count_line is None:
        assert "**Issues:**" not in body
    else:
        assert expected_count_line in body
