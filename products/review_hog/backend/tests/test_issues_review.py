import json

from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority, LineRange
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, FileInfo
from products.review_hog.backend.reviewer.tools.issues_review import _covered_findings_for_chunk


def _finding(file: str, title: str) -> ReviewIssueFinding:
    return ReviewIssueFinding(
        issue_key=f"r1:{file}:1:logic:1-1-1",
        run_index=1,
        title=title,
        file=file,
        lines=[LineRange(start=1)],
        body="the problem",
        suggestion="our private fix",
        priority=IssuePriority.SHOULD_FIX,
    )


def _chunk(*files: str) -> Chunk:
    return Chunk(chunk_id=1, files=[FileInfo(filename=f) for f in files], chunk_type="feature")


def test_covered_findings_filters_to_chunk_files_and_omits_suggestion() -> None:
    # The covered set feeds one chunk's review: only that chunk's files belong (other files are noise),
    # and our suggestion stays out (the agent must recognize the problem, not be handed our fix).
    out = _covered_findings_for_chunk([_finding("a.py", "in chunk"), _finding("z.py", "other file")], _chunk("a.py"))
    assert out is not None
    parsed = json.loads(out)
    assert [f["title"] for f in parsed] == ["in chunk"]
    assert "suggestion" not in parsed[0]
    assert "our private fix" not in out


def test_covered_findings_is_none_when_nothing_on_chunk_files() -> None:
    # None lets the prompt omit the section entirely (no empty "already covered" block on a first run).
    assert _covered_findings_for_chunk([_finding("a.py", "x")], _chunk("b.py")) is None
