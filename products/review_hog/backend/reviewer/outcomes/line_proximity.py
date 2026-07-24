"""The cheap first gate: did any post-review commit touch a finding's lines?

Given the ``base...head`` compare between the head a finding was published at and the PR's branch tip
at merge, decide whether the finding's file changed near its lines. A hit only makes the finding a
*candidate* for "addressed" — the LLM judge is the real arbiter; this just keeps judge calls off the
findings nothing touched.
"""

import re
from dataclasses import dataclass

from products.review_hog.backend.reviewer.models.issues_review import LineRange

# `@@ -old_start[,old_count] +new_start[,new_count] @@` — we only need the new-side start.
_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(frozen=True)
class ComparedFile:
    """One file in a ``base...head`` compare: its name, the name it was renamed from, and the
    new-side line numbers its hunks changed (added lines, plus the anchor of each deletion)."""

    filename: str
    previous_filename: str | None
    changed_new_lines: frozenset[int]


def _changed_new_lines(patch: str) -> set[int]:
    """New-file line numbers a unified-diff ``patch`` changed.

    Added lines map to their new-side number; a deletion has no new-side line, so it anchors at the
    position it was removed from (the current new-side counter) — enough for proximity. Context lines
    only advance the counter.
    """
    changed: set[int] = set()
    new_line: int | None = None
    for line in patch.splitlines():
        header = _HUNK_HEADER.match(line)
        if header is not None:
            new_line = int(header.group(1))
            continue
        if new_line is None:
            continue
        # Single-char markers on purpose: GitHub's compare `patch` is hunk-only (no `--- a/` /
        # `+++ b/` header pair), so guarding against `+++`/`---` here would instead swallow real
        # content lines that start with a doubled marker — a deleted `---` frontmatter delimiter,
        # an added unindented `++x` — and shift every later new-side number.
        if line.startswith("+"):
            changed.add(new_line)
            new_line += 1
        elif line.startswith("-"):
            changed.add(new_line)
        elif line.startswith("\\"):
            # "\ No newline at end of file" — not a real line on either side.
            continue
        else:
            new_line += 1
    return changed


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
                changed_new_lines=frozenset(_changed_new_lines(patch)),
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
            changed |= cf.changed_new_lines
    if not changed:
        return False
    return any(
        (lr.start - window) <= changed_line <= ((lr.end if lr.end is not None else lr.start) + window)
        for lr in lines
        for changed_line in changed
    )
