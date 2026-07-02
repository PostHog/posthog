"""
Bumps FeatureFlag.version when a cohort referenced by the flag changes its conditions.

SDKs consuming the local-evaluation payload use a flag's ``version`` to detect when its
definition changed. A flag's effective definition includes the conditions of every
cohort it references (directly or through nested cohorts), so editing a cohort's
conditions must bump the version of every flag using it — even though the flag rows
themselves didn't change.

Membership recalculation bookkeeping must never bump versions: the periodic
recalculation cycle saves every stale dynamic cohort roughly every 15 minutes, and
version churn there would invalidate every SDK cache (and the payload ETag) with no
definition change. The pre_save snapshot plus value comparison below guarantees only
real condition changes bump.
"""

from typing import Any

from django.db.models import Value
from django.db.models.functions import Coalesce
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

import structlog

from posthog.exceptions_capture import capture_exception

from products.cohorts.backend.models.cohort import Cohort, CohortOrEmpty
from products.feature_flags.backend.models.feature_flag import FeatureFlag

logger = structlog.get_logger(__name__)

# Fields that make up a cohort's conditions. Saves that persist a value change to any
# of these bump the versions of flags referencing the cohort; everything else
# (recalculation bookkeeping, renames, folder moves) must not.
COHORT_DEFINITION_FIELDS = frozenset({"filters", "query", "groups", "is_static"})

_DEFINITION_BEFORE_SAVE_ATTR = "_definition_before_save"


@receiver(pre_save, sender=Cohort)
def capture_cohort_definition_before_save(
    sender: type[Cohort],
    instance: Cohort,
    raw: bool = False,
    update_fields: frozenset[str] | None = None,
    **kwargs: Any,
) -> None:
    """Snapshot the persisted definition fields this save may overwrite.

    Always resets the snapshot first so a failed earlier save can never leak a stale
    capture into a later save's comparison.
    """
    setattr(instance, _DEFINITION_BEFORE_SAVE_ATTR, None)
    if raw or instance.pk is None:
        return
    # Only fields this save will actually persist: a definition field changed in
    # memory but excluded from update_fields is not written, so it must not count.
    fields = COHORT_DEFINITION_FIELDS if update_fields is None else COHORT_DEFINITION_FIELDS.intersection(update_fields)
    if not fields:
        return
    setattr(instance, _DEFINITION_BEFORE_SAVE_ATTR, Cohort.objects.filter(pk=instance.pk).values(*fields).first())


@receiver(post_save, sender=Cohort)
def bump_flag_versions_on_cohort_definition_change(
    sender: type[Cohort],
    instance: Cohort,
    created: bool = False,
    raw: bool = False,
    **kwargs: Any,
) -> None:
    if raw or created:
        return
    before = instance.__dict__.pop(_DEFINITION_BEFORE_SAVE_ATTR, None)
    if not before:
        return
    if all(getattr(instance, field) == value for field, value in before.items()):
        return

    flag_ids = [flag.pk for flag in _flags_referencing_cohort(instance)]
    if flag_ids:
        # Bumped in the same transaction as the cohort save, so the cache rebuilds the
        # cohort receivers enqueue via transaction.on_commit always read the new
        # versions. Bypassing FeatureFlag.save() (and its signals) is intentional: the
        # cohort save already triggers the team's cache invalidation, and the flag rows'
        # own fields are untouched, so updated_at/last_modified_by stay as they were.
        FeatureFlag.objects.filter(pk__in=flag_ids).update(version=Coalesce("version", Value(0)) + 1)


def _flags_referencing_cohort(cohort: Cohort) -> list[FeatureFlag]:
    """Non-deleted flags in the cohort's project whose conditions reach this cohort.

    Matches the payload semantics of local evaluation (all non-deleted flags, active or
    not). Mirrors the used_in/deletion-protection lookup in ``posthog/api/cohort.py``,
    which can't be imported here without pulling the API layer into app startup: a
    DB-side pre-filter keeps the Python-side ``get_cohort_ids`` expansion to flags that
    reference some cohort at all — matching any cohort id (not just this one) is
    required, since a flag can reach this cohort transitively through another cohort.
    """
    candidate_flags = (
        FeatureFlag.objects.filter(team__project_id=cohort.team.project_id)
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (static predicate, no user input)
        .extra(where=["""jsonb_path_exists(filters, '$.** ? (@.type == "cohort")')"""])
        .select_related("team")
    )
    # Static cohorts stop the traversal: their membership is a materialized person
    # list, so upstream condition changes don't alter how flags evaluate them.
    seen_cohorts_cache: dict[int, CohortOrEmpty] = {cohort.pk: cohort}
    flags: list[FeatureFlag] = []
    for flag in candidate_flags:
        try:
            if cohort.pk in flag.get_cohort_ids(seen_cohorts_cache=seen_cohorts_cache, stop_traversal_at_static=True):
                flags.append(flag)
        except Exception:
            # A sibling flag with malformed filters (e.g. a non-numeric cohort value,
            # which get_cohort_ids doesn't tolerate) must neither break the cohort save
            # nor suppress the bump for healthy flags.
            logger.exception(
                "flag_version_sync_cohort_expansion_failed",
                flag_id=flag.pk,
                cohort_id=cohort.pk,
                team_id=cohort.team_id,
            )
            capture_exception()
    return flags
