from collections.abc import Collection
from datetime import datetime

from django.utils import timezone

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
    filter_stale_flags,
    rollout_state_and_variant,
)
from products.feature_flags.backend.flag_version_sync import direct_flag_dependency_ids, flags_with_flag_dependencies
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.session_recording_links import replay_linked_flag_ids_for_projects
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey

# `last_called_at` exists and predates the stale threshold. The column only records received
# `$feature_flag_called` events, so it says nothing about evaluations that send no event.
EVIDENCE_NOT_CALLED_RECENTLY = "not_called_recently"
# No call evidence at all; the flag is old enough and its configuration serves a fixed
# result. This says nothing about whether SDKs still evaluate the flag.
EVIDENCE_FULLY_ROLLED_OUT_WITHOUT_USAGE_DATA = "fully_rolled_out_without_usage_data"

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
    # Postgres-heavy and one issue per stale flag rather than per team, so smaller
    # batches than the default policy.
    policy = HealthExecutionPolicy(batch_size=250, max_concurrent=2)
    # Dry until the feature-flags scout can consume these issues; flipping this is an
    # operational checkpoint, not a code change to make casually.
    dry_run = True
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
        candidates = list(
            filter_stale_flags(
                FeatureFlag.objects.filter(
                    team_id__in=team_ids,
                    deleted=False,
                    archived=False,
                    active=True,
                ).exclude(is_remote_configuration=True)
            )
        )
        if not candidates:
            return {}

        excluded_ids = _excluded_flag_ids(candidates)

        now = timezone.now()
        issues: dict[int, list[HealthCheckResult]] = {}
        for flag in candidates:
            if flag.id in excluded_ids:
                continue
            issues.setdefault(flag.team_id, []).append(_build_result(flag, now))
        return issues


def _excluded_flag_ids(candidates: list[FeatureFlag]) -> set[int]:
    """Flag ids that known blockers reference, a superset of the candidate ids.

    Every lookup is one set-wise query over the batch; the count stays fixed as the
    candidate volume grows. These exclusions remove known blockers only. They do not prove
    the remaining flags are free of repository references or product intent.
    """
    flag_ids = [flag.id for flag in candidates]
    team_ids = {flag.team_id for flag in candidates}
    # Replay links and flag dependencies are project-scoped: a sibling team in the same
    # project can reference a flag this batch's teams own.
    project_ids = set(Team.objects.filter(id__in=team_ids).values_list("project_id", flat=True))

    excluded: set[int] = set()
    excluded |= Survey.get_internal_flag_ids(team_ids=team_ids)
    excluded |= set(
        ProductTour.all_objects.filter(team_id__in=team_ids, internal_targeting_flag__isnull=False).values_list(
            "internal_targeting_flag_id", flat=True
        )
    )
    excluded |= set(
        Experiment.objects.filter(feature_flag_id__in=flag_ids, deleted=False).values_list("feature_flag_id", flat=True)
    )
    excluded |= set(
        EarlyAccessFeature.objects.filter(feature_flag_id__in=flag_ids).values_list("feature_flag_id", flat=True)
    )
    excluded |= _depended_on_flag_ids(project_ids)
    excluded |= replay_linked_flag_ids_for_projects(project_ids, flag_ids)
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


def _build_result(flag: FeatureFlag, now: datetime) -> HealthCheckResult:
    checker = FeatureFlagStatusChecker(feature_flag=flag)
    summary = checker.get_rollout_summary(flag)
    rollout_state, winning_variant = rollout_state_and_variant(flag, checker, summary)

    if flag.last_called_at is not None:
        evidence_class = EVIDENCE_NOT_CALLED_RECENTLY
        evidence_date = flag.last_called_at
    else:
        evidence_class = EVIDENCE_FULLY_ROLLED_OUT_WITHOUT_USAGE_DATA
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
