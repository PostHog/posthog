"""Turns Customer.io automations into draft workflows, checked the way the create endpoint checks them."""

from dataclasses import asdict
from typing import Any, cast
from uuid import UUID

import structlog
from rest_framework.exceptions import ValidationError

from posthog.event_usage import EventSource
from posthog.models import Team, User

from products.workflows.backend.facade.activity import log_workflow_activity
from products.workflows.backend.facade.contracts import CampaignSource, ImportNote, ImportOptions, WorkflowActor
from products.workflows.backend.facade.enums import HogFlowState, WorkflowImportNoteLevel
from products.workflows.backend.facade.workflow_imports import previous_import, record_import, translate_campaign
from products.workflows.backend.facade.writes import create_workflow, update_workflow
from products.workflows.backend.presentation.views.graph_validation import validate_graph
from products.workflows.backend.presentation.views.hog_flow import HogFlowSerializer

logger = structlog.get_logger(__name__)


def import_campaign(
    team: Team, user: User, payload: dict[str, Any], options: ImportOptions, dry_run: bool
) -> dict[str, Any]:
    """Imports one Customer.io automation, or previews it, and returns its result in the response shape."""
    templates = payload.get("templates") or {}
    if isinstance(templates, list):
        templates = {str(template.get("id")): template for template in templates if isinstance(template, dict)}
    source = CampaignSource(
        campaign=payload["campaign"],
        actions=payload["actions"],
        templates={str(key): value for key, value in templates.items() if isinstance(value, dict)},
    )
    translated = translate_campaign(source, options)
    result: dict[str, Any] = {
        "source_id": translated.source_id,
        "name": translated.name,
        "workflow_id": None,
        "notes": [asdict(note) for note in translated.notes],
        "validation_errors": [],
    }
    validated, errors = _validated_draft(team, translated.workflow)
    if validated is None:
        return {**result, "status": "failed", "validation_errors": errors}
    if dry_run:
        return {**result, "status": "preview"}

    previous = previous_import(team, translated.source_id)
    if previous.hog_flow_id is not None and not previous.hog_flow_is_draft:
        # Someone enabled the earlier import, so a re-import must not change what is running.
        skipped = ImportNote(
            level=WorkflowImportNoteLevel.APPROXIMATED,
            message="This automation was imported before and that workflow is no longer a draft, so it was left "
            "unchanged.",
        )
        return {**result, "status": "skipped", "workflow_id": str(previous.hog_flow_id), "notes": [asdict(skipped)]}
    if previous.hog_flow_id is not None:
        update_workflow(
            team_id=team.id,
            user_id=user.id,
            hog_flow_id=previous.hog_flow_id,
            validated_data=validated,
            route_to_draft=False,
            base_updated_at=None,
            base_live_updated_at=None,
            includes_staged_draft=False,
            validated_status=HogFlowState.DRAFT.value,
        )
        workflow_id, status = previous.hog_flow_id, "updated"
    else:
        created = create_workflow(team_id=team.id, user_id=user.id, validated_data=validated)
        workflow_id, status = cast(UUID, created.current["id"]), "created"
        log_workflow_activity(
            actor=WorkflowActor(
                organization_id=team.organization_id, team_id=team.id, user=user, was_impersonated=False
            ),
            workflow_id=workflow_id,
            name=cast("str | None", created.current.get("name")),
            activity="created",
            detail_type="standard",
        )
    record_import(
        team=team,
        user=user,
        record_id=previous.record_id,
        source_id=translated.source_id,
        name=translated.name,
        hog_flow_id=workflow_id,
        notes=translated.notes,
    )
    return {**result, "status": status, "workflow_id": str(workflow_id)}


def _validated_draft(team: Team, workflow: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """The draft as the create endpoint would store it, or the reasons it would reject it."""
    serializer = HogFlowSerializer(
        data={**workflow, "status": HogFlowState.DRAFT.value},
        context={"team_id": team.id, "get_team": lambda: team, "is_draft": True, "event_source": EventSource.API},
    )
    try:
        validate_graph(workflow["actions"], workflow["edges"])
        serializer.is_valid(raise_exception=True)
    except ValidationError as error:
        logger.info("workflows.import.invalid_workflow", team_id=team.id, errors=str(error.detail)[:500])
        return None, _flatten_errors(error.detail)
    return dict(serializer.validated_data), []


def _flatten_errors(detail: Any, prefix: str = "") -> list[str]:
    if isinstance(detail, dict):
        return [message for key, value in detail.items() for message in _flatten_errors(value, f"{prefix}{key}.")]
    if isinstance(detail, list):
        return [message for value in detail for message in _flatten_errors(value, prefix)]
    return [f"{prefix.rstrip('.')}: {detail}" if prefix else str(detail)]
