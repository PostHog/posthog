"""Slug tags on inbox reports, and the rules every writer follows.

- A writer sends the whole set. A list replaces the stored set, and `None` (an omitted field)
  keeps it. This is the task tags rule.
- A merge gives the survivor the union of its own tags and the sources' tags (`union_report_tags`).
- A stack plan layer starts with the plan's tags.
- A report never takes tags from its signals' `extra.tags`.

Tags live in the `SignalReport.tags` column, not in the shared `TaggedItem` system. Every reader
filters one column with no join, `Tag` rows would show report tags in the tag picker for other
objects, and a `TaggedItem` delete writes an activity log row on each replace.
"""

from collections.abc import Sequence

from products.signals.backend.models import SignalReport
from products.signals.backend.scout_harness.tags import slugify_tag


def normalize_report_tags(tags: list[str]) -> list[str]:
    """Deduped kebab-case slugs in first-seen order, by the same rules as scout finding tags.

    Raises `ValueError` when there are more than `SignalReport.MAX_TAGS`, or when a tag is empty or
    too long after normalization, so a writer learns that its tags did not stick.
    """
    if len(tags) > SignalReport.MAX_TAGS:
        raise ValueError(f"tags has {len(tags)} entries, max is {SignalReport.MAX_TAGS}")
    normalized: list[str] = []
    for raw in tags:
        slug = slugify_tag(raw)
        if not slug:
            raise ValueError(f"tag {raw!r} is empty after slug normalization")
        if len(slug) > SignalReport.MAX_TAG_LENGTH:
            raise ValueError(f"tag {raw!r} exceeds {SignalReport.MAX_TAG_LENGTH} chars after normalization")
        if slug not in normalized:
            normalized.append(slug)
    return normalized


def set_report_tags(report: SignalReport, tags: list[str] | None) -> bool:
    """Replace the report's tags with `normalize_report_tags(tags)`.

    Returns True when the stored set changed. Raises `ValueError` from `normalize_report_tags` and
    leaves the stored set as it was.
    """
    if tags is None:
        return False
    normalized = normalize_report_tags(tags)
    if normalized == report.tags:
        return False
    report.tags = normalized
    # Only `tags`, so a retag does not bump `updated_at` and skips the status and document receivers.
    report.save(update_fields=["tags"])
    return True


def union_report_tags(*tag_sets: Sequence[str]) -> list[str]:
    """The union of already-normalized tag sets in first-seen order, capped at `SignalReport.MAX_TAGS`."""
    merged: list[str] = []
    for tags in tag_sets:
        for tag in tags:
            if tag not in merged:
                merged.append(tag)
    return merged[: SignalReport.MAX_TAGS]
