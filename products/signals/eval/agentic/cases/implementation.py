"""Implementation eval dataset.

Each case points the coding agent at an OSS repo with a described issue. The gradeable
artifact is the resulting unified diff: deterministic scorers check it lands in the right
files, avoids the wrong ones, and contains the expected edits; the LLM judge assesses fix
correctness. In replay mode the diff is loaded from a recorded ``.patch`` file; live mode
runs the coding agent against a checked-out repo (see README).
"""

from __future__ import annotations

from products.signals.eval.agentic.datasets import ImplementationCase, ImplementationExpectation
from products.signals.eval.agentic.scorers_implementation import default_implementation_scorers
from products.signals.eval.agentic.scorers_judge import ImplementationFixJudge

CASES: list[ImplementationCase] = [
    ImplementationCase(
        case_id="impl_cal_tz",
        step="implementation",
        repo="cal",
        patch="impl_cal_tz.patch",
        notes="Fix DST-boundary slot dropping in cal.com schedule bucketing.",
        issue_prompt=(
            "Booking availability drops slots that span a daylight-saving-time boundary because slot "
            "bucketing uses server-local time instead of the organizer's timezone. Fix the bucketing in "
            "the schedule logic and add a regression test."
        ),
        expected=ImplementationExpectation(
            expected_file_substrings=("getschedule",),
            forbidden_file_substrings=("pnpm-lock", "package-lock", "yarn.lock"),
            expected_diff_keywords=("timezone", "dst"),
            min_files_changed=1,
            max_files_changed=4,
        ),
        scorers=(*default_implementation_scorers(), ImplementationFixJudge()),
    ),
]
