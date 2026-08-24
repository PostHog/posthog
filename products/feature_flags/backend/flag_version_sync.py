"""
Bumps FeatureFlag.version when something a flag depends on changes: a cohort it
references, or another flag it depends on.

SDKs consuming the local-evaluation payload use a flag's ``version`` to detect when its
definition changed. A flag's effective definition includes the conditions of every
cohort it references (directly or through nested cohorts) and the definition of every
flag it depends on (directly or transitively), so editing either must bump the version
of every flag downstream — even though those flag rows themselves didn't change.

Each bump also writes a FeatureFlag activity log entry ("flag history"). That entry is
load-bearing, not just informational: ``version_history.reconstruct_flag_at_version``
rebuilds historical flag states by walking activity entries via their ``version``
change, and raises ``VersionHistoryIncomplete`` for any version number that has no
entry — which is exactly what a silent bump would create.

Membership recalculation bookkeeping must never bump versions: the periodic
recalculation cycle saves every stale dynamic cohort roughly every 15 minutes, and
version churn there would invalidate every SDK cache (and the payload ETag) with no
definition change. The same goes for flag edits that leave the flag's conditions alone
(renames, folder moves, analytics bookkeeping). The pre_save snapshot plus value
comparison below guarantees only real definition changes bump.

The bumps run synchronously inside the triggering save's transaction rather than on
commit: the flag-change signals schedule cache rebuilds via ``on_commit`` callbacks,
so a bump deferred to commit time could run after a rebuild has already read the
pre-bump versions.
"""

from collections import defaultdict
from typing import Any

from django.db import models, transaction
from django.db.models import Value
from django.db.models.functions import Coalesce
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import Change, Detail, LogActivityEntry, Trigger, bulk_log_activity
from posthog.models.activity_logging.utils import activity_storage

from products.cohorts.backend.models.cohort import Cohort, CohortOrEmpty
from products.feature_flags.backend.models.feature_flag import FeatureFlag

logger = structlog.get_logger(__name__)

# Also referenced by the frontend flag activity describer — keep the two in sync.
COHORT_CONDITIONS_UPDATED_JOB_TYPE = "cohort_conditions_updated"
FLAG_DEPENDENCY_UPDATED_JOB_TYPE = "flag_dependency_updated"

# Fields that make up a cohort's conditions. Saves that persist a value change to any
# of these bump the versions of flags referencing the cohort; everything else
# (recalculation bookkeeping, renames, folder moves) must not.
COHORT_DEFINITION_FIELDS = frozenset({"filters", "query", "groups", "is_static"})

# Fields of a flag that change how a flag depending on it ("flag_evaluates_to") resolves:
# `filters` is the condition set the dependent inherits, `active` and `deleted` make the
# dependency resolve false and drop it from the payload, and `key` is embedded in the
# dependent's own payload (local evaluation rewrites the stored flag id to the key and
# inlines a dependency_chain of keys). Delivery and metadata attributes are deliberately
# out: `ensure_experience_continuity`, `evaluation_runtime` and `bucketing_identifier`
# shape how the base flag itself is served rather than what it resolves to, and
# name/folder/analytics bookkeeping don't touch conditions at all. `archived` is covered
# transitively: the `archived_flag_must_be_disabled` constraint means archiving always
# moves `active` too.
FLAG_DEFINITION_FIELDS = frozenset({"filters", "active", "deleted", "key"})

_DEFINITION_BEFORE_SAVE_ATTR = "_definition_before_save"


def _capture_definition_before_save(
    instance: models.Model,
    manager: models.Manager[Any],
    definition_fields: frozenset[str],
    update_fields: frozenset[str] | None,
    raw: bool,
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
    fields = definition_fields if update_fields is None else definition_fields.intersection(update_fields)
    if not fields:
        return
    # sorted(): set iteration order varies between processes, and it reaches the SELECT's
    # column list — an unstable query string defeats plan reuse and makes the query
    # snapshots that cover flag saves fail at random.
    setattr(instance, _DEFINITION_BEFORE_SAVE_ATTR, manager.filter(pk=instance.pk).values(*sorted(fields)).first())


def _changed_definition_fields(instance: models.Model) -> dict[str, Any] | None:
    """Pop the pre_save snapshot and return it only if a snapshotted value changed."""
    before = instance.__dict__.pop(_DEFINITION_BEFORE_SAVE_ATTR, None)
    if before is None:
        return None
    if all(getattr(instance, field) == value for field, value in before.items()):
        return None
    return before


@receiver(pre_save, sender=Cohort)
def capture_cohort_definition_before_save(
    sender: type[Cohort],
    instance: Cohort,
    raw: bool = False,
    update_fields: frozenset[str] | None = None,
    **kwargs: Any,
) -> None:
    _capture_definition_before_save(instance, Cohort.objects, COHORT_DEFINITION_FIELDS, update_fields, raw)


@receiver(pre_save, sender=FeatureFlag)
def capture_flag_definition_before_save(
    sender: type[FeatureFlag],
    instance: FeatureFlag,
    raw: bool = False,
    update_fields: frozenset[str] | None = None,
    **kwargs: Any,
) -> None:
    # objects_including_soft_deleted so restoring a soft-deleted flag reads as a
    # deleted True -> False change instead of snapshotting nothing.
    _capture_definition_before_save(
        instance, FeatureFlag.objects_including_soft_deleted, FLAG_DEFINITION_FIELDS, update_fields, raw
    )


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
    if _changed_definition_fields(instance) is None:
        return

    project_id = instance.team.project_id
    referencing_flags = _flags_referencing_cohort(instance)
    if not referencing_flags:
        return
    # Flags depending on a flag whose cohort conditions moved are downstream of the same
    # change. The bump below is a bulk update, which fires no signals, so the flag
    # receiver can never pick these up — this path has to expand them itself.
    dependents = _dependent_flags(referencing_flags, project_id)
    # Only the flags that actually reference the cohort name it in their history; a flag
    # further down the chain doesn't reference it, so it names the flag it depends on.
    triggers: dict[int, Trigger] = {flag.pk: _cohort_conditions_trigger(instance) for flag in referencing_flags}
    triggers.update({dependent.pk: _flag_dependency_trigger(origin) for dependent, origin in dependents})
    _bump_flag_versions(referencing_flags + [dependent for dependent, _ in dependents], project_id, triggers)


@receiver(post_save, sender=FeatureFlag)
def bump_dependent_flag_versions_on_flag_definition_change(
    sender: type[FeatureFlag],
    instance: FeatureFlag,
    created: bool = False,
    raw: bool = False,
    **kwargs: Any,
) -> None:
    if raw or created:
        return
    before = _changed_definition_fields(instance)
    if before is None:
        return
    # An already-deleted flag is in no payload, so edits to it (e.g. the tombstone rename
    # that frees a key for reuse) can't change how any dependent resolves. A save that
    # leaves `deleted` out of update_fields doesn't snapshot it, and doesn't write it
    # either, so the instance's value is the persisted one.
    if before.get("deleted", instance.deleted) and instance.deleted:
        return

    project_id = instance.team.project_id
    # The saved flag is excluded: whoever edited it already bumped and logged its version.
    dependents = _dependent_flags([instance], project_id)
    _bump_flag_versions(
        [dependent for dependent, _ in dependents],
        project_id,
        {dependent.pk: _flag_dependency_trigger(origin) for dependent, origin in dependents},
    )


def _bump_flag_versions(flags: list[FeatureFlag], project_id: int, triggers: dict[int, Trigger]) -> None:
    if not flags:
        return
    with transaction.atomic():
        # Lock the affected rows (and only them — of="self" keeps the joined team row
        # unlocked) so the versions logged below exactly match what the UPDATE writes
        # even under concurrent flag edits (which take the same lock in the serializer);
        # a mismatched entry breaks version-history reconstruction the same way a
        # missing one does. pk order keeps the lock order consistent.
        old_versions = dict(
            FeatureFlag.objects.filter(pk__in=[flag.pk for flag in flags], team__project_id=project_id)
            .select_for_update(of=("self",))
            .order_by("pk")
            .values_list("pk", "version")
        )
        # Bypassing FeatureFlag.save() (and its signals) is intentional: the triggering
        # save already invalidates the project's flag cache, and these flags' own fields
        # are untouched, so updated_at/last_modified_by stay as they were. It's also why
        # the dependent set above is expanded transitively up front — no post_save fires
        # for these rows to continue the cascade (and nothing can recurse).
        # The flag-history entry the signal path would have produced is written
        # explicitly below instead.
        FeatureFlag.objects.filter(pk__in=old_versions.keys(), team__project_id=project_id).update(
            version=Coalesce("version", Value(0)) + 1
        )
        bulk_log_activity(
            [
                _flag_version_bump_entry(flag, old_version=old_versions[flag.pk], trigger=triggers[flag.pk])
                for flag in flags
                if flag.pk in old_versions
            ]
        )


def _cohort_conditions_trigger(cohort: Cohort) -> Trigger:
    return Trigger(
        job_type=COHORT_CONDITIONS_UPDATED_JOB_TYPE,
        job_id=str(cohort.pk),
        payload={"cohort_id": cohort.pk, "cohort_name": cohort.name},
    )


def _flag_dependency_trigger(flag: FeatureFlag) -> Trigger:
    return Trigger(
        job_type=FLAG_DEPENDENCY_UPDATED_JOB_TYPE,
        job_id=str(flag.pk),
        payload={"flag_id": flag.pk, "flag_key": flag.key},
    )


def _flag_version_bump_entry(flag: FeatureFlag, old_version: int | None, trigger: Trigger) -> LogActivityEntry:
    """Build the flag-history entry for a dependency-driven version bump.

    The acting user comes from activity_storage (populated by middleware for API
    requests, i.e. whoever edited the cohort or upstream flag); outside a request the
    entry is logged as a system action.
    """
    return LogActivityEntry(
        organization_id=flag.team.organization_id,
        team_id=flag.team_id,
        user=activity_storage.get_user(),
        was_impersonated=activity_storage.get_was_impersonated(),
        item_id=flag.pk,
        scope="FeatureFlag",
        activity="updated",
        detail=Detail(
            name=flag.key,
            changes=[
                Change(
                    type="FeatureFlag",
                    action="changed",
                    field="version",
                    before=old_version,
                    after=(old_version or 0) + 1,
                )
            ],
            trigger=trigger,
        ),
    )


def _direct_flag_dependency_ids(flag: FeatureFlag) -> set[int]:
    """Flag ids this flag has a ``flag_evaluates_to`` release condition on.

    Same parse as ``flags_cache._extract_direct_dependency_ids`` (a dependency is keyed by
    the referenced flag's id in ``key``), minus its inactive/deleted short-circuit: a
    disabled flag still ships in the local-evaluation payload so dependencies can resolve
    it, so its dependents still need the bump. Tolerant of malformed values so one bad
    sibling flag can't break the save that triggered this.
    """
    dependency_ids: set[int] = set()
    try:
        conditions = flag.conditions
    except Exception:
        # A sibling flag with malformed filters must neither break the save nor suppress
        # the bump for healthy flags.
        logger.exception("flag_version_sync_dependency_parse_failed", flag_id=flag.pk, team_id=flag.team_id)
        capture_exception()
        return dependency_ids
    for condition in conditions:
        for prop in condition.get("properties") or []:
            if prop.get("type") != "flag":
                continue
            try:
                dependency_ids.add(int(prop["key"]))
            except (ValueError, KeyError, TypeError):
                continue
    return dependency_ids


def _dependent_flags(sources: list[FeatureFlag], project_id: int) -> list[tuple[FeatureFlag, FeatureFlag]]:
    """Non-deleted flags in the project that transitively depend on any source flag.

    Returns ``(dependent, origin)`` pairs, where origin is the source flag the chain
    started from — that's what the dependent's history entry names. Sources are never
    returned: their own versions are bumped by whatever changed them, and skipping them
    is also what makes a dependency cycle terminate here.

    Matches the payload semantics of local evaluation (all non-deleted flags, active or
    not). Deliberately not the ``find_dependent_flags`` lookup in the flag API, which is
    scoped to one team's active flags for the disable/delete guards, and lives in a module
    too heavy to import at app startup. One query builds the whole reverse graph so the
    walk below needs no further round trips.
    """
    candidate_flags = list(
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (static predicate, no user input)
        FeatureFlag.objects.filter(team__project_id=project_id, deleted=False)
        .extra(where=["""jsonb_path_exists(filters, '$.** ? (@.type == "flag")')"""])
        # select_related: the activity entry per bumped flag reads flag.team.organization_id.
        .select_related("team")
    )
    if not candidate_flags:
        return []

    dependents_of: dict[int, list[FeatureFlag]] = defaultdict(list)
    for flag in candidate_flags:
        for dependency_id in _direct_flag_dependency_ids(flag):
            dependents_of[dependency_id].append(flag)

    dependents: list[tuple[FeatureFlag, FeatureFlag]] = []
    seen = {flag.pk for flag in sources}
    frontier = [(flag.pk, flag) for flag in sources]
    while frontier:
        next_frontier: list[tuple[int, FeatureFlag]] = []
        for flag_id, origin in frontier:
            for dependent in dependents_of.get(flag_id, []):
                if dependent.pk in seen:
                    continue
                seen.add(dependent.pk)
                dependents.append((dependent, origin))
                next_frontier.append((dependent.pk, origin))
        frontier = next_frontier
    return dependents


def _flags_referencing_cohort(cohort: Cohort) -> list[FeatureFlag]:
    """Non-deleted flags in the cohort's project whose conditions reach this cohort.

    Matches the payload semantics of local evaluation (all non-deleted flags, active or
    not). Mirrors the used_in/deletion-protection lookup in ``posthog/api/cohort.py``,
    which can't be imported here without pulling the API layer into app startup: a
    DB-side pre-filter keeps the Python-side ``get_cohort_ids`` expansion to flags that
    reference some cohort at all — matching any cohort id (not just this one) is
    required, since a flag can reach this cohort transitively through another cohort.
    """
    candidate_flags = list(
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (static predicate, no user input)
        FeatureFlag.objects.filter(team__project_id=cohort.team.project_id, deleted=False)
        .extra(where=["""jsonb_path_exists(filters, '$.** ? (@.type == "cohort")')"""])
        .select_related("team")
    )
    # Static cohorts stop the traversal: their membership is a materialized person
    # list, so upstream condition changes don't alter how flags evaluate them.
    seen_cohorts_cache: dict[int, CohortOrEmpty] = {cohort.pk: cohort}
    # Bulk-load every cohort the flags reference directly (the same cohort-property walk
    # get_cohort_ids does), so the expansion below only point-queries cohorts nested
    # behind another cohort's filters. Missing ids are cached as empty so a dangling
    # reference doesn't re-query once per flag either. Guarded per flag: a malformed
    # sibling here must not break the save — the expansion loop below logs it.
    direct_ids: set[int] = set()
    for flag in candidate_flags:
        try:
            for condition in flag.conditions:
                for prop in condition.get("properties", []):
                    if prop.get("type") == "cohort" and str(prop.get("value")).lstrip("-").isdigit():
                        direct_ids.add(int(prop["value"]))
        except Exception:
            continue
    direct_ids -= seen_cohorts_cache.keys()
    if direct_ids:
        for direct_cohort in Cohort.objects.filter(
            pk__in=direct_ids, team__project_id=cohort.team.project_id, deleted=False
        ):
            seen_cohorts_cache[direct_cohort.pk] = direct_cohort
        for missing_id in direct_ids - seen_cohorts_cache.keys():
            seen_cohorts_cache[missing_id] = ""
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
