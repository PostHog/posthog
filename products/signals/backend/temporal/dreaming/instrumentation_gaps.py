"""Heuristic instrumentation-gap detection over merged-PR diffs.

The Dreaming Agent inspects PRs merged since a team's previous dreaming run and looks
for *missing* PostHog instrumentation that should have accompanied the change:

- **Product analytics** — a new user-facing flow / handler / endpoint with no
  `posthog.capture(...)` event.
- **Error tracking** — a new `try/except` (or `catch`) that swallows the error without
  reporting it (`capture_exception` / `posthog.captureException`).
- **LLM analytics / observability** — a new LLM provider call (OpenAI / Anthropic / etc.)
  not wrapped in PostHog's LLM observability (`posthog.ai`, `@observe`, `PostHogCallback`).

This module is deliberately **pure and synchronous**: it takes already-fetched diff text
and returns structured findings. The Temporal activity layer owns fetching diffs from the
GitHub API and writing the consolidated result by reference — keeping the heuristics here
makes them trivially unit-testable against sample diffs with no GitHub or LLM dependency.

The detection is intentionally conservative (precision over recall): the output feeds a
single consolidated cleanup PR, and a noisy false positive there is far more costly than a
missed gap, which the next nightly run can still catch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class InstrumentationKind(StrEnum):
    """The category of instrumentation a gap is missing."""

    PRODUCT_ANALYTICS = "product_analytics"
    ERROR_TRACKING = "error_tracking"
    LLM_ANALYTICS = "llm_analytics"


# File suffixes we attempt to reason about. Anything else (lockfiles, generated code,
# markdown, config) is skipped — we have no reliable heuristic for it and don't want to
# suggest instrumenting it.
_ANALYZABLE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx")

# Generated / vendored / test paths never get an instrumentation suggestion: they're not
# product surface, and editing them in a cleanup PR is almost always wrong.
_SKIP_PATH_MARKERS = (
    "/generated/",
    "/migrations/",
    "/node_modules/",
    "/__snapshots__/",
    ".min.js",
    ".d.ts",
    "/test/",
    "/tests/",
    "/__tests__/",
    "/test_",
    "_test.",
    ".test.",
    ".spec.",
)

# --- Product-analytics heuristics ---------------------------------------------------------

# A line that already captures a PostHog product-analytics event. Matches both the Python
# (`posthog.capture(`, `ph_client.capture(`) and JS (`posthog.capture(`) call shapes, plus
# the server-side `ph_scoped_capture` helper used in Celery tasks.
_CAPTURE_RE = re.compile(r"\b(?:capture|ph_scoped_capture)\s*\(")

# Signals that an added hunk introduces user-facing product surface worth an event. These are
# deliberately coarse: a new view/handler/route/click handler is the canonical "should this
# emit an event?" shape.
_PRODUCT_SURFACE_RES = (
    re.compile(r"\bdef\s+\w*(?:view|handler|endpoint|action|submit|create|update|delete)\w*\s*\("),
    re.compile(r"@(?:app|router|api)\.(?:get|post|put|patch|delete)\s*\("),
    re.compile(r"\bon(?:Click|Submit|Change)\s*="),
    re.compile(r"\bclassName=.*\bbutton\b", re.IGNORECASE),
)

# --- Error-tracking heuristics ------------------------------------------------------------

# An added except/catch block (the place a swallowed error hides).
_EXCEPT_RES = (
    re.compile(r"\bexcept\b[^:]*:"),
    re.compile(r"\}\s*catch\s*\("),
)

# An added line that already reports the error to PostHog error tracking.
_ERROR_REPORT_RE = re.compile(r"\b(?:capture_exception|captureException|capture_error|posthog\.capture_exception)\s*\(")

# `raise` / `throw` / `re-raise` count as "handled" — the error propagates, it isn't swallowed.
_RERAISE_RE = re.compile(r"\b(?:raise|throw)\b")

# --- LLM-analytics heuristics -------------------------------------------------------------

# An added line that makes a raw LLM provider call.
_LLM_CALL_RES = (
    re.compile(r"\bOpenAI\s*\("),
    re.compile(r"\bAnthropic\s*\("),
    re.compile(r"\bAsyncOpenAI\s*\("),
    re.compile(r"\bAsyncAnthropic\s*\("),
    re.compile(r"\.chat\.completions\.create\s*\("),
    re.compile(r"\.messages\.create\s*\("),
    re.compile(r"\bgenerateText\s*\("),
    re.compile(r"\bstreamText\s*\("),
)

# An added line that already routes the LLM call through PostHog LLM observability.
_LLM_OBSERVABILITY_RE = re.compile(
    r"(?:posthog\.ai|from\s+posthog\.ai|@observe\b|PostHogCallback|posthog/ai|withTracing)"
)


@dataclass(frozen=True)
class InstrumentationGap:
    """One missing-instrumentation finding scoped to a file within a PR."""

    kind: InstrumentationKind
    file_path: str
    line_hint: str
    rationale: str


@dataclass(frozen=True)
class PullRequestDiff:
    """A merged PR plus its unified-diff text, as fetched from the GitHub API.

    `files` maps a file path to its unified-diff hunk text. Splitting by file (rather than
    one big blob) lets the detector attribute each gap and lets the activity layer cap diff
    size per file before it ever reaches this pure logic.
    """

    number: int
    title: str
    merged_at: str
    author: str
    files: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PullRequestGaps:
    """All gaps detected for one PR (empty `gaps` means the PR was clean)."""

    pr_number: int
    pr_title: str
    gaps: tuple[InstrumentationGap, ...]


def _added_lines(diff_text: str) -> list[str]:
    """The added lines of a unified diff (leading `+`, excluding the `+++` file header)."""
    added: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    return added


def _should_skip_path(file_path: str) -> bool:
    normalized = file_path if file_path.startswith("/") else f"/{file_path}"
    if not file_path.endswith(_ANALYZABLE_SUFFIXES):
        return True
    return any(marker in normalized for marker in _SKIP_PATH_MARKERS)


def _detect_product_analytics_gap(file_path: str, added: list[str]) -> InstrumentationGap | None:
    has_surface = any(pattern.search(line) for line in added for pattern in _PRODUCT_SURFACE_RES)
    if not has_surface:
        return None
    if any(_CAPTURE_RE.search(line) for line in added):
        return None
    hint = next(
        (line.strip()[:200] for line in added if any(pattern.search(line) for pattern in _PRODUCT_SURFACE_RES)),
        "",
    )
    return InstrumentationGap(
        kind=InstrumentationKind.PRODUCT_ANALYTICS,
        file_path=file_path,
        line_hint=hint,
        rationale=(
            "New user-facing surface (view/handler/route/interaction) added without a "
            "PostHog product-analytics `capture(...)` event. Consider capturing the "
            "relevant user action so its adoption is measurable."
        ),
    )


def _detect_error_tracking_gap(file_path: str, added: list[str]) -> InstrumentationGap | None:
    has_new_handler = any(pattern.search(line) for line in added for pattern in _EXCEPT_RES)
    if not has_new_handler:
        return None
    if any(_ERROR_REPORT_RE.search(line) for line in added):
        return None
    if any(_RERAISE_RE.search(line) for line in added):
        # The error propagates (re-raised / re-thrown), so it isn't silently swallowed.
        return None
    hint = next(
        (line.strip()[:200] for line in added if any(pattern.search(line) for pattern in _EXCEPT_RES)),
        "",
    )
    return InstrumentationGap(
        kind=InstrumentationKind.ERROR_TRACKING,
        file_path=file_path,
        line_hint=hint,
        rationale=(
            "New error handler that neither re-raises nor reports the exception to PostHog "
            "error tracking. Consider `capture_exception(...)` so the swallowed failure is "
            "still observable."
        ),
    )


def _detect_llm_analytics_gap(file_path: str, added: list[str]) -> InstrumentationGap | None:
    if not any(pattern.search(line) for line in added for pattern in _LLM_CALL_RES):
        return None
    if any(_LLM_OBSERVABILITY_RE.search(line) for line in added):
        return None
    hint = next(
        (line.strip()[:200] for line in added if any(pattern.search(line) for pattern in _LLM_CALL_RES)),
        "",
    )
    return InstrumentationGap(
        kind=InstrumentationKind.LLM_ANALYTICS,
        file_path=file_path,
        line_hint=hint,
        rationale=(
            "New LLM provider call added without routing through PostHog LLM observability "
            "(`posthog.ai` / `@observe` / `PostHogCallback`). Consider wrapping it so traces, "
            "tokens, and cost are captured."
        ),
    )


_DETECTORS = (
    _detect_product_analytics_gap,
    _detect_error_tracking_gap,
    _detect_llm_analytics_gap,
)


def detect_gaps_in_file(file_path: str, diff_text: str) -> list[InstrumentationGap]:
    """Run every detector against one file's diff. Returns at most one gap per kind."""
    if _should_skip_path(file_path):
        return []
    added = _added_lines(diff_text)
    if not added:
        return []
    gaps: list[InstrumentationGap] = []
    for detector in _DETECTORS:
        gap = detector(file_path, added)
        if gap is not None:
            gaps.append(gap)
    return gaps


def detect_gaps_in_pr(pr: PullRequestDiff) -> PullRequestGaps:
    """Detect all instrumentation gaps across every analyzable file in a merged PR."""
    gaps: list[InstrumentationGap] = []
    for file_path, diff_text in sorted(pr.files.items()):
        gaps.extend(detect_gaps_in_file(file_path, diff_text))
    return PullRequestGaps(pr_number=pr.number, pr_title=pr.title, gaps=tuple(gaps))


def detect_gaps_across_prs(prs: list[PullRequestDiff]) -> list[PullRequestGaps]:
    """Detect gaps across a batch of merged PRs, dropping PRs with no findings.

    The returned list preserves the input order so the caller controls how the cleanup PR
    description is ordered (it sorts newest-merged first upstream).
    """
    results: list[PullRequestGaps] = []
    for pr in prs:
        pr_gaps = detect_gaps_in_pr(pr)
        if pr_gaps.gaps:
            results.append(pr_gaps)
    return results
