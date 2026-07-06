"""Live implementation cases.

Live implementation drives the coding agent against a repository the team's GitHub integration
can clone (public repos work) and grades the diff it produces. We use a small SDK repo and a
focused, reliably-doable additive change so the run is fast and the expected diff is unambiguous —
the point is to prove the agent edits the real repo and returns a correct diff end to end. Heavier,
representative fixes are graded deterministically in replay (see ``implementation.py``).
"""

from __future__ import annotations

from products.signals.eval.agentic.datasets import ImplementationCase, ImplementationExpectation
from products.signals.eval.agentic.scorers_implementation import default_implementation_scorers
from products.signals.eval.agentic.scorers_judge import ImplementationFixJudge

CASES: list[ImplementationCase] = [
    ImplementationCase(
        case_id="impl_live_pysdk_marker",
        step="implementation",
        repo="posthog-python",
        notes="Small additive change on the Python SDK — reliably-doable, unambiguous diff.",
        issue_prompt=(
            "In the file `posthog/__init__.py`, add a new top-level function "
            "`def eval_marker() -> str:` that returns the string 'signals-agentic-eval'. "
            "Place it near the other top-level functions and keep the change minimal."
        ),
        expected=ImplementationExpectation(
            expected_file_substrings=("__init__.py",),
            forbidden_file_substrings=("setup.py", "pyproject", "requirements"),
            expected_diff_keywords=("eval_marker", "signals-agentic-eval"),
            min_files_changed=1,
            max_files_changed=2,
        ),
        scorers=(*default_implementation_scorers(), ImplementationFixJudge()),
    ),
]
