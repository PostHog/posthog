"""Turns Customer.io automations into draft workflows, checked the way the create endpoint checks them."""

from dataclasses import asdict
from typing import Any, cast
from uuid import UUID

from django.db import IntegrityError, transaction

import structlog
from rest_framework.exceptions import ValidationError

from posthog.dataclasses import frozen
from posthog.event_usage import EventSource
from posthog.models import Team, User

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.workflows.backend.facade.activity import log_workflow_activity
from products.workflows.backend.facade.contracts import (
    CampaignSource,
    ImportNote,
    ImportOptions,
    PreviousImport,
    WorkflowActor,
    WorkflowStale,
)
from products.workflows.backend.facade.enums import HogFlowState, WorkflowImportNoteLevel
from products.workflows.backend.facade.workflow_imports import (
    import_content,
    previous_import,
    record_import,
    translate_campaign,
)
from products.workflows.backend.facade.writes import create_workflow, update_workflow
from products.workflows.backend.presentation.views.graph_validation import validate_graph
from products.workflows.backend.presentation.views.hog_flow import HogFlowSerializer

logger = structlog.get_logger(__name__)


@frozen
class ImportRun:
    results: list[dict[str, Any]]
    # Whether PostHog read message content from Customer.io with the team's stored App API key.
    content_fetched: bool


def import_campaigns(
    team: Team,
    user: User,
    payloads: list[dict[str, Any]],
    options: ImportOptions,
    dry_run: bool,
    sender_identities: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> ImportRun:
    content = import_content(
        team.id, [_campaign_source(payload) for payload in payloads], options, sender_identities, segments
    )
    results = [
        import_campaign(
            team, user, source, content.options, dry_run, content.fetch_notes.get(str(source.campaign.get("id")), ())
        )
        for source in content.sources
    ]
    return ImportRun(results=results, content_fetched=content.fetched)


def _campaign_source(payload: dict[str, Any]) -> CampaignSource:
    templates = payload.get("templates") or {}
    if isinstance(templates, list):
        templates = {str(template.get("id")): template for template in templates if isinstance(template, dict)}
    return CampaignSource(
        campaign=payload["campaign"],
        actions=payload["actions"],
        templates={str(key): value for key, value in templates.items() if isinstance(value, dict)},
    )


def import_campaign(
    team: Team,
    user: User,
    source: CampaignSource,
    options: ImportOptions,
    dry_run: bool,
    extra_notes: tuple[ImportNote, ...] = (),
) -> dict[str, Any]:
    """Imports one Customer.io automation, or previews it, and returns its result in the response shape."""
    try:
        translated = translate_campaign(source, options)
    except (ValueError, TypeError) as error:
        logger.info("workflows.import.unreadable_campaign", team_id=team.id, error=type(error).__name__)
        return {
            "source_id": str(source.campaign.get("id")),
            "name": str(source.campaign.get("name") or ""),
            "workflow_id": None,
            "notes": [asdict(note) for note in extra_notes],
            "validation_errors": [
                "Customer.io sent a value PostHog could not read, such as a delay that is not a number. "
                "Check the automation in Customer.io and import it again."
            ],
            "status": "failed",
        }
    notes = (*extra_notes, *translated.notes)
    result: dict[str, Any] = {
        "source_id": translated.source_id,
        "name": translated.name,
        "workflow_id": None,
        "notes": [asdict(note) for note in notes],
        "validation_errors": [],
    }
    validated, errors = _validated_draft(team, translated.workflow)
    if validated is None:
        return {**result, "status": "failed", "validation_errors": errors}
    if dry_run:
        return {**result, "status": "preview"}

    previous = previous_import(team, translated.source_id)
    if previous.hog_flow_id is not None and not _can_edit(team, user, previous):
        return _skipped(
            result,
            previous.hog_flow_id,
            "You can't edit the workflow an earlier import of this automation created, so it was left unchanged.",
        )
    if previous.hog_flow_id is not None and not previous.hog_flow_is_draft:
        return _skipped(result, previous.hog_flow_id, _NO_LONGER_DRAFT)
    created_name: str | None = None
    try:
        with transaction.atomic():
            if previous.hog_flow_id is not None:
                # Without `status` in the payload, the update refuses a workflow someone enabled since the check above.
                update_workflow(
                    team_id=team.id,
                    user_id=user.id,
                    hog_flow_id=previous.hog_flow_id,
                    validated_data={key: value for key, value in validated.items() if key != "status"},
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
                created_name = cast("str | None", created.current.get("name"))
            record_import(
                team=team,
                user=user,
                record_id=previous.record_id,
                source_id=translated.source_id,
                name=translated.name,
                hog_flow_id=workflow_id,
                notes=notes,
            )
    except WorkflowStale:
        return _skipped(result, previous.hog_flow_id, _NO_LONGER_DRAFT)
    except IntegrityError:
        # Another request imported the same automation first, and the unique record rolled this one back.
        return {
            **result,
            "status": "failed",
            "validation_errors": ["Another import of this automation ran at the same time. Import it again."],
        }
    if status == "created":
        log_workflow_activity(
            actor=WorkflowActor(
                organization_id=team.organization_id, team_id=team.id, user=user, was_impersonated=False
            ),
            workflow_id=workflow_id,
            name=created_name,
            activity="created",
            detail_type="standard",
        )
    return {**result, "status": status, "workflow_id": str(workflow_id)}


_NO_LONGER_DRAFT = (
    "This automation was imported before and that workflow is no longer a draft, so it was left unchanged."
)


def _skipped(result: dict[str, Any], workflow_id: UUID | None, message: str) -> dict[str, Any]:
    note = ImportNote(level=WorkflowImportNoteLevel.APPROXIMATED, message=message)
    return {**result, "status": "skipped", "workflow_id": str(workflow_id), "notes": [asdict(note)]}


def _can_edit(team: Team, user: User, previous: PreviousImport) -> bool:
    ref = ObjectAccessRef(
        resource="hog_flow",
        id=str(previous.hog_flow_id),
        team_id=team.id,
        created_by_id=previous.hog_flow_created_by_id,
    )
    return UserAccessControl(user=user, team=team).check_access_level_for_ref(ref, "editor")


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
