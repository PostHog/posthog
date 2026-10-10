"""
Business logic for Wizard sessions.
"""

import logging
from functools import partial
from typing import Any

from django.db import IntegrityError, transaction

from kombu.exceptions import OperationalError

from products.wizard.backend.facade.contracts import UpsertWizardSessionInput, WizardSessionDTO
from products.wizard.backend.facade.enums import WizardSessionRunPhase
from products.wizard.backend.facade.errors import WizardSessionOwnershipError
from products.wizard.backend.logic.sessions.pubsub import publish_session_update
from products.wizard.backend.logic.sessions.serializers import to_session_dto
from products.wizard.backend.metrics import report_session_upserted
from products.wizard.backend.models import WizardSession
from products.wizard.backend.tasks.tasks import sync_wizard_event_definitions

logger = logging.getLogger(__name__)


def upsert_session(params: UpsertWizardSessionInput) -> tuple[WizardSessionDTO, bool]:
    """Upsert a session row and return (dto, created).

    Each push replaces `tasks` / `run_phase` / `event_plan` / `error`, except
    that a completed push without an event plan preserves the plan from the
    running session. The row is locked once and saved directly, because
    `update_or_create` would lock it a second time. If a concurrent push for a
    brand-new session_id inserts the row first, this push locks that row and
    updates it.
    """
    with transaction.atomic():
        session = _lock_session(params)
        created = False
        if session is None:
            try:
                with transaction.atomic():
                    # created_by is set only here so a later push for the same run can't reattribute it.
                    session = WizardSession.objects.create(
                        team_id=params.team_id,
                        session_id=params.session_id,
                        created_by_id=params.created_by_id,
                        **_session_fields(params, previous_session=None),
                    )
                created = True
            except IntegrityError:
                session = _lock_session(params)
                if session is None:
                    raise

        previous_run_phase = None if created else session.run_phase
        if not created:
            _check_owner(session, params)
            fields = _session_fields(params, previous_session=session)
            for name, value in fields.items():
                setattr(session, name, value)
            session.save(update_fields=[*fields, "updated_at"])

        if (
            previous_run_phase != WizardSessionRunPhase.COMPLETED.value
            and params.run_phase == WizardSessionRunPhase.COMPLETED
        ):
            transaction.on_commit(
                partial(_enqueue_event_definition_sync, params.team_id, params.session_id),
                robust=True,
            )
        dto = to_session_dto(session)

    report_session_upserted(previous_run_phase, dto)
    publish_session_update(dto)
    return dto, created


def _lock_session(params: UpsertWizardSessionInput) -> WizardSession | None:
    return (
        WizardSession.objects.select_for_update().filter(team_id=params.team_id, session_id=params.session_id).first()
    )


def _check_owner(session: WizardSession, params: UpsertWizardSessionInput) -> None:
    # A session belongs to the user who created it. A later push from a
    # different user would overwrite the run data while `created_by` stays
    # the original owner, so reject it. Legacy rows with a null
    # `created_by_id` predate attribution and stay updatable by anyone.
    if session.created_by_id is not None and session.created_by_id != params.created_by_id:
        raise WizardSessionOwnershipError("This wizard session belongs to a different user and can't be updated.")


def _session_fields(params: UpsertWizardSessionInput, previous_session: WizardSession | None) -> dict[str, Any]:
    event_plan = params.event_plan
    if event_plan is None and params.run_phase == WizardSessionRunPhase.COMPLETED and previous_session:
        event_plan = previous_session.event_plan

    # Monotonic within a session: the doc arrives late in the run, so a push without it
    # (an ordering race between debounced snapshots, or an older CLI) must not wipe it.
    # A new run is a new session_id, so nothing ever needs to clear the field.
    handoff_text = params.handoff_text
    if not handoff_text and previous_session:
        handoff_text = previous_session.handoff_text

    return {
        "workflow_id": params.workflow_id,
        "skill_id": params.skill_id,
        "started_at": params.started_at,
        "run_phase": params.run_phase.value,
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "status": task.status.value,
            }
            for task in params.tasks
        ],
        "event_plan": event_plan,
        "error": params.error,
        "pending_input": params.pending_input,
        "handoff_text": handoff_text,
    }


def _enqueue_event_definition_sync(team_id: int, session_id: str) -> None:
    try:
        sync_wizard_event_definitions.apply_async(
            args=(team_id, session_id),
            retry=True,
            retry_policy={"max_retries": 3, "interval_start": 0, "interval_step": 1, "interval_max": 5},
        )
    except OperationalError:
        logger.exception("Failed to enqueue event definition sync for a completed wizard session")


def get_session(team_id: int, session_id: str) -> WizardSessionDTO | None:
    instance = WizardSession.objects.select_related("created_by").filter(team_id=team_id, session_id=session_id).first()
    return to_session_dto(instance) if instance else None


def get_latest_session(team_id: int, workflow_id: str, skill_id: str | None = None) -> WizardSessionDTO | None:
    qs = WizardSession.objects.select_related("created_by").filter(team_id=team_id, workflow_id=workflow_id)
    if skill_id:
        qs = qs.filter(skill_id=skill_id)
    # created_at breaks ties on equal (client-supplied, second-granularity) started_at
    instance = qs.order_by("-started_at", "-created_at").first()
    return to_session_dto(instance) if instance else None


def list_sessions(
    team_id: int,
    workflow_id: str | None = None,
    skill_id: str | None = None,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> list[WizardSessionDTO]:
    """List sessions for a team, ordered by `started_at` desc.

    `offset`/`limit` are applied at the SQL layer (LIMIT/OFFSET) so the read
    cost stays bounded regardless of how many sessions the team has. The view
    layer should always pass a `limit`.
    """
    qs = WizardSession.objects.select_related("created_by").filter(team_id=team_id)
    if workflow_id:
        qs = qs.filter(workflow_id=workflow_id)
    if skill_id:
        qs = qs.filter(skill_id=skill_id)
    # created_at breaks ties on equal (client-supplied, second-granularity) started_at
    qs = qs.order_by("-started_at", "-created_at")
    if limit is not None:
        qs = qs[offset : offset + limit]
    elif offset:
        qs = qs[offset:]
    return [to_session_dto(instance) for instance in qs]
