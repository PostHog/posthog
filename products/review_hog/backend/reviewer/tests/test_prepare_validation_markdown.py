from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, ChunksList, FileInfo
from products.review_hog.backend.reviewer.tools.prepare_validation_markdown import build_review_body


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


def test_only_validated_issues_count_and_chunk_appears() -> None:
    # One valid + one invalid issue on the same chunk: the body shows the chunk (with a humanized
    # header) and counts only the valid one.
    chunks_data = ChunksList(chunks=[_chunk(1, "business_logic")])
    issues = [_issue("1-1-1"), _issue("1-1-2")]
    validations = {
        "1-1-1": IssueValidation(is_valid=True, argumentation="real bug", category="bug"),
        "1-1-2": IssueValidation(is_valid=False, argumentation="not a bug", category="code_quality"),
    }

    body = build_review_body(chunks_data=chunks_data, issues=issues, validations=validations)

    assert "# ReviewHog Report" in body
    assert "## Business logic" in body  # chunk_type humanized into the header
    assert "**Issues:** 1 issue" in body  # only the valid issue counts


def test_chunk_with_no_valid_issue_is_skipped() -> None:
    # chunk 2 has no validated issue, so it must not clutter the body (which summarizes findings, not
    # coverage); chunk 1 has a valid finding and appears.
    chunks_data = ChunksList(chunks=[_chunk(1, "bugfix"), _chunk(2, "frontend")])
    issues = [_issue("1-1-1")]
    validations = {"1-1-1": IssueValidation(is_valid=True, argumentation="real", category="bug")}

    body = build_review_body(chunks_data=chunks_data, issues=issues, validations=validations)

    assert "## Bugfix" in body
    assert "## Frontend" not in body
