"""Thin a CI job log down to its failure-relevant lines.

The kept lines are those near a failure marker, plus a short tail. Every other stretch collapses
to a ``... N lines omitted ...`` marker.
"""

import dataclasses

# Exact, case-sensitive substrings. Bare ``error`` and ``failed`` are not markers, because logs
# are full of them (``errortracking`` migrations, ``0 failed`` summaries) and nothing would be thinned.
DEFAULT_FAILURE_MARKERS: tuple[str, ...] = (
    "##[error]",  # GitHub emits this on every failed step
    "##[warning]",
    "Traceback (most recent call last)",  # Python
    "AssertionError",  # Python / JS
    "FAILED ",  # pytest per-test failure line
    "RERUN ",  # pytest failed-attempt diagnostics, including jobs that recovered
    "test result: FAILED",  # cargo test summary
    "panic:",  # Go / Rust panic
    "--- FAIL",  # go test
)


@dataclasses.dataclass(frozen=True)
class ThinningConfig:
    markers: tuple[str, ...] = DEFAULT_FAILURE_MARKERS
    leading_context: int = 15  # the cause usually precedes the marker
    trailing_context: int = 10  # a traceback's frames follow the marker
    # The fallback for a log with no marker.
    tail_lines: int = 50
    max_lines: int = 400  # a log at or under this passes through untouched


FAILURE_THINNING = ThinningConfig()


@dataclasses.dataclass(frozen=True)
class ThinnedLine:
    """``original_line_number`` is the line's 1-based position in the full log, or None for an
    omission marker. It is the only anchor back to the full log, which is not stored."""

    text: str
    original_line_number: int | None


def _matches_marker(line: str, markers: tuple[str, ...]) -> bool:
    return any(marker in line for marker in markers)


def thin_log_lines(text: str, config: ThinningConfig = FAILURE_THINNING) -> list[ThinnedLine]:
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
        # Keep the end, because the final summary matters more than the first of many failures.
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
    return "\n".join(line.text for line in thin_log_lines(text, config))
