from collections.abc import Callable
from dataclasses import dataclass

from parameterized import parameterized

from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, FileInfo
from products.review_hog.backend.reviewer.tools.issue_validation import (
    build_validation_followup_prompt,
    build_validation_prompt,
)
from products.review_hog.backend.reviewer.tools.issues_review import build_review_prompt
from products.review_hog.backend.reviewer.tools.prompt_helpers import load_template_and_schema
from products.review_hog.backend.reviewer.tools.select_perspectives import generate_selection_prompt
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import generate_chunking_prompt


@dataclass
class _Perspective:
    skill_name: str
    description: str


def _pr_metadata() -> PRMetadata:
    return PRMetadata(
        number=1,
        title="t",
        state="open",
        draft=False,
        created_at="c",
        updated_at="u",
        author="octocat",
        base_branch="main",
        head_branch="feat",
        commits=1,
        additions=1,
        deletions=0,
        changed_files=1,
    )


def _chunk() -> Chunk:
    return Chunk(chunk_id=1, files=[FileInfo(filename="a.py")], chunk_type="feature")


def _issue() -> Issue:
    return Issue(
        id="1-1-1",
        title="t",
        file="a.py",
        lines=[LineRange(start=1)],
        issue="the problem",
        suggestion="the fix",
        priority=IssuePriority.SHOULD_FIX,
    )


def _issues_review_prompt() -> str:
    return build_review_prompt(
        skill_name="review-hog-perspective-logic-correctness",
        skill_version=2,
        chunk=_chunk(),
        pr_metadata=_pr_metadata(),
        pr_comments=[],
        pr_files=[],
        prior_findings=[],
    )


def _chunking_prompt() -> str:
    return generate_chunking_prompt(_pr_metadata(), [], [])


def _selection_prompt() -> str:
    return generate_selection_prompt(
        _pr_metadata(), [_chunk()], [], [_Perspective("review-hog-perspective-logic-correctness", "logic")]
    )


def _validation_prompt() -> str:
    return build_validation_prompt(
        issue=_issue(),
        chunk=_chunk(),
        skill_name="review-hog-validation-general",
        skill_version=1,
        pr_metadata=_pr_metadata(),
        pr_files=[],
    )


def _validation_followup_prompt() -> str:
    return build_validation_followup_prompt(issue=_issue(), pr_files=[])


def _dedup_prompt() -> str:
    template, _ = load_template_and_schema("issue_deduplicator")
    return template.render()


class TestPromptInjectionGuards:
    # Every prompt that embeds PR-author-controlled text (title/body, comments, diffs) must tell
    # the model to treat that text as data, never instructions — otherwise a crafted PR can steer
    # the review into dropping real findings. Prompts get rewritten during eval rounds; this
    # catches a retune that silently drops the guard.
    @parameterized.expand(
        [
            ("issues_review", _issues_review_prompt),
            ("chunking", _chunking_prompt),
            ("perspective_selection", _selection_prompt),
            ("issue_validation", _validation_prompt),
            ("issue_validation_followup", _validation_followup_prompt),
            ("issue_deduplicator", _dedup_prompt),
        ]
    )
    def test_prompt_carries_the_untrusted_content_guard(self, _name: str, render: Callable[[], str]) -> None:
        prompt = render().lower()
        assert "untrusted" in prompt
        assert "instruction" in prompt
