import pytest
from unittest.mock import AsyncMock, patch

from products.review_hog.backend.reviewer.constants import FLASH_LENSES, SINGLE_AGENT_SOURCE
from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRFileUpdate, PRMetadata
from products.review_hog.backend.reviewer.models.issue_deduplicator import DuplicateIssue, IssueDeduplication
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.tools.single_agent_review import (
    SingleAgentPrompt,
    compose_flash_findings,
    dedupe_flash_findings,
)

_MODULE = "products.review_hog.backend.reviewer.tools.single_agent_review"
_DEDUP_MODULE = "products.review_hog.backend.reviewer.tools.issue_deduplicator"
_LENS_SOURCE = FLASH_LENSES["contracts-security"].source


def _file(filename: str, code: str) -> PRFile:
    return PRFile(
        filename=filename,
        status="modified",
        additions=1,
        deletions=0,
        changes=[PRFileUpdate(type="addition", new_start_line=1, new_end_line=1, code=code)],
    )


def _issue(issue_id: str, priority: IssuePriority, source: str = SINGLE_AGENT_SOURCE) -> Issue:
    return Issue(
        id=issue_id,
        title=f"Issue {issue_id}",
        file="a.py",
        lines=[LineRange(start=10)],
        issue="problem",
        suggestion="",
        priority=priority,
        source_perspective=source,
    )


class TestSingleAgentPrompt:
    @pytest.mark.parametrize(
        "scope_files,diff_budget,shown,not_shown",
        [
            pytest.param(None, 10_000, {"a.py", "yarn.lock"}, set(), id="whole_pr_fits"),
            pytest.param(["a.py"], 10_000, {"a.py"}, set(), id="lens_part_shows_only_its_files"),
            pytest.param(None, 100, {"a.py"}, {"yarn.lock"}, id="too_large_keeps_the_reviewable_files"),
            pytest.param(None, 10, set(), {"a.py", "yarn.lock"}, id="still_too_large_keeps_only_the_file_list"),
        ],
    )
    def test_diff_shows_only_what_fits_and_marks_the_rest(
        self,
        pr_metadata: PRMetadata,
        scope_files: list[str] | None,
        diff_budget: int,
        shown: set[str],
        not_shown: set[str],
    ) -> None:
        # A diff past the model's context fails the session, and a lens part that shows another
        # part's files reviews them twice, so each session must see only what it owns and what fits.
        pr_files = [_file("a.py", "x = 1"), _file("yarn.lock", "y" * 500)]
        with patch(f"{_MODULE}.FLASH_PROMPT_DIFF_MAX_CHARS", diff_budget):
            prompt = SingleAgentPrompt(
                repository="o/r",
                pr_metadata=pr_metadata,
                pr_files=pr_files,
                prior_findings=[],
                scope_files=scope_files,
            ).render()

        for pr_file in pr_files:
            assert (f"=== {pr_file.filename} [modified] ===" in prompt) is (pr_file.filename in shown)
            assert (f"- {pr_file.filename} (modified, +1 -0, diff not shown)" in prompt) is (
                pr_file.filename in not_shown
            )
        assert ("Review the changes in these files: `a.py`." in prompt) is (scope_files is not None)
        assert ("git fetch origin" in prompt) is bool(not_shown)


class TestComposeFlashFindings:
    @pytest.mark.parametrize(
        "main,lens,lens_part_count,expected_ids",
        [
            pytest.param(
                [_issue("m-p3", IssuePriority.CONSIDER), _issue("m-p2", IssuePriority.SHOULD_FIX)],
                [_issue("l-p1", IssuePriority.MUST_FIX, _LENS_SOURCE)],
                1,
                ["l-p1", "m-p2", "m-p3"],
                id="p3_fills_a_free_slot_after_p2_and_a_lens_must_fix_ranks_first",
            ),
            pytest.param(
                [_issue(f"m{n}", IssuePriority.MUST_FIX) for n in range(1, 4)]
                + [_issue("m-p2", IssuePriority.SHOULD_FIX)],
                [_issue(f"l{n}", IssuePriority.MUST_FIX, _LENS_SOURCE) for n in range(1, 4)],
                1,
                ["m1", "m2", "m3", "l1", "l2", "l3"],
                id="must_fix_posts_past_the_cap_and_leaves_no_slot_for_p2",
            ),
            pytest.param(
                [_issue(f"m{n}", IssuePriority.MUST_FIX) for n in range(1, 6)],
                [_issue(f"l{n}", IssuePriority.MUST_FIX, _LENS_SOURCE) for n in range(1, 6)],
                1,
                ["m1", "m2", "m3", "m4", "m5", "l1", "l2", "l3"],
                id="must_fix_stops_at_twice_the_cap",
            ),
            pytest.param(
                [
                    _issue("m1", IssuePriority.MUST_FIX),
                    _issue("m2", IssuePriority.SHOULD_FIX),
                    _issue("m3", IssuePriority.SHOULD_FIX),
                ],
                [
                    _issue("l1", IssuePriority.MUST_FIX, _LENS_SOURCE),
                    _issue("l2", IssuePriority.MUST_FIX, _LENS_SOURCE),
                    _issue("l3", IssuePriority.SHOULD_FIX, _LENS_SOURCE),
                ],
                1,
                ["m1", "l1", "l2", "m2"],
                id="one_part_keeps_four_and_main_first_on_ties",
            ),
            pytest.param(
                [_issue(f"m{n}", IssuePriority.SHOULD_FIX) for n in range(1, 7)],
                [_issue(f"l{n}", IssuePriority.SHOULD_FIX, _LENS_SOURCE) for n in range(1, 7)],
                4,
                ["m1", "m2", "m3", "m4", "m5", "m6", "l1", "l2", "l3", "l4"],
                id="four_parts_keep_ten",
            ),
        ],
    )
    def test_keeps_the_highest_priority_findings_main_first_on_ties(
        self, main: list[Issue], lens: list[Issue], lens_part_count: int, expected_ids: list[str]
    ) -> None:
        # A turn posts only what this keeps. A must-fix finding cut by the cap never reaches the PR, a
        # P3 that outranks a P1 or a comment past the cap is noise, a session that marks everything
        # must-fix floods the PR without the ceiling, and a large PR held to the one-part cap loses
        # real findings.
        kept = compose_flash_findings(main, lens, lens_part_count=lens_part_count)
        assert [issue.id for issue in kept] == expected_ids


class TestDedupeFlashFindings:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "llm_duplicates,expected_ids",
        [
            pytest.param(["2000-1-1"], ["2000-1-1", "2002-1-1"], id="llm_names_the_main_finding"),
            pytest.param(["2002-1-1"], ["2000-1-1"], id="llm_names_the_lens_finding"),
        ],
    )
    async def test_a_lens_finding_can_lose_to_a_main_finding_but_never_the_reverse(
        self, pr_metadata: PRMetadata, llm_duplicates: list[str], expected_ids: list[str]
    ) -> None:
        # Dedup keeps whichever restatement reads more complete, so one call over both lists could
        # drop the main finding, and a lens call that ignores the main findings posts the same
        # problem twice.
        main = _issue("2000-1-1", IssuePriority.MUST_FIX)
        lens = _issue("2002-1-1", IssuePriority.MUST_FIX, _LENS_SOURCE)
        mock_llm = AsyncMock(
            return_value=IssueDeduplication(duplicates=[DuplicateIssue(id=issue_id) for issue_id in llm_duplicates])
        )
        with patch(f"{_DEDUP_MODULE}.run_oneshot_openai_review", mock_llm):
            kept = await dedupe_flash_findings(
                team_id=1,
                user_id=1,
                issues=[main, lens],
                pr_metadata=pr_metadata,
                pr_comments=[],
                prior_findings=[],
                branch="feat",
                repository="o/r",
                lens_part_count=1,
            )

        assert [issue.id for issue in kept] == expected_ids
        assert mock_llm.call_count == 1
