"""Thin a GitHub Actions job log down to its failure-relevant lines.

A failed job's log is mostly noise (dependency downloads, hundreds of passing migrations) around a
small failure region. We keep that region — lines matching a high-precision failure marker plus
context — and a short tail fallback; everything else collapses to a ``... N lines omitted ...``
marker, turning multi-MB logs into a few hundred lines without losing the cause.

Pure transform, decoupled from fetch/emit: all-jobs ingestion can later thin *non-failure* logs by
passing a different ``ThinningConfig``. (A structured alternative — the check-run annotations API or
JUnit XML — is a cleaner future upgrade but depends on per-workflow instrumentation we don't control.)

Markers are exact, case-sensitive substrings, deliberately high-precision: bare ``error`` / ``failed``
are NOT markers — real logs are full of them (``errortracking`` migrations, ``0 failed`` summaries)
and they would defeat the thinning.
"""

import dataclasses

# Failure anchors. First two are GitHub's own ::error / ::warning annotations; the rest are framework
# fallbacks for steps that emit no annotation. Substring match, case-sensitive.
DEFAULT_FAILURE_MARKERS: tuple[str, ...] = (
    "##[error]",  # GitHub step failure — emitted on every failed step
    "##[warning]",  # GitHub warning annotation — non-fatal but worth surfacing
    "Traceback (most recent call last)",  # Python
    "AssertionError",  # Python / JS
    "FAILED ",  # pytest per-test failure line
    "test result: FAILED",  # cargo test summary
    "panic:",  # Go / Rust panic
    "--- FAIL",  # go test
)


@dataclasses.dataclass(frozen=True)
class ThinningConfig:
    """Knobs for :func:`thin_log`. Defaults target failure logs; other log types pass their own."""

    markers: tuple[str, ...] = DEFAULT_FAILURE_MARKERS
    leading_context: int = 15  # lines kept before a marker (the cause usually precedes the marker)
    trailing_context: int = 10  # lines kept after a marker (a traceback's frames follow it)
    # Fallback for the rare marker-less log; the summary itself is already caught by the ##[error]
    # window (Actions appends cleanup steps after the test step, so the literal tail is mostly noise).
    tail_lines: int = 50
    max_lines: int = 400  # hard cap on kept lines; logs at or under this pass through untouched


FAILURE_THINNING = ThinningConfig()


@dataclasses.dataclass(frozen=True)
class ThinnedLine:
    """One line of a thinned log. ``original_line_number`` is the line's 1-based position in the full
    pre-thinning log; None for a synthetic ``... N lines omitted ...`` marker. The number is the only
    durable anchor back to the original — the full log isn't stored and GitHub expires it.
    """

    text: str
    original_line_number: int | None


def _matches_marker(line: str, markers: tuple[str, ...]) -> bool:
    return any(marker in line for marker in markers)


def thin_log_lines(text: str, config: ThinningConfig = FAILURE_THINNING) -> list[ThinnedLine]:
    """Return the failure-relevant slice of ``text`` as lines, each tagged with its 1-based position in
    the full log (None for an omission marker). Pure; no I/O.

    Logs at or under ``config.max_lines`` pass through untouched (every line kept, numbered) so small
    failures keep full fidelity; larger logs collapse the noise to ``... N lines omitted ...`` markers.
    """
    lines = text.splitlines()
    total = len(lines)
    if total <= config.max_lines:
        return [ThinnedLine(line, index + 1) for index, line in enumerate(lines)]

    keep: set[int] = set()
    for index, line in enumerate(lines):
        if _matches_marker(line, config.markers):
            start = max(0, index - config.leading_context)
            stop = min(total, index + config.trailing_context + 1)
            keep.update(range(start, stop))
    keep.update(range(max(0, total - config.tail_lines), total))

    selected = sorted(keep)
    if len(selected) > config.max_lines:
        # Bias to the end: the final summary matters more than the first of many failures.
        selected = selected[-config.max_lines :]

    out: list[ThinnedLine] = []
    if selected and selected[0] > 0:
        out.append(ThinnedLine(f"... {selected[0]} lines omitted ...", None))
    previous: int | None = None
    for index in selected:
        if previous is not None and index > previous + 1:
            out.append(ThinnedLine(f"... {index - previous - 1} lines omitted ...", None))
        out.append(ThinnedLine(lines[index], index + 1))
        previous = index
    return out


def thin_log(text: str, config: ThinningConfig = FAILURE_THINNING) -> str:
    """Text rendering of :func:`thin_log_lines` — kept lines joined, omission markers inline."""
    return "\n".join(line.text for line in thin_log_lines(text, config))
