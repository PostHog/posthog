import pytest
from unittest.mock import patch

from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRFileUpdate, PRMetadata
from products.review_hog.backend.reviewer.tools.single_agent_review import SingleAgentPrompt

_MODULE = "products.review_hog.backend.reviewer.tools.single_agent_review"


def _file(filename: str, code: str) -> PRFile:
    return PRFile(
        filename=filename,
        status="modified",
        additions=1,
        deletions=0,
        changes=[PRFileUpdate(type="addition", new_start_line=1, new_end_line=1, code=code)],
    )


class TestSingleAgentPrompt:
    @pytest.mark.parametrize(
        "scope_files,diff_budget,shown,not_shown",
        [
            pytest.param(None, 10_000, {"a.py", "data.json"}, set(), id="whole_pr_fits"),
            pytest.param(["a.py"], 10_000, {"a.py"}, set(), id="lens_part_shows_only_its_files"),
            pytest.param(None, 100, {"a.py"}, {"data.json"}, id="too_large_keeps_the_reviewable_files"),
            pytest.param(None, 10, set(), {"a.py", "data.json"}, id="still_too_large_keeps_only_the_file_list"),
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
        pr_files = [_file("a.py", "x = 1"), _file("data.json", "y" * 500)]
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
