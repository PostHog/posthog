import pytest

from parameterized import parameterized
from pydantic import ValidationError

from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.thread_resolution import ThreadOutcome, ThreadResolution
from products.review_hog.backend.reviewer.tools.github_threads import ReviewThread, ThreadComment
from products.review_hog.backend.reviewer.tools.thread_resolution import (
    build_resolution_followup_prompt,
    build_resolution_prompt,
)


def _thread(thread_id: str = "PRRT_1", *, body: str = "please fix this") -> ReviewThread:
    return ReviewThread(
        thread_id=thread_id,
        path="posthog/models.py",
        line=42,
        comments=[
            ThreadComment(
                id=1,
                author_login="alice",
                author_association="MEMBER",
                body=body,
                created_at="2026-07-01T00:00:00Z",
            )
        ],
    )


class TestThreadResolution:
    def test_fixed_requires_commit_sha(self) -> None:
        with pytest.raises(ValidationError, match="commit_sha"):
            ThreadResolution(thread_id="PRRT_1", outcome=ThreadOutcome.FIXED, reasoning="r", reply="done")

    @parameterized.expand([(o.value,) for o in ThreadOutcome if o != ThreadOutcome.FIXED])
    def test_non_fixed_outcomes_need_no_commit(self, outcome: str) -> None:
        parsed = ThreadResolution(thread_id="PRRT_1", outcome=outcome, reasoning="r", reply="answered")
        assert parsed.commit_sha is None

    def test_prompt_renders_skill_pin_work_list_and_schema(self, pr_metadata: PRMetadata) -> None:
        threads = [_thread("PRRT_1"), _thread("PRRT_2", body="second ask")]
        # The current thread is passed explicitly: a session restarting mid-list opens on a LATER
        # thread than the inventory's first, and the opener must carry that one.
        prompt = build_resolution_prompt(
            threads=threads,
            thread=threads[1],
            pr_metadata=pr_metadata,
            skill_name="review-hog-resolution-criteria",
            skill_version=3,
        )
        # The criteria pull must be pinned, the inventory must list every thread's excerpt, the
        # schema must be embedded, and the current-thread section must carry the thread that was
        # passed — a template/schema regression here only fails at runtime.
        assert 'skill-get(skill_name="review-hog-resolution-criteria", version=3)' in prompt
        assert "please fix this" in prompt and "second ask" in prompt
        assert '"ThreadOutcome"' in prompt
        current_section = prompt.split("<current_thread>", 1)[1]
        assert "thread_id: PRRT_2" in current_section

    def test_followup_prompt_carries_only_the_next_thread(self) -> None:
        prompt = build_resolution_followup_prompt(thread=_thread("PRRT_9", body="the next ask"))
        assert "PRRT_9" in prompt and "the next ask" in prompt
        assert "skill-get" not in prompt  # the warm session already holds the criteria

    def test_pathological_comment_bodies_are_clipped(self) -> None:
        prompt = build_resolution_followup_prompt(thread=_thread("PRRT_9", body="x" * 50_000))
        assert "truncated" in prompt
        assert len(prompt) < 20_000
