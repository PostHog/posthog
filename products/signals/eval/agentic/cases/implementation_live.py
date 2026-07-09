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


def _impl(
    case_id: str,
    repo: str,
    issue_prompt: str,
    expected_files: tuple[str, ...],
    expected_keywords: tuple[str, ...],
    *,
    forbidden: tuple[str, ...] = (),
    min_files: int = 1,
    max_files: int | None = 3,
) -> ImplementationCase:
    return ImplementationCase(
        case_id=case_id,
        step="implementation",
        repo=repo,
        issue_prompt=issue_prompt,
        expected=ImplementationExpectation(
            expected_file_substrings=expected_files,
            forbidden_file_substrings=forbidden,
            expected_diff_keywords=expected_keywords,
            min_files_changed=min_files,
            max_files_changed=max_files,
        ),
        scorers=(*default_implementation_scorers(), ImplementationFixJudge()),
    )


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
    # ── posthog-python: additive utilities (easy→medium) ──────────────────────────
    _impl(
        "impl_pysdk_clamp",
        "posthog-python",
        "In `posthog/utils.py`, add a new top-level function `def clamp(value, minimum, maximum):` "
        "that returns `value` bounded to the inclusive range [minimum, maximum] (i.e. never below "
        "minimum, never above maximum). Keep it minimal and place it among the other helpers.",
        ("utils.py",),
        ("clamp", "minimum", "maximum"),
        forbidden=("setup.py", "pyproject", "test"),
    ),
    _impl(
        "impl_pysdk_redact_email",
        "posthog-python",
        "In `posthog/utils.py`, add `def redact_email(text: str) -> str:` that returns `text` with any "
        "email addresses replaced by the literal string `[redacted]`. Use a regular expression.",
        ("utils.py",),
        ("redact_email", "[redacted]", "re."),
        forbidden=("setup.py", "test"),
    ),
    _impl(
        "impl_pysdk_chunk_list",
        "posthog-python",
        "In `posthog/utils.py`, add `def chunk_list(items, size):` that splits the list `items` into "
        "consecutive sublists of at most `size` elements and returns the list of sublists.",
        ("utils.py",),
        ("chunk_list", "size"),
        forbidden=("test",),
    ),
    # ── posthog-python: bugfix / robustness (medium) ──────────────────────────────
    _impl(
        "impl_pysdk_trailing_slash_none",
        "posthog-python",
        "`posthog/utils.py` has `remove_trailing_slash(host)`. It currently raises AttributeError when "
        "`host` is None. Make it return the input unchanged when `host` is None, without changing its "
        "behavior for normal strings.",
        ("utils.py",),
        ("remove_trailing_slash", "none"),
        forbidden=("test",),
        max_files=2,
    ),
    _impl(
        "impl_pysdk_regex_nonstring",
        "posthog-python",
        "`posthog/utils.py` has `is_valid_regex(value) -> bool`. It currently raises TypeError when "
        "`value` is not a string (e.g. an int). Make it return False for any non-string input instead "
        "of raising, keeping existing behavior for strings.",
        ("utils.py",),
        ("is_valid_regex",),
        forbidden=("test",),
        max_files=2,
    ),
    # ── posthog-python: new Client methods (medium→hard) ──────────────────────────
    _impl(
        "impl_pysdk_flush_and_shutdown",
        "posthog-python",
        "Add a method `def flush_and_shutdown(self):` to the `Client` class in `posthog/client.py` "
        "that flushes any queued events and then shuts the client down, by calling the existing "
        "`self.flush()` and `self.shutdown()` methods in that order.",
        ("client.py",),
        ("flush_and_shutdown", "self.flush", "self.shutdown"),
        forbidden=("test",),
    ),
    _impl(
        "impl_pysdk_flag_or_default",
        "posthog-python",
        "Add a method `def feature_enabled_or_default(self, key, distinct_id, default=False):` to the "
        "`Client` class in `posthog/client.py`. It should return the result of the existing "
        "`self.feature_enabled(key, distinct_id)`, but if that raises any exception it must catch it and "
        "return `default` instead.",
        ("client.py",),
        ("feature_enabled_or_default", "default", "except"),
        forbidden=("test",),
    ),
    # ── posthog-python: new module (medium) ───────────────────────────────────────
    _impl(
        "impl_pysdk_redaction_module",
        "posthog-python",
        "Create a new file `posthog/redaction.py` containing `def redact_credit_cards(text: str) -> str:` "
        "that replaces any sequence of 13 to 16 digits (a credit-card-like number) in `text` with the "
        "literal string `[redacted-card]`. Use a regular expression.",
        ("redaction.py",),
        ("redact_credit_cards", "[redacted-card]"),
        forbidden=("client.py", "setup.py"),
    ),
    # ── posthog-js: additive TypeScript utilities (easy→medium) ───────────────────
    _impl(
        "impl_jssdk_truncate",
        "posthog-js",
        "In `src/utils/string-utils.ts`, add and export `function truncate(value: string, maxLength: "
        "number): string` that returns `value` unchanged if its length is <= maxLength, otherwise the "
        "first maxLength characters followed by an ellipsis `...`.",
        ("string-utils.ts",),
        ("export function truncate", "maxLength", "..."),
        forbidden=("test",),
    ),
    _impl(
        "impl_jssdk_is_valid_email",
        "posthog-js",
        "In `src/utils/string-utils.ts`, add and export `function isValidEmail(value: string): boolean` "
        "that returns true only when `value` looks like a valid email address. Use a regular expression.",
        ("string-utils.ts",),
        ("export function isValidEmail", "boolean"),
        forbidden=("test",),
    ),
    _impl(
        "impl_jssdk_capitalize",
        "posthog-js",
        "In `src/utils/string-utils.ts`, add and export `function capitalize(value: string): string` that "
        "upper-cases the first character of `value` and leaves the rest unchanged (empty string returns "
        "empty string).",
        ("string-utils.ts",),
        ("export function capitalize",),
        forbidden=("test",),
    ),
]
