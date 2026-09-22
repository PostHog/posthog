from collections.abc import Collection
from datetime import datetime

from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.clickhouse.query_tagging import Product
from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.models.team import Team
from posthog.temporal.health_checks.detectors import HealthExecutionPolicy
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck, Remediation
from posthog.temporal.health_checks.models import HealthCheckResult

from products.early_access_features.backend.models import EarlyAccessFeature
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.flag_status import (
    ROLLOUT_FULLY_ROLLED_OUT,
    ROLLOUT_NOT_ROLLED_OUT,
    ROLLOUT_PARTIAL,
    FeatureFlagStatusChecker,
    filter_effectively_full_rollout_flags,
    filter_stale_flags,
    stale_flag_threshold,
)
from products.feature_flags.backend.flag_version_sync import direct_flag_dependency_ids, flags_with_flag_dependencies
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.session_recording_links import replay_gated_flags_for_projects
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey

logger = structlog.get_logger(__name__)

# `last_called_at` exists and predates the stale threshold. The column only records received
# `$feature_flag_called` events, so it says nothing about evaluations that send no event.
EVIDENCE_NOT_CALLED_RECENTLY = "not_called_recently"
# No call evidence at all; the flag is old enough and its configuration serves a fixed
# result. This says nothing about whether SDKs still evaluate the flag.
EVIDENCE_FULLY_ROLLED_OUT_WITHOUT_USAGE_DATA = "fully_rolled_out_without_usage_data"
# The configuration serves one fixed result and PostHog received a call inside the stale window.
# `filter_stale_flags` needs a call older than the threshold or no call data at all, so a flag at
# 100% that SDKs evaluate every day falls outside both of its branches and only this class sees it.
EVIDENCE_EFFECTIVELY_FULL_ROLLOUT = "effectively_full_rollout"

_ROLLOUT_STATE_TEXT = {
    ROLLOUT_FULLY_ROLLED_OUT: "fully rolled out",
    ROLLOUT_NOT_ROLLED_OUT: "not rolled out",
    ROLLOUT_PARTIAL: "partially rolled out",
}


class StaleFeatureFlagsCheck(HealthCheck):
    """One INFO issue per user-managed flag that qualifies as a cleanup candidate.

    The evidence layer for proactive stale-flag cleanup: the feature-flags scout reads
    these issues and authors the Inbox reports itself, so this check must not implement
    `render_signal` (the framework default returns None). A stale verdict is evidence for
    investigation, never proof that removal is safe.
    """

    name = "stale_feature_flags"
    kind = "stale_feature_flags"
    owner = JobOwners.TEAM_FEATURE_FLAGS
    product = Product.FEATURE_FLAGS
    schedule = "0 6 * * 1"  # weekly, Mondays 06:00 UTC
    # Payloads carry flag keys and names.
    access_controlled_resource = "feature_flag"
    # Postgres-heavy and one issue per stale flag rather than per team, so smaller
    # batches than the default policy.
    policy = HealthExecutionPolicy(batch_size=250, max_concurrent=2)
    # Dry until the feature-flags scout can consume these issues; flipping this is an
    # operational checkpoint, not a code change to make casually.
    dry_run = True
    # dry_run stops the writes, not the detection queries. Sample teams until one batch of
    # this check has a measured cost, because filter_stale_flags has only ever run paginated
    # for a single team.
    rollout_percentage = 0.01
    remediation = Remediation(
        human="""
            Open the flag and confirm the staleness evidence is still current. Check every
            repository and runtime that evaluates the flag for code references, and check linked
            systems: experiments, surveys, early access features, session replay settings, and
            other flags that depend on it. Confirm the rollout intent with the flag's owner.
            Then clean up in this order: remove the code checks first and keep the winning
            behavior, merge and deploy, let the release soak, verify that no runtime still
            evaluates the flag, and only then archive it. Do not delete a flag that is rolled
            out to nobody while deployed code still checks it; the disabled path is still the
            code path in use.
        """,
        agent="""
            Read this issue with `health-issues-get`, then re-read the current flag definition
            with the feature-flag tools before acting; the issue's evidence is a snapshot and
            the flag may have changed since detection. Treat a stale verdict as evidence for
            investigation, not proof that removal is safe. Load the stale-flag cleanup skill if
            one is available. Search the user's repositories for the flag key, and check linked
            systems: experiments, surveys, early access features, session replay settings, and
            dependent flags. The cleanup order is fixed: remove code checks first, merge and
            deploy, observe a release soak, verify all relevant runtimes, and archive last.
            Never archive, disable, or delete the flag as part of health detection.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        payload = issue.payload
        # Flag keys and names are project data; keep interpolated text bounded.
        flag_key = str(payload.get("flag_key") or "unknown")[:200]
        days = payload.get("days_since_evidence")
        if payload.get("evidence_class") == EVIDENCE_NOT_CALLED_RECENTLY:
            evidence_text = (
                f"PostHog has not received a call for this flag in {days} days"
                if isinstance(days, int)
                else "PostHog has not received a call for this flag recently"
            )
        elif payload.get("evidence_class") == EVIDENCE_EFFECTIVELY_FULL_ROLLOUT:
            evidence_text = "PostHog still receives calls for this flag"
        else:
            evidence_text = "This flag has no usage data and its configuration serves a fixed result"
        rollout_text = _ROLLOUT_STATE_TEXT.get(payload.get("rollout_state"))
        rollout_sentence = f" The flag is {rollout_text}." if rollout_text else ""
        flag_id = payload.get("flag_id")
        return AlertContent(
            title=f"Feature flag '{flag_key}' may be ready for cleanup",
            summary=(
                f"{evidence_text}.{rollout_sentence} "
                "Review code references and linked systems before removing anything."
            ),
            link=f"/feature_flags/{flag_id}" if flag_id is not None else "/feature_flags",
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        reportable_flags = FeatureFlag.objects.filter(
            team_id__in=team_ids,
            deleted=False,
            archived=False,
            active=True,
        ).exclude(is_remote_configuration=True)

        # One cutoff for the whole run: both candidate queries and the evidence classification
        # compare against it. A second clock read would let a flag whose last call sits on the
        # boundary be selected by one of them and then classified against the other.
        stale_threshold = stale_flag_threshold()

        stale_candidates = list(filter_stale_flags(reportable_flags, stale_threshold=stale_threshold))
        # Only a never-called stale flag can come back from the rollout query too: a usage-stale
        # flag's last call predates the cutoff, which fails the call-recency filter below. Excluding
        # those ids beats fetching the rows again and dropping them in Python, and
        # `hash_keys=["flag_id"]` would otherwise give both rows the same issue identity.
        # The ids go in as a bound list. A subquery looks tidier and is wrong here: the inner
        # `.extra(where=...)` hard-codes `posthog_featureflag`, the subquery aliases that table,
        # and the raw text then tests the outer row instead of the inner one.
        overlap_ids = {flag.id for flag in stale_candidates if flag.last_called_at is None}
        # The prefilter reads configuration only and returns a superset, so the policy that makes
        # one of those flags a cleanup candidate is applied here, and the checker settles each
        # remaining row. A flag created after the cutoff is too new for a constant configuration to
        # mean the rollout is finished, and one that went cold is already a `filter_stale_flags`
        # row. Call recency is spelled as a positive filter because
        # `exclude(last_called_at__lt=...)` on a nullable column drops the rows with no call data,
        # which have to stay in.
        full_rollout_query = (
            filter_effectively_full_rollout_flags(reportable_flags)
            .filter(
                Q(last_called_at__isnull=True) | Q(last_called_at__gte=stale_threshold),
                created_at__lt=stale_threshold,
            )
            .exclude(pk__in=overlap_ids)
        )
        full_rollout_candidates = [
            flag
            for flag in full_rollout_query
            if not _serves_more_than_one_result(flag)
            and FeatureFlagStatusChecker(feature_flag=flag).is_flag_fully_rolled_out(flag)[0]
        ]
        candidates = stale_candidates + full_rollout_candidates
        if not candidates:
            return {}

        excluded_ids = _excluded_flag_ids(candidates)
        full_rollout_ids = {flag.id for flag in full_rollout_candidates}

        now = timezone.now()
        issues: dict[int, list[HealthCheckResult]] = {}
        for flag in candidates:
            if flag.id in excluded_ids:
                continue
            issues.setdefault(flag.team_id, []).append(_build_result(flag, now, stale_threshold))

        if issues:
            # Each issue fires its own alert once dry_run flips, so the flip decision needs the
            # worst single team, which the framework's batch-wide dry-run summary does not show.
            issue_counts = [len(team_issues) for team_issues in issues.values()]
            evidence_classes = [
                result.payload["evidence_class"] for team_issues in issues.values() for result in team_issues
            ]
            logger.info(
                "stale_feature_flags_detected",
                teams_with_issues=len(issues),
                issue_count=sum(issue_counts),
                max_issues_per_team=max(issue_counts),
                effectively_full_rollout_evidence_count=evidence_classes.count(EVIDENCE_EFFECTIVELY_FULL_ROLLOUT),
                full_rollout_query_issue_count=len(full_rollout_ids - excluded_ids),
            )
        return issues


def _serves_more_than_one_result(flag: FeatureFlag) -> bool:
    """Whether the matcher can return more than the one result the checker named.

    `FeatureFlagStatusChecker` reads `groups` and `multivariate` and asks whether some release
    condition is at 100% with no properties. That is necessary for a fixed result and not
    sufficient, so this class needs the rest of the runtime model before it calls a flag constant.
    The checker stays as it is: it backs the flag status endpoint, the stale badge, bulk delete and
    Max, and the raw SQL behind the public `active=STALE` filter mirrors it. A follow-up has to
    reconcile the two meanings of full rollout; until then this guard holds the stricter one and
    only the effectively-full-rollout class reads it.

    The other candidate source is left alone. Its evidence is that PostHog stopped receiving calls,
    which none of this contradicts.
    """
    filters = flag.filters or {}
    # A holdout is resolved before the release conditions and returns `holdout-<id>` to its share,
    # legacy super groups short-circuit the same way, and `early_exit` returns false on a failed
    # rollout check instead of falling through to a later blanket condition.
    # Two siblings encode part of the same evaluation order. `group_cohort_restriction_blocker` in
    # `products/feature_flags/backend/facade/filters.py` reads `holdout`, `holdout_groups` and
    # `super_groups`. `is_unconditionally_fully_rolled_out` in
    # `products/feature_flags/backend/persisted_flags.py` reads `holdout` and `super_groups`.
    # Neither reads `early_exit`, so the three lists have never been in parity.
    if any(filters.get(key) for key in ("holdout", "holdout_groups", "super_groups", "early_exit")):
        return True
    # These three decide the result from evaluation context the configuration does not carry, so a
    # blanket condition does not reach everyone. A group-aggregated condition is skipped for a
    # request that carries no group of that type. Device-id bucketing skips person-aggregated
    # conditions when the request has no device id. Feature enrollment evaluates the flag against
    # the person property `$feature_enrollment/{key}`. An explicit null aggregation index means
    # person aggregation, so only a set index excludes.
    if flag.bucketing_identifier == "device_id" or filters.get("feature_enrollment"):
        return True
    groups = filters.get("groups") or []
    if filters.get("aggregation_group_type_index") is not None:
        return True
    if any(group.get("aggregation_group_type_index") is not None for group in groups):
        return True
    return not _multivariate_results_agree(flag)


def _multivariate_results_agree(flag: FeatureFlag) -> bool:
    """Whether every user a multivariate flag can reach receives the same variant.

    The matcher reads the release conditions in declaration order and stops at the first one that
    matches, so a condition declared before the blanket one decides the result for the users it
    matches. A condition carrying a `variant` override serves that variant, and any other condition
    serves whatever the variant distribution gives. The flag is constant only when every one of
    those paths lands on the same variant.

    Boolean flags are constant by this test, because every condition that matches returns true.
    """
    variants = ((flag.filters or {}).get("multivariate") or {}).get("variants") or []
    if not variants:
        return True
    return _sole_served_variant(flag) is not None


def _sole_served_variant(flag: FeatureFlag) -> str | None:
    """The one variant that every reachable path serves, or None when the paths disagree.

    A boolean flag carries no variants and returns None, so a caller must not read None as "the
    flag is not constant". `_multivariate_results_agree` holds that distinction.
    """
    filters = flag.filters or {}
    variants = ((filters.get("multivariate") or {}).get("variants")) or []

    groups = filters.get("groups") or []
    checker = FeatureFlagStatusChecker(feature_flag=flag)
    decider = next((index for index, group in enumerate(groups) if checker.is_group_fully_rolled_out(group)), None)
    if decider is None:
        return None

    distributed = _sole_reachable_variant(variants)
    variant_keys = {variant.get("key") for variant in variants}
    results = set()
    for group in groups[: decider + 1]:
        # A missing rollout_percentage evaluates to 100% at runtime, matching `get_rollout_summary`.
        percentage = group.get("rollout_percentage")
        if percentage is not None and percentage <= 0:
            continue
        # The matcher ignores an override naming a variant the flag does not configure, and the
        # distribution decides instead.
        override = group.get("variant")
        results.add(override if override in variant_keys else distributed)
    # `None` is in the set when a path falls through to a distribution that is not itself constant.
    if len(results) != 1:
        return None
    (served,) = results
    return served


def _sole_reachable_variant(variants: list[dict]) -> str | None:
    """The only variant the distribution can serve, or None when a user can land on more than one.

    Variants take cumulative slices of the hash space in declaration order, so the first variant
    with a non-zero rollout takes the low hashes. Only that variant exists when it takes the whole
    space. A list such as `[40, 100]` is overallocated: the 100 does not make the flag constant,
    because the 40 still owns the low hashes.
    """
    for variant in variants:
        percentage = variant.get("rollout_percentage") or 0
        if percentage <= 0:
            continue
        return variant.get("key") if percentage >= 100 else None
    return None


def _excluded_flag_ids(candidates: list[FeatureFlag]) -> set[int]:
    """Flag ids that known blockers reference, not limited to the candidate ids.

    Every lookup is scoped by team or project rather than by candidate flag id, so each
    one binds a handful of parameters per batch and can return ids for flags outside it.

    Every lookup is one set-wise query over the batch; the count stays fixed as the
    candidate volume grows. These exclusions remove known blockers only. They do not prove
    the remaining flags are free of repository references or product intent.

    The bulk-delete guard in ``products/feature_flags/backend/api/feature_flag.py`` blocks
    the same references and must stay in step with this list. Where the two differ it is on
    purpose, and this list is the stricter one: the guard blocks only running experiments
    where this excludes every non-deleted one, the guard's ``find_dependent_flags_batch``
    counts only active dependent flags where this also lets disabled dependents block, and
    the guard matches a replay gate only within the flag's own project where this matches a
    stored id across every project scanned.

    A survey's user-created ``linked_flag`` is deliberately not excluded, unlike the
    survey flags PostHog generates itself. It is user-managed, bulk delete permits it, and
    the remediation tells the investigator to check surveys. A reported flag is evidence
    to investigate, not a verdict that removal is safe.
    """
    team_ids = {flag.team_id for flag in candidates}
    # Product tours, replay links, and flag dependencies are scoped by project, not by team:
    # another team in the same project can reference a flag this batch's teams own. A product
    # tour stays on the environment that created it, while a flag moves to the project root.
    # Surveys stay on team scope: Survey and FeatureFlag both inherit RootTeamMixin, so both
    # rows always sit on the project root team and their team ids line up.
    team_projects = dict(Team.objects.filter(id__in=team_ids).values_list("id", "project_id"))
    project_ids = set(team_projects.values())

    excluded: set[int] = set()
    excluded |= Survey.get_internal_flag_ids(team_ids=team_ids)
    excluded |= set(
        ProductTour.all_objects.filter(
            team__project_id__in=project_ids, internal_targeting_flag__isnull=False
        ).values_list("internal_targeting_flag_id", flat=True)
    )
    excluded |= set(
        Experiment.objects.filter(team_id__in=team_ids, deleted=False).values_list("feature_flag_id", flat=True)
    )
    excluded |= set(
        EarlyAccessFeature.objects.filter(team_id__in=team_ids, feature_flag_id__isnull=False).values_list(
            "feature_flag_id", flat=True
        )
    )
    excluded |= _depended_on_flag_ids(project_ids)
    # A trigger group counts here as much as the linked-flag column: both gate recording, so a
    # flag either one names must not be reported as a cleanup candidate.
    replay_gates = replay_gated_flags_for_projects(project_ids)
    # A stored id is matched against every project scanned, because flag ids are globally unique.
    # Only the stored key reaches an SDK, so a team holding another project's flag id gates no
    # recording on that flag. The candidate is withheld anyway, because a hard delete leaves that
    # reference unrepairable. `repair_replay_linked_flag_keys` reports such a row as
    # `FLAG_IN_OTHER_PROJECT` and has no key it can safely adopt.
    excluded |= {flag_id for gates in replay_gates.values() for flag_id in gates.flag_ids}
    # A stored key is matched only within its own project, because a key names one flag only
    # there, and pooling keys would let a key stored in one project protect a same-keyed flag in
    # another.
    excluded |= {
        flag.id
        for flag in candidates
        if (project_id := team_projects.get(flag.team_id)) is not None
        and (gates := replay_gates.get(project_id)) is not None
        and flag.key in gates.flag_keys
    }
    return excluded


def _depended_on_flag_ids(project_ids: Collection[int]) -> set[int]:
    """Ids of flags that at least one non-deleted flag has a flag-type condition on.

    Matches local-evaluation payload semantics (all non-deleted flags, active or not):
    a disabled dependent still ships in the payload and can be re-enabled, so it must
    keep protecting its dependency from cleanup.
    """
    dependents = flags_with_flag_dependencies(project_ids)
    depended_on: set[int] = set()
    for dependent in dependents:
        depended_on |= direct_flag_dependency_ids(dependent)
    return depended_on


def _build_result(flag: FeatureFlag, now: datetime, stale_threshold: datetime) -> HealthCheckResult:
    checker = FeatureFlagStatusChecker(feature_flag=flag)
    summary = checker.get_rollout_summary(flag)
    rollout_state, winning_variant = checker.rollout_state_and_variant(flag, summary)

    # The checker returns a condition's `variant` override without testing it against the variants
    # the flag configures, so a legacy row naming an absent key reaches the payload and the
    # remediation then names a variant nobody receives. Prefer the variant the matcher serves. A
    # flag whose reachable paths disagree has no such variant, so it keeps the checker's value.
    served_variant = _sole_served_variant(flag)
    if served_variant is not None:
        winning_variant = served_variant

    # Read off the flag rather than off the query that found it, so the payload describes the row
    # a reader opens. Every candidate is old enough and serves a fixed result or went cold, so the
    # call column is what separates the three classes.
    if flag.last_called_at is None:
        evidence_class = EVIDENCE_FULLY_ROLLED_OUT_WITHOUT_USAGE_DATA
        evidence_date = flag.created_at
    elif flag.last_called_at < stale_threshold:
        evidence_class = EVIDENCE_NOT_CALLED_RECENTLY
        evidence_date = flag.last_called_at
    else:
        evidence_class = EVIDENCE_EFFECTIVELY_FULL_ROLLOUT
        # No column records when the flag reached 100%, and `last_called_at` reads as about zero
        # days on a flag that is called every day, which is the opposite of the point.
        evidence_date = flag.created_at

    return HealthCheckResult(
        severity=HealthIssue.Severity.INFO,
        payload={
            "flag_id": flag.id,
            "flag_key": flag.key,
            "flag_name": (flag.name or "")[:500],
            "evidence_class": evidence_class,
            "evidence_date": evidence_date.isoformat(),
            "days_since_evidence": (now - evidence_date).days,
            "rollout_state": rollout_state,
            "winning_variant": winning_variant,
            "has_targeting_conditions": summary.has_targeting_conditions,
            "max_rollout_percentage": summary.max_rollout_percentage,
            "flag_version": flag.version,
        },
        hash_keys=["flag_id"],
    )
