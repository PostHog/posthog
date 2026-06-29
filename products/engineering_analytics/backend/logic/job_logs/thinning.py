"""Thin a GitHub Actions job log down to its failure-relevant lines.

A failed job's full log is mostly noise — dependency downloads, hundreds of passing migrations,
setup chatter — wrapped around a small failure region. We keep that region (every line matching a
high-precision failure marker, plus surrounding context) and always the tail, where test runners
print their final summary (pytest's ``FAILED`` list, cargo's ``test result: FAILED``, jest /
playwright's ``N failed``). Everything else collapses to a ``... N lines omitted ...`` marker. This
turns multi-MB logs into a few hundred lines without losing the cause.

This is a pure transform over log text, independent of how the log is fetched or emitted, so the
same path can later thin *non-failure* logs (once all-jobs ingestion lands) by passing a different
``ThinningConfig`` — a narrower marker set, a shorter tail, whatever that case wants.

A richer, structured alternative exists for instrumented workflows — GitHub's check-run *annotations*
API and JUnit XML test reports — but both depend on per-workflow problem matchers / artifact uploads
we don't control. Raw-log thinning is the universal fallback; the annotations API is a clean future
upgrade for the jobs that have them.

Markers are matched as exact, case-sensitive substrings and are deliberately high-precision: bare
``error`` / ``failed`` are NOT markers, because real logs are full of them (``errortracking``
migrations, ``0 failed`` summaries, non-fatal setup warnings) and would defeat the thinning.
"""

import dataclasses

# Failure anchors. The first two are GitHub's own workflow-command annotations (the documented
# ::error / ::warning mechanism, rendered into the raw log): ##[error] is present on every failed
# step, and ##[warning] surfaces non-fatal issues worth seeing in engineering analytics (e.g. a
# GeoIP setup warning). The rest are framework fallbacks for steps that emit no annotation.
# Substring match, case-sensitive on purpose.
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
    # Keep a small tail as a non-empty fallback for the rare marker-less log. It is NOT where the
    # summary lives: Actions appends "Post job cleanup" steps after the test step, so the failing
    # step's summary sits just before its ##[error], which a marker window already captures.
    tail_lines: int = 50
    max_lines: int = 400  # hard cap on kept lines; logs at or under this pass through untouched


FAILURE_THINNING = ThinningConfig()


def _matches_marker(line: str, markers: tuple[str, ...]) -> bool:
    return any(marker in line for marker in markers)


def thin_log(text: str, config: ThinningConfig = FAILURE_THINNING) -> str:
    """Return the failure-relevant slice of ``text`` with omitted gaps marked. Pure; no I/O.

    Logs at or under ``config.max_lines`` are returned unchanged — thinning only kicks in once a log
    is large enough to be worth trimming, so small failures keep full fidelity.
    """
    lines = text.splitlines()
    total = len(lines)
    if total <= config.max_lines:
        return text

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

    out: list[str] = []
    if selected and selected[0] > 0:
        out.append(f"... {selected[0]} lines omitted ...")
    previous: int | None = None
    for index in selected:
        if previous is not None and index > previous + 1:
            out.append(f"... {index - previous - 1} lines omitted ...")
        out.append(lines[index])
        previous = index
    return "\n".join(out)
