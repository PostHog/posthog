"""The one call another product makes to have an agent look at one of its records.

The same call starts new work and re-addresses old work. The caller names an agent and an entity
and passes no content, because Self-driving loads the entity itself through the loader the owning
product registered.
"""

from __future__ import annotations

from datetime import timedelta
from functools import partial

from django.db import IntegrityError, transaction
from django.utils import timezone

import structlog

from posthog.models import Team

from products.signals.backend.agent_run_passes import (
    REASON_STALE,
    REASON_WORKFLOW_START_FAILED,
    PassOutcome,
    agent_scout_for,
    complete_pass,
)
from products.signals.backend.agent_run_types import (
    AgentEntity,
    AgentRunHandle,
    AgentRunOutcome,
    AgentRunRequestState,
    AgentRunResult,
)
from products.signals.backend.facade.agent_sources import deliver_agent_run_result, get_agent_source, load_agent_entity
from products.signals.backend.models import SignalAgentRun, SignalSourceConfig
from products.signals.backend.scout_harness.limits import STALE_RUN_CUTOFF_S
from products.signals.backend.scout_harness.run_gates import check_fleet_gates, check_spend_gates

logger = structlog.get_logger(__name__)

REASON_UNKNOWN_SOURCE = "unknown_source"
REASON_TEAM_NOT_FOUND = "team_not_found"
REASON_CHILD_ENVIRONMENT = "child_environment"
REASON_SOURCE_DISABLED = "source_disabled"
REASON_AI_PROCESSING_NOT_APPROVED = "ai_processing_not_approved"
REASON_ENTITY_NOT_FOUND = "entity_not_found"


def _rejected(reason_code: str) -> AgentRunHandle:
    return AgentRunHandle(state=AgentRunRequestState.REJECTED, run_id=None, reason_code=reason_code)


def _entity_runs(team_id: int, agent: str, entity: AgentEntity):
    return SignalAgentRun.objects.for_team(team_id, canonical=True).filter(
        agent=agent, source_product=entity.product, source_type=entity.type, source_id=entity.id
    )


def _join_active_pass(
    *, team_id: int, agent: str, entity: AgentEntity, reason: str | None, note: str, content_hash: str
) -> str | None:
    """Attach the request to the entity's active pass, and return that pass's id.

    Returns None when no pass is active. An active pass that outlived any possible run is a pass
    whose workflow died, so it is failed here and does not count.
    """
    with transaction.atomic():
        active = (
            _entity_runs(team_id, agent, entity)
            .select_for_update()
            .filter(status__in=SignalAgentRun.ACTIVE_STATUSES)
            .first()
        )
        if active is None:
            return None
        if timezone.now() - active.created_at > timedelta(seconds=STALE_RUN_CUTOFF_S):
            # Without `look_again` the stale pass queues no successor. The request that found it starts one.
            active.look_again = False
            active.save(update_fields=["look_again", "updated_at"])
            completed = complete_pass(
                run_id=str(active.id), outcome=PassOutcome(outcome=AgentRunOutcome.FAILED, reason_code=REASON_STALE)
            )
            if completed is not None:
                transaction.on_commit(partial(_deliver_result, completed.result))
            return None
        # A pass with no hash has not read the entity yet, so it reads what this request saw or newer.
        if reason is None and not note and active.content_hash in (None, content_hash):
            return str(active.id)
        if active.look_again:
            active.reason = reason if reason is not None else active.reason
            active.note = note or active.note
        else:
            # From here the row's reason and note belong to the waiting request, not to the active pass.
            active.reason = reason
            active.note = note
        active.look_again = True
        active.save(update_fields=["look_again", "reason", "note", "updated_at"])
        return str(active.id)


def _deliver_result(result: AgentRunResult) -> None:
    """Hand a result to the owning product. A handler that raises must not undo a settled pass."""
    try:
        deliver_agent_run_result(result)
    except Exception:
        logger.exception("signals_agent_run_result_delivery_failed", run_id=result.run_id)


def fail_pass(run_id: str, reason_code: str) -> None:
    """End a pass that cannot run, and tell the owning product. Never raises."""
    try:
        completed = complete_pass(
            run_id=run_id, outcome=PassOutcome(outcome=AgentRunOutcome.FAILED, reason_code=reason_code)
        )
    except Exception:
        logger.exception("signals_agent_run_fail_pass_failed", run_id=run_id, reason_code=reason_code)
        return
    if completed is None:
        return
    _deliver_result(completed.result)
    if completed.next_run_id is not None:
        dispatch_agent_run(completed.next_run_id)


def dispatch_agent_run(run_id: str) -> None:
    """Start the workflow of a queued pass. A pass whose workflow cannot start ends as failed."""
    from products.signals.backend.temporal.agent_run import (
        start_agent_run_workflow,  # noqa: PLC0415 — keeps the Temporal workflow registry off the facade import path
    )

    try:
        start_agent_run_workflow(run_id)
    except Exception:
        logger.exception("signals_agent_run_workflow_start_failed", run_id=run_id)
        fail_pass(run_id, REASON_WORKFLOW_START_FAILED)


def _check_vocabulary(reason: str | None, requested_by: str | None) -> None:
    if reason is not None and reason not in SignalAgentRun.Reason.values:
        raise ValueError(f"Unknown agent run reason: {reason}")
    if requested_by is not None and requested_by not in SignalAgentRun.RequestedBy.values:
        raise ValueError(f"Unknown agent run requester: {requested_by}")


def _team_for_request(team_id: int, agent: str, entity: AgentEntity) -> Team | str:
    """The team the request runs for, or the reason code that refuses the request."""
    if (
        agent_scout_for(agent, entity) is None
        or get_agent_source(agent=agent, product=entity.product, type=entity.type) is None
    ):
        return REASON_UNKNOWN_SOURCE
    team = Team.objects.select_related("organization").filter(id=team_id).first()
    if team is None:
        return REASON_TEAM_NOT_FOUND
    if team.parent_team_id is not None and team.parent_team_id != team.id:
        # The lane's rows and the agent's scout run belong to a project's main environment.
        return REASON_CHILD_ENVIRONMENT
    if not SignalSourceConfig.is_source_enabled(team.id, entity.product, entity.type):
        return REASON_SOURCE_DISABLED
    if not team.organization.is_ai_data_processing_approved:
        return REASON_AI_PROCESSING_NOT_APPROVED
    return team


def request_agent_run(
    *,
    team_id: int,
    agent: str,
    entity: AgentEntity,
    reason: str | None = None,
    note: str | None = None,
    requested_by: str | None = None,
) -> AgentRunHandle:
    """Ask for one pass of `agent` over `entity`, and say at once what happened to the request.

    - `started`: a pass is queued, and its result goes to the owning product's `on_result` handler.
    - `joined`: a pass is already active. One more pass starts when it ends, however many requests joined,
      unless the request adds nothing: no reason, no note, and the active pass reads the entity as it is now.
    - `unchanged`: the entity is the same as at the last pass and the request gave no reason, so nothing runs.
    - `rejected`: nothing runs, and `reason_code` says why.

    Call it inside the caller's own transaction when the request belongs to a change the caller makes:
    the workflow starts only after that transaction commits.
    """
    _check_vocabulary(reason, requested_by)
    team = _team_for_request(team_id, agent, entity)
    if isinstance(team, str):
        return _rejected(team)

    content = load_agent_entity(team_id=team.id, agent=agent, entity=entity)
    if content is None:
        return _rejected(REASON_ENTITY_NOT_FOUND)
    note = (note or "").strip()[: SignalAgentRun.MAX_NOTE_LENGTH]

    def join() -> str | None:
        return _join_active_pass(
            team_id=team.id, agent=agent, entity=entity, reason=reason, note=note, content_hash=content.content_hash
        )

    joined_run_id = join()
    if joined_run_id is not None:
        return AgentRunHandle(state=AgentRunRequestState.JOINED, run_id=joined_run_id)

    last_pass = _entity_runs(team.id, agent, entity).order_by("-pass_number").first()
    # A failed pass read the entity and concluded nothing, so it does not make the entity unchanged.
    if (
        reason is None
        and last_pass is not None
        and last_pass.status == SignalAgentRun.Status.DONE
        and last_pass.content_hash == content.content_hash
    ):
        return AgentRunHandle(state=AgentRunRequestState.UNCHANGED, run_id=str(last_pass.id))

    # Checked last, because each refusal is recorded for billing and an unchanged entity must not record one.
    rejection = check_fleet_gates(team.id) or check_spend_gates(team)
    if rejection is not None:
        return _rejected(rejection.reason)

    try:
        with transaction.atomic():
            run = SignalAgentRun.objects.for_team(team.id, canonical=True).create(
                team_id=team.id,
                agent=agent,
                source_product=entity.product,
                source_type=entity.type,
                source_id=entity.id,
                pass_number=(last_pass.pass_number if last_pass is not None else 0) + 1,
                reason=reason,
                note=note,
                requested_by=requested_by,
            )
    except IntegrityError:
        # Another request created the active pass after the check above, and the constraint stopped this one.
        joined_run_id = join()
        if joined_run_id is None:
            raise
        return AgentRunHandle(state=AgentRunRequestState.JOINED, run_id=joined_run_id)
    transaction.on_commit(partial(dispatch_agent_run, str(run.id)))
    return AgentRunHandle(state=AgentRunRequestState.STARTED, run_id=str(run.id))
