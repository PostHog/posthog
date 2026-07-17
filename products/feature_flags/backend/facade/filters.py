"""Pure transforms over feature flag ``filters`` dicts, exposed via the facade.

These own the flag-schema knowledge (groups are OR'd, conditions AND within a group,
evaluation is top-down first-match, holdout/super groups are evaluated before release
conditions) so consumers don't have to. The marker keys and notes are opaque values
passed in by the caller — e.g. experiments' enrollment freeze — so the flag product
learns no consumer concepts.

Deliberately free of Django/DRF imports: consumer model modules import these predicates
at module level, and routing them through ``facade.api`` (which imports the flag
serializer, whose module imports back into consumers) would create an import cycle.
"""

from copy import deepcopy
from typing import Literal

CohortRestrictionBlocker = Literal["group_aggregation", "holdout", "super_groups", "no_groups"]


def restrict_groups_to_cohort(
    current_filters: dict,
    cohort_id: int,
    *,
    marker_key: str,
    cohort_key: str,
    marker_note: str,
) -> dict:
    """AND a static-cohort condition into every release group and stamp the marker key.

    AND (not a new group): groups are OR'd, so a separate group would *widen* access.
    AND (not replace): the original per-group ``properties``/``rollout_percentage`` are
    preserved so a future strip or manual revert restores exactly the original.
    The restricted state lives in the structured ``marker_key`` on each group and
    ``cohort_key`` records which cohort was AND'd in; ``marker_note`` is merely prepended
    to the (preserved) ``description`` as a human-readable note. Everything else
    (``multivariate``, ``payloads``, aggregation index) is left byte-for-byte.
    """
    cohort_condition = {"key": "id", "type": "cohort", "value": cohort_id, "operator": "in"}

    new_groups = []
    for group in current_filters.get("groups", []):
        # One deepcopy per group so the new filters never alias the original flag's dicts.
        new_group = deepcopy(group)
        new_group["properties"] = [*new_group.get("properties", []), cohort_condition]
        new_group[marker_key] = True
        new_group[cohort_key] = cohort_id
        existing_description = new_group.get("description")
        new_group["description"] = f"{marker_note} {existing_description}" if existing_description else marker_note
        new_groups.append(new_group)
    return {**current_filters, "groups": new_groups}


def strip_group_cohort_restriction(
    current_filters: dict,
    *,
    marker_key: str,
    cohort_key: str,
    marker_note: str,
) -> tuple[dict, list[int]]:
    """Inverse of restrict_groups_to_cohort: remove the restriction stamps from every
    release group — the AND'd cohort condition (identified via the per-group
    ``cohort_key``, so user-added cohort conditions survive), the two structured keys,
    and the description note. Groups without the marker key pass through untouched.

    Returns the stripped filters plus the cohort ids that were referenced, so callers
    can clean up the then-orphaned cohorts once the stripped filters are persisted — and only
    then: deleting earlier would yank the cohort from under a still-restricted flag if the
    save fails.
    """
    new_groups = []
    cohort_ids: list[int] = []
    for group in current_filters.get("groups", []):
        new_group = deepcopy(group)
        if new_group.get(marker_key) is not True:
            new_groups.append(new_group)
            continue
        new_group.pop(marker_key, None)
        cohort_id = new_group.pop(cohort_key, None)
        if cohort_id is not None:
            cohort_ids.append(cohort_id)
            new_group["properties"] = [
                condition
                for condition in new_group.get("properties", [])
                if not (
                    condition.get("type") == "cohort"
                    and condition.get("key") == "id"
                    and condition.get("value") == cohort_id
                )
            ]
        description = new_group.get("description")
        if isinstance(description, str) and marker_note in description:
            stripped_description = description.replace(marker_note, "").strip()
            if stripped_description:
                new_group["description"] = stripped_description
            else:
                # The restriction added the description outright — restore its absence.
                del new_group["description"]
        new_groups.append(new_group)
    return {**current_filters, "groups": new_groups}, list(dict.fromkeys(cohort_ids))


def groups_carry_restriction_marker(current_filters: dict, *, marker_key: str) -> bool:
    """Whether EVERY release group carries the ``marker_key`` restriction stamp.

    Checks only the stamp, not the AND'd cohort condition itself — a manually edited group
    could keep the stamp after losing the condition.

    All-groups (not any-group) so that adding or editing an unstamped group reads as the
    restriction being lifted; an empty ``groups`` list is not restricted (there is nothing
    holding anyone back).
    """
    groups = current_filters.get("groups", [])
    return bool(groups) and all(group.get(marker_key) is True for group in groups)


def set_holdout(current_filters: dict, *, holdout_id: int | None, exclusion_percentage: float | None) -> dict:
    """Set (or clear) the flag-level ``holdout`` object on the filters.

    Takes plain values — the caller resolves them from its own holdout concept, so the
    flag product learns none. Without a holdout id or a usable exclusion percentage the
    ``holdout`` key is written as None (not removed), so a previously attached holdout
    is detached by the same write.
    """
    if not holdout_id or exclusion_percentage is None:
        return {**current_filters, "holdout": None}
    return {**current_filters, "holdout": {"id": holdout_id, "exclusion_percentage": exclusion_percentage}}


def group_cohort_restriction_blocker(current_filters: dict) -> CohortRestrictionBlocker | None:
    """Why the flag's release groups can't be reversibly narrowed to a person cohort, or None.

    Encodes flag-matcher evaluation-order knowledge so consumers don't recompute it:

    - ``group_aggregation``: the flag aggregates by groups, not persons, so a person cohort
      cannot narrow who it serves.
    - ``holdout``: holdout assignment is evaluated before release conditions, so narrowing
      the groups cannot stop entry through the holdout.
    - ``super_groups``: early-access enrollment (super groups) is evaluated before release
      conditions too.
    - ``no_groups``: without release conditions there is nothing to narrow — the restriction
      would be a no-op and could never be detected from the group stamps.

    Checked in that order; the first blocker wins.
    """
    if current_filters.get("aggregation_group_type_index") is not None:
        return "group_aggregation"
    if current_filters.get("holdout") or current_filters.get("holdout_groups"):
        return "holdout"
    if current_filters.get("super_groups"):
        return "super_groups"
    if not current_filters.get("groups"):
        return "no_groups"
    return None
