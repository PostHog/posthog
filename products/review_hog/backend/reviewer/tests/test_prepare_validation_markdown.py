from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis, ChunkMeta
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


def _analysis(chunk_id: int, goal: str) -> ChunkAnalysis:
    return ChunkAnalysis(goal=goal, chunk_meta=ChunkMeta(chunk_id=chunk_id, files_in_this_chunk=["src/auth.py"]))


def _chunk(chunk_id: int, chunk_type: str) -> Chunk:
    return Chunk(chunk_id=chunk_id, files=[FileInfo(filename="src/auth.py")], chunk_type=chunk_type, key_changes=[])


def test_only_validated_issues_count_toward_chunk_issue_line() -> None:
    # One valid + one invalid issue on the same chunk; the body must count only the valid one.
    chunks_data = ChunksList(chunks=[_chunk(1, "bugfix")])
    analyses = {1: _analysis(1, "Fix the auth bug")}
    issues = [_issue("1-1-1"), _issue("1-1-2")]
    validations = {
        "1-1-1": IssueValidation(is_valid=True, argumentation="real bug", category="bug"),
        "1-1-2": IssueValidation(is_valid=False, argumentation="not a bug", category="code_quality"),
    }

    body = build_review_body(chunks_data=chunks_data, analyses=analyses, issues=issues, validations=validations)

    assert "**Issues:** 1 issue" in body


def test_body_contains_header_chunk_header_and_analysis_goal() -> None:
    goal = "This chunk rewires the auth handshake and adds retry handling."
    chunks_data = ChunksList(chunks=[_chunk(1, "business_logic")])
    analyses = {1: _analysis(1, goal)}

    body = build_review_body(chunks_data=chunks_data, analyses=analyses, issues=[], validations={})

    assert "# ReviewHog Report" in body
    # chunk_type "business_logic" is humanized into the chunk header
    assert "## Business logic" in body
    assert goal in body


def test_chunk_without_analysis_is_skipped() -> None:
    # chunk 2 has no analysis entry, so it must not appear in the rendered body.
    chunks_data = ChunksList(chunks=[_chunk(1, "bugfix"), _chunk(2, "frontend")])
    analyses = {1: _analysis(1, "Fix the auth bug")}

    body = build_review_body(chunks_data=chunks_data, analyses=analyses, issues=[], validations={})

    assert "## Bugfix" in body
    assert "## Frontend" not in body
