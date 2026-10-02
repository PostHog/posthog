from datetime import datetime
from uuid import UUID

from posthog.api.app_metrics2 import fetch_app_metric_totals

from products.workflows.backend.facade.contracts import ProposalMetric, ProposalVersionOutcome
from products.workflows.backend.metrics import (
    GUARDRAIL_LABELS,
    GUARDRAIL_METRICS,
    HOG_FLOW_VERSION_APP_SOURCE,
    MIN_EVIDENCE_SAMPLE,
    TARGET_CLICK_METRIC,
    TARGET_OPEN_METRIC,
    TARGET_SEND_METRIC,
    TARGET_UNTRACKED_METRIC,
)
from products.workflows.backend.models.hog_flow_optimization import HogFlowOptimization
from products.workflows.backend.models.workflow_proposal import WorkflowProposal


def unstage_workflow_proposals(hog_flow_id: UUID) -> None:
    """Put every approved suggestion back in the queue, because the draft it was approved into is
    about to be replaced.

    Approved means one thing here: this suggestion is what sits in the draft. Discarding the draft,
    restoring a revision, approving a different suggestion or editing over it all replace that
    draft, and publish reads approved as "this is what shipped", so it must not record one against
    a version that never carried it. A suggestion whose change survives the replacement comes back
    to the queue too, which costs a person one more approval rather than a wrong history entry.
    """
    WorkflowProposal.objects.filter(hog_flow_id=hog_flow_id, status=WorkflowProposal.Status.APPROVED).update(
        status=WorkflowProposal.Status.SUGGESTED, resolved_at=None, resolved_by=None
    )


def version_outcome(
    *, team_id: int, hog_flow_id: UUID, version: int | None, after: datetime, step_id: str | None = None
) -> ProposalVersionOutcome | None:
    if version is None:
        return None
    # Scoped to the step the suggestion names; several email steps would otherwise share one denominator.
    totals = fetch_app_metric_totals(
        team_id=team_id,
        app_source=HOG_FLOW_VERSION_APP_SOURCE,
        app_source_id=f"{hog_flow_id}/{version}",
        breakdown_by="name",
        after=after,
        instance_id=step_id or None,
        name=[
            TARGET_SEND_METRIC,
            TARGET_OPEN_METRIC,
            TARGET_CLICK_METRIC,
            TARGET_UNTRACKED_METRIC,
            *GUARDRAIL_METRICS,
        ],
    ).totals
    sends = int(totals.get(TARGET_SEND_METRIC, 0))
    # Untracked sends can never record an open, so opens read against tracked sends; guardrails keep every send.
    tracked_sends = max(0, sends - int(totals.get(TARGET_UNTRACKED_METRIC, 0)))

    def rate(count: int, label: str, denominator: int) -> ProposalMetric:
        return {
            "metric": label,
            "value": (count / denominator) if denominator else None,
            "n": denominator,
            "below_minimum_sample": denominator < MIN_EVIDENCE_SAMPLE,
        }

    return {
        "version": version,
        "target": rate(int(totals.get(TARGET_OPEN_METRIC, 0)), "email open rate", tracked_sends),
        # Same denominator as opens: a send with tracking off can record neither.
        "click_through": rate(int(totals.get(TARGET_CLICK_METRIC, 0)), "click rate", tracked_sends),
        "guardrails": [rate(int(totals.get(name, 0)), GUARDRAIL_LABELS[name], sends) for name in GUARDRAIL_METRICS],
    }


def is_optimization_enabled(hog_flow_id: UUID) -> bool:
    return HogFlowOptimization.objects.filter(hog_flow_id=hog_flow_id, enabled=True).exists()


def set_optimization_enabled(*, hog_flow_id: UUID, enabled: bool) -> bool:
    """Turn suggestions on or off for one workflow. Returns whether the setting changed."""
    row = HogFlowOptimization.objects.filter(hog_flow_id=hog_flow_id).first()
    if row is None:
        # Turning it off for a workflow nobody turned on is a no-op, not a row saying "no".
        if not enabled:
            return False
        # get_or_create rather than create: two first-time enables race, and the loser of
        # the one-to-one constraint would answer 500 for a workflow that is now on.
        # nosemgrep: idor-lookup-without-team - team scope is enforced by TeamScopedManager
        row, created = HogFlowOptimization.objects.get_or_create(hog_flow_id=hog_flow_id, defaults={"enabled": True})
        if not created and not row.enabled:
            row.enabled = True
            row.save(update_fields=["enabled"])
            return True
        return created
    # Off keeps the row: how many tried this and stopped is a rollout question.
    if row.enabled == enabled:
        return False
    row.enabled = enabled
    row.save(update_fields=["enabled"])
    return True
