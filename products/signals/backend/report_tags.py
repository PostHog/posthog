"""Slug tags on inbox reports, and the rules every writer follows.

- A writer sends the whole set. A list replaces the stored set, and `None` (an omitted field)
  keeps it. This is the task tags rule.
- A merge gives the survivor the union of its own tags and the sources' tags (`union_report_tags`).
- A stack plan layer starts with the plan's tags.
- A report never takes tags from its signals' `extra.tags`.
- Research writes the whole set with the title and summary on each pass (`coerce_report_tags`). An
  invalid tag from the agent is dropped with a warning, so it never fails the run.

Tags live in the `SignalReport.tags` column, not in the shared `TaggedItem` system. Every reader
filters one column with no join, `Tag` rows would show report tags in the tag picker for other
objects, and a `TaggedItem` delete writes an activity log row on each replace.
"""

from collections import Counter
from collections.abc import Sequence

import structlog

from products.signals.backend.models import SignalReport
from products.signals.backend.scout_harness.tags import slugify_tag

logger = structlog.get_logger(__name__)

# The research prompt shows this many of the team's most-used tags, so a run reuses a tag before it
# invents a near duplicate.
TEAM_TAG_VOCABULARY_SIZE = 30
# The vocabulary query reads at most this many of the team's newest reports, so its cost does not
# grow with the team's report history.
TEAM_TAG_VOCABULARY_SAMPLE = 500


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


def coerce_report_tags(tags: Sequence[object]) -> list[str]:
    """`normalize_report_tags` for agent output, which must never fail a research run.

    Drops each tag that does not normalize and keeps the first `SignalReport.MAX_TAGS`, with a warning
    for each loss instead of a `ValueError`.
    """
    kept: list[str] = []
    # Counts by reason only, never the tag text: agent output can carry customer data or secrets.
    rejected: Counter[str] = Counter()
    for raw in tags:
        slug = slugify_tag(raw) if isinstance(raw, str) else ""
        if not isinstance(raw, str):
            rejected["not_a_string"] += 1
        elif not slug:
            rejected["empty_after_normalization"] += 1
        elif len(slug) > SignalReport.MAX_TAG_LENGTH:
            rejected["too_long"] += 1
        elif slug not in kept:
            kept.append(slug)
    if len(kept) > SignalReport.MAX_TAGS:
        rejected["over_the_cap"] = len(kept) - SignalReport.MAX_TAGS
        kept = kept[: SignalReport.MAX_TAGS]
    if rejected:
        logger.warning("report tags: dropped tags", rejected=dict(rejected))
    return kept


def team_tag_vocabulary(team_id: int) -> list[str]:
    """The team's most-used report tags, most-used first, counted over its newest reports."""
    # Limit first and filter in Python. A SQL filter on `tags` or `status` before the limit can walk
    # the team's whole history on the `(team, created_at)` index when few reports match.
    rows = (
        SignalReport.objects.filter(team_id=team_id)
        .order_by("-created_at")
        .values_list("tags", "status")[:TEAM_TAG_VOCABULARY_SAMPLE]
    )
    counts = Counter(tag for tags, status in rows if status != SignalReport.Status.DELETED for tag in tags)
    return [tag for tag, _ in counts.most_common(TEAM_TAG_VOCABULARY_SIZE)]


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
