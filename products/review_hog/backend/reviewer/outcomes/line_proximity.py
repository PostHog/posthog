"""The cheap first gate: did any post-review commit touch a finding's lines?

Given the ``base...head`` compare between the head a finding was published at and the PR's branch tip
at merge, decide whether the finding's file changed near its lines. A hit only makes the finding a
*candidate* for "addressed" — the LLM judge is the real arbiter; this just keeps judge calls off the
findings nothing touched.

Everything here works in BASE-side line numbers, because that is the only frame the two inputs share:
a finding's `lines` come from the review diff's new side (`diff_position.build_diff_line_map`), which
is the file at the head it was published at — this compare's base. Reading the compare's new side
instead would compare the two across a shift of however many lines the post-review commits added
above the finding. A miss here is unguarded, unlike a false hit: the judge only runs on hits, so
`classify_report` sends a miss straight to `ignored` / `no_signal`.
"""

import re
import sys
from dataclasses import dataclass

from products.review_hog.backend.reviewer.models.issues_review import LineRange

# `@@ -old_start[,old_count] +new_start[,new_count] @@`. Both starts are captured: the old side is
# what proximity compares against (see `_changed_base_lines`), the new side only advances alongside it.
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")

# Marks rows cut from inside a hunk, so the judge sees the evidence is partial rather than assuming
# the shown rows are the whole change.
_ROWS_ELIDED = "[... {count} row(s) of this hunk omitted ...]"


@dataclass(frozen=True)
class ComparedFile:
    """One file in a ``base...head`` compare: its name, the name it was renamed from, and the line
    numbers its hunks changed, expressed in the BASE file (deletions, plus each addition's insertion
    point) — the frame a finding's `lines` are in."""

    filename: str
    previous_filename: str | None
    changed_base_lines: frozenset[int]


def _changed_base_lines(patch: str) -> set[int]:
    """Line numbers this ``patch`` changed, in the file as it stood at the compare's BASE.

    Base-side on purpose: a finding's `lines` are anchored to the head it was published at, which is
    exactly this compare's base, so the two are only comparable in that frame. New-side numbers drift
    by however many lines the post-review commits added or removed above the finding, which silently
    moves a fix landing on the flagged line out of the proximity window.

    A deleted line has a base-side number of its own. An added line has none, so it anchors at the
    base position it was inserted at — the same "close enough for proximity" treatment deletions get
    on the new side. Only deletions and context consume a base line; additions do not.
    """
    changed: set[int] = set()
    base_line: int | None = None
    for line in patch.splitlines():
        header = _HUNK_HEADER.match(line)
        if header is not None:
            base_line = int(header.group(1))
            continue
        if base_line is None:
            continue
        # Single-char markers on purpose: GitHub's compare `patch` is hunk-only (no `--- a/` /
        # `+++ b/` header pair), so guarding against `+++`/`---` here would instead swallow real
        # content lines that start with a doubled marker — a deleted `---` frontmatter delimiter,
        # an added unindented `++x` — and shift every later base-side number.
        if line.startswith("+"):
            changed.add(base_line)
        elif line.startswith("-"):
            changed.add(base_line)
            base_line += 1
        elif line.startswith("\\"):
            # "\ No newline at end of file" — not a real line on either side.
            continue
        else:
            base_line += 1
    return changed


def _split_hunks(patch: str) -> list[str]:
    """``patch`` split into its ``@@`` hunks, in file order. Anything before the first header is
    dropped: GitHub's compare `patch` is hunk-only, so there is nothing there to keep."""
    hunks: list[str] = []
    current: list[str] = []
    for line in patch.splitlines():
        if _HUNK_HEADER.match(line) is not None:
            if current:
                hunks.append("\n".join(current))
            current = [line]
            continue
        if current:
            current.append(line)
    if current:
        hunks.append("\n".join(current))
    return hunks


def _line_distance(line: int, lines: list[LineRange]) -> int:
    """How far a single base-side ``line`` sits from the nearest of ``lines``; 0 when inside one."""
    return min(
        0
        if lr.start <= line <= (lr.end if lr.end is not None else lr.start)
        else lr.start - line
        if line < lr.start
        else line - (lr.end if lr.end is not None else lr.start)
        for lr in lines
    )


def _distance_to_lines(hunk: str, lines: list[LineRange]) -> int:
    """How far ``hunk``'s nearest changed line is from ``lines``; ``maxsize`` when it changes none."""
    changed = _changed_base_lines(hunk)
    if not changed or not lines:
        return sys.maxsize
    return min(_line_distance(changed_line, lines) for changed_line in changed)


def _base_line_per_row(header: str, body: list[str]) -> list[int]:
    """The base-side line each body row of a hunk sits at, by the same walk as `_changed_base_lines`."""
    match = _HUNK_HEADER.match(header)
    base_line = int(match.group(1)) if match is not None else 0
    positions: list[int] = []
    for row in body:
        positions.append(base_line)
        if not row.startswith(("+", "\\")):
            base_line += 1
    return positions


def _trim_hunk_around(hunk: str, lines: list[LineRange], max_chars: int) -> str:
    """``hunk`` reduced to a run of rows around the change nearest ``lines``, within ``max_chars``.

    The nearest hunk can exceed the budget on its own — a large rewrite landing right where a finding
    sits. Keeping it whole would make the ceiling meaningless (any single oversized hunk would set the
    prompt size, and whoever wrote the diff decides that), and dropping it would leave the judge
    ruling on no evidence at all. Slicing around the finding bounds the prompt and keeps the rows that
    decide the answer; cutting the string from the front would not, since the relevant rows can sit
    anywhere in the hunk.
    """
    rows = hunk.splitlines()
    header, body = (rows[0], rows[1:]) if rows else (hunk, [])
    if not body:
        return hunk[:max_chars]
    positions = _base_line_per_row(header, body)
    center = min(range(len(body)), key=lambda i: (_line_distance(positions[i], lines), i)) if lines else 0
    # Reserve room for the header and an elision marker on each side before spending on rows.
    budget = max_chars - len(header) - 2 * len(_ROWS_ELIDED.format(count=len(body))) - 4
    if budget <= 0:
        return header[:max_chars]
    low = high = center
    used = len(body[center]) + 1
    grew = True
    while grew:
        grew = False
        if low > 0 and used + len(body[low - 1]) + 1 <= budget:
            low -= 1
            used += len(body[low]) + 1
            grew = True
        if high < len(body) - 1 and used + len(body[high + 1]) + 1 <= budget:
            high += 1
            used += len(body[high]) + 1
            grew = True
    kept = [header]
    if low > 0:
        kept.append(_ROWS_ELIDED.format(count=low))
    kept.extend(body[low : high + 1])
    if high < len(body) - 1:
        kept.append(_ROWS_ELIDED.format(count=len(body) - 1 - high))
    return "\n".join(kept)[:max_chars]


def trim_patch_near(patch: str, lines: list[LineRange], *, max_chars: int) -> tuple[str, int]:
    """``patch`` reduced to the hunks nearest ``lines`` within ``max_chars``, plus the number dropped.

    A file can pick up a large unrelated rewrite (a refactor, a regenerated file) between review and
    merge, and the whole thing would otherwise ride into the judge's prompt. Cutting the string
    blindly could drop the very hunk that made the finding a candidate and leave the judge ruling on
    unrelated changes, so hunks are chosen nearest-first and re-emitted in file order. The nearest
    hunk is always represented — sliced around the finding when it alone overruns the budget, never
    dropped — so the judge always has the evidence that made this finding a candidate, and the
    ceiling still holds however large a single hunk is.
    """
    if len(patch) <= max_chars:
        return patch, 0
    hunks = _split_hunks(patch)
    if not hunks:
        return patch[:max_chars], 0
    ranked = sorted(range(len(hunks)), key=lambda i: (_distance_to_lines(hunks[i], lines), i))
    kept: dict[int, str] = {}
    used = 0
    for i in ranked:
        text = hunks[i]
        cost = len(text) + 2
        if not kept and cost > max_chars:
            text = _trim_hunk_around(text, lines, max_chars)
            cost = len(text) + 2
        if kept and used + cost > max_chars:
            break
        kept[i] = text
        used += cost
    return "\n\n".join(kept[i] for i in sorted(kept)), len(hunks) - len(kept)


def parse_compare_files(files: list[dict]) -> list[ComparedFile]:
    """Map a GitHub compare's ``files`` entries to `ComparedFile`, parsing each file's ``patch``.

    A file with no ``patch`` (binary, or a rename with no content change) contributes no changed
    lines but still carries its rename mapping, so a pure rename never reads as "touched near".
    """
    compared: list[ComparedFile] = []
    for file in files:
        patch = file.get("patch") or ""
        compared.append(
            ComparedFile(
                filename=file["filename"],
                previous_filename=file.get("previous_filename"),
                changed_base_lines=frozenset(_changed_base_lines(patch)),
            )
        )
    return compared


def touched_near(*, file: str, lines: list[LineRange], compared: list[ComparedFile], window: int) -> bool:
    """Whether the compare changed ``file`` within ``window`` lines of any of ``lines``.

    Matches the compare file by its current name or its ``previous_filename`` (so a finding on a since-
    renamed file still resolves). A finding with no line ranges can't be "near" anything, so it never
    hits this gate — it falls through to the comment-thread signal or `ignored`.
    """
    if not lines:
        return False
    changed: set[int] = set()
    for cf in compared:
        if cf.filename == file or cf.previous_filename == file:
            changed |= cf.changed_base_lines
    if not changed:
        return False
    return any(
        (lr.start - window) <= changed_line <= ((lr.end if lr.end is not None else lr.start) + window)
        for lr in lines
        for changed_line in changed
    )
