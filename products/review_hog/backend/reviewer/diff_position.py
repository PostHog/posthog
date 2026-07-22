"""Map a finding's line range onto the PR diff's added lines for inline-comment positioning.

GitHub only accepts an inline review comment on a line present in the diff (an added line on the
RIGHT side). Both the publisher (which builds inline comments) and the body renderer (which surfaces
findings that can't be positioned in an "Other findings" section) share this check, so it lives in
one place — keyed by file + `LineRange`s, which both the live `Issue` and the durable
`ReviewIssueFinding` satisfy.
"""

from products.review_hog.backend.reviewer.models.github_meta import PRFile
from products.review_hog.backend.reviewer.models.issues_review import LineRange


def build_diff_line_map(pr_files: list[PRFile]) -> dict[str, set[int]]:
    """Map each filename to the set of new-file line numbers present in the diff."""
    diff_lines: dict[str, set[int]] = {}
    for pr_file in pr_files:
        valid_lines: set[int] = set()
        for change in pr_file.changes:
            if change.type == "deletion":
                continue
            start = change.new_start_line
            if start is not None:
                end = change.new_end_line or start
                valid_lines.update(range(start, end + 1))
        diff_lines[pr_file.filename] = valid_lines
    return diff_lines


def find_diff_position(
    file: str,
    line_ranges: list[LineRange],
    diff_lines: dict[str, set[int]],
) -> tuple[int, int | None] | None:
    """First valid inline-comment position for a finding, or None if no range lands on the diff.

    Tries each range in order; returns (start_line, end_line) for the first whose start line is in
    the diff (end_line is None for a single-line comment). None means the finding can't be anchored
    to an inline comment — the caller surfaces it in the body instead of dropping it.
    """
    valid_lines = diff_lines.get(file)
    if valid_lines is None:
        return None

    for lr in line_ranges:
        if lr.start in valid_lines:
            end = lr.end if lr.end is not None and lr.end in valid_lines else None
            return (lr.start, end)
    return None


def format_line_ranges(line_ranges: list[LineRange]) -> str:
    """Format line ranges as a readable string (e.g. '12, 40-45')."""
    parts = []
    for lr in line_ranges:
        if lr.end is None or lr.end == lr.start:
            parts.append(str(lr.start))
        else:
            parts.append(f"{lr.start}-{lr.end}")
    return ", ".join(parts)
