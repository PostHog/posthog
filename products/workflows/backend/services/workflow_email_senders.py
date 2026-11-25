from collections.abc import Iterator, Mapping
from typing import Any

from django.db.models import Q

import structlog
import posthoganalytics
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.tasks.email import send_workflow_email_sender_unusable

from products.workflows.backend.facade.contracts import UnusableEmailSender, UnusableEmailStep
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.sandbox_email.provisioning import own_sender_verification

logger = structlog.get_logger(__name__)

SENDER_UNUSABLE_NOTICE_FLAG = "workflows-sender-unusable-notice"

_PAGE_SIZE = 500

sender_unusable_notice_failures_total = Counter(
    "workflow_email_sender_unusable_notice_failures_total",
    "Projects or notices the daily unusable email sender check could not finish, by the step that failed.",
    labelnames=["step"],
)

_HAS_EMAIL_STEP = Q(actions__contains=[{"type": "function_email"}]) | Q(
    actions__contains=[{"config": {"template_id": "template-email"}}]
)


@frozen
class WorkflowWithUnusableSenders:
    id: str
    name: str
    created_by_id: int | None
    steps: tuple[UnusableEmailStep, ...]

    @property
    def sender_ids(self) -> list[str | None]:
        ids = {sender.sender_id for step in self.steps for sender in step.senders}
        return sorted(ids, key=lambda sender_id: (sender_id is None, sender_id or ""))


def email_step_sender_ids(action: dict[str, Any]) -> list[str | None]:
    config = action.get("config") or {}
    if action.get("type") != "function_email" and config.get("template_id") != "template-email":
        return []
    email_input = (config.get("inputs") or {}).get("email")
    value = email_input.get("value") if isinstance(email_input, dict) else None
    sender = value.get("from") if isinstance(value, dict) else None
    if not isinstance(sender, dict):
        return []
    # The send path picks from the rotation alone when one is set.
    rotation = sender.get("integrationIds")
    configured = rotation if isinstance(rotation, list) and rotation else [sender.get("integrationId")]
    # JSON can carry an id as 42.0, which the send path reads as sender 42.
    configured = [int(value) if isinstance(value, float) and value.is_integer() else value for value in configured]
    # The send path loads a sender only from a JSON number, so an id stored as text, such as "42", names none.
    return [
        str(sender_id) if isinstance(sender_id, int) else None
        for sender_id in configured
        if sender_id not in (None, "")
    ]


def unusable_email_steps(actions: list[dict[str, Any]], *, team_id: int) -> list[UnusableEmailStep]:
    """The email steps among `actions` with a sender that is deleted or whose domain isn't verified yet."""
    if not any(email_step_sender_ids(action) for action in actions):
        return []
    return _unusable_steps(actions, own_sender_verification(team_id))


def live_workflows_with_unusable_senders(team_id: int) -> list[WorkflowWithUnusableSenders]:
    flows = list(
        HogFlow.objects.filter(_HAS_EMAIL_STEP, team_id=team_id, status=HogFlow.State.ACTIVE)
        .order_by("id")
        .values("id", "name", "actions", "created_by_id")
    )
    if not flows:
        return []
    verification = own_sender_verification(team_id)
    workflows = []
    for flow in flows:
        if steps := _unusable_steps(flow["actions"] or [], verification):
            workflows.append(
                WorkflowWithUnusableSenders(
                    id=str(flow["id"]), name=flow["name"] or "", created_by_id=flow["created_by_id"], steps=tuple(steps)
                )
            )
    return workflows


def notify_unusable_email_senders() -> None:
    """Email each project in the rollout about its live workflows with an email sender that cannot send.

    Projects outside the rollout get a log line listing those workflows instead.
    """
    held_back = undecided = failed = 0
    for team_id in _teams_with_live_email_workflows():
        try:
            outcome = _notify_team(team_id)
        except Exception as error:
            failed += 1
            sender_unusable_notice_failures_total.labels(step="project").inc()
            logger.exception("workflow_email_sender_unusable_team_failed", team_id=team_id)
            capture_exception(error, {"team_id": team_id})
            continue
        held_back += outcome.held_back
        undecided += outcome.undecided
    logger.info("workflow_email_sender_unusable_shadow", held_back=held_back, undecided=undecided, failed=failed)


@frozen
class _TeamOutcome:
    held_back: int = 0
    undecided: int = 0


def _notify_team(team_id: int) -> _TeamOutcome:
    workflows = live_workflows_with_unusable_senders(team_id)
    if not workflows:
        return _TeamOutcome()
    rolled_out = _rolled_out(team_id)
    if rolled_out is None:
        return _TeamOutcome(undecided=len(workflows))
    if not rolled_out:
        logger.info(
            "workflow_email_sender_unusable_held_back",
            team_id=team_id,
            workflows=[{"workflow_id": workflow.id, "sender_ids": workflow.sender_ids} for workflow in workflows],
        )
        return _TeamOutcome(held_back=len(workflows))
    for workflow in workflows:
        _queue_sender_unusable_email(team_id, workflow)
    return _TeamOutcome()


def _unusable_steps(actions: list[dict[str, Any]], verification: Mapping[str, bool]) -> list[UnusableEmailStep]:
    steps = []
    for action in actions:
        senders = tuple(
            UnusableEmailSender(sender_id=sender_id, unverified=sender_id in verification)
            for sender_id in email_step_sender_ids(action)
            if sender_id is None or not verification.get(sender_id)
        )
        if senders:
            steps.append(UnusableEmailStep(name=action.get("name") or "Email", senders=senders))
    return steps


def _teams_with_live_email_workflows() -> Iterator[int]:
    after_team_id = 0
    while page := list(
        HogFlow.objects.filter(_HAS_EMAIL_STEP, status=HogFlow.State.ACTIVE, team_id__gt=after_team_id)
        .order_by("team_id")
        .values_list("team_id", flat=True)
        .distinct()[:_PAGE_SIZE]
    ):
        yield from page
        after_team_id = page[-1]


def _rolled_out(team_id: int) -> bool | None:
    team = Team.objects.only("uuid", "organization_id").get(id=team_id)
    organization_id = str(team.organization_id)
    return posthoganalytics.feature_enabled(
        SENDER_UNUSABLE_NOTICE_FLAG,
        str(team.uuid),
        groups={"organization": organization_id, "project": str(team_id)},
        group_properties={"organization": {"id": organization_id}, "project": {"id": str(team_id)}},
        send_feature_flag_events=False,
    )


def _queue_sender_unusable_email(team_id: int, workflow: WorkflowWithUnusableSenders) -> None:
    try:
        send_workflow_email_sender_unusable.delay(
            team_id=team_id,
            hog_flow_id=workflow.id,
            hog_flow_name=workflow.name,
            created_by_id=workflow.created_by_id,
            steps=[
                {
                    "name": step.name,
                    "missing": any(not sender.unverified for sender in step.senders),
                    "unverified": any(sender.unverified for sender in step.senders),
                }
                for step in workflow.steps
            ],
            sender_ids=workflow.sender_ids,
        )
    except Exception as error:
        sender_unusable_notice_failures_total.labels(step="dispatch").inc()
        logger.exception("workflow_email_sender_unusable_dispatch_failed", team_id=team_id, workflow_id=workflow.id)
        capture_exception(error, {"team_id": team_id, "workflow_id": workflow.id})
