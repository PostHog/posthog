"""Turns Customer.io automations into draft workflows, checked the way the create endpoint checks them."""

import time
from dataclasses import asdict
from typing import Any, cast
from uuid import UUID

from django.db import IntegrityError, transaction

import structlog
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.dataclasses import frozen
from posthog.event_usage import EventSource
from posthog.models import Team, User
from posthog.permissions import get_authenticator_scopes
from posthog.scopes import scopes_not_covered

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.workflows.backend.facade.activity import log_workflow_activity
from products.workflows.backend.facade.contracts import (
    CampaignSource,
    ImageBudget,
    ImportNote,
    ImportOptions,
    PreviousImport,
    SnippetRoom,
    WorkflowActor,
    WorkflowStale,
)
from products.workflows.backend.facade.enums import HogFlowState, WorkflowImportNoteLevel
from products.workflows.backend.facade.workflow_imports import (
    import_content,
    previous_import,
    record_import,
    rehost_images,
    translate_campaign,
)
from products.workflows.backend.facade.writes import create_workflow, defer_hog_flow_reloads, update_workflow
from products.workflows.backend.presentation.views.data_suggestion_drafts import checked_draft

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
    request: Request,
) -> ImportRun:
    deadline = time.monotonic() + _REQUEST_SECONDS
    sources = [_campaign_source(payload) for payload in payloads]
    context = _RequestContext(
        request=request,
        access=UserAccessControl(user=user, team=team),
        previous={source_id: previous_import(team, source_id) for source_id in {_source_id(s) for s in sources}},
        snippet_room=SnippetRoom(),
    )
    content = import_content(
        team.id, sources, options, sender_identities, segments, deadline, _left_alone(team, context)
    )
    budget = ImageBudget(deadline=deadline, can_upload=_can_upload_media(request, context.access))
    with defer_hog_flow_reloads():
        results = [
            import_campaign(
                team,
                user,
                source,
                content.options,
                dry_run,
                content.fetch_notes.get(_source_id(source), ()),
                context,
                budget,
            )
            for source in content.sources
        ]
    return ImportRun(results=results, content_fetched=content.fetched)


# The import runs inside the request, so everything it reads from Customer.io shares one time limit.
_REQUEST_SECONDS = 60


@frozen
class _RequestContext:
    """What every automation in one import request shares."""

    request: Request
    access: UserAccessControl
    # The earlier import of each automation in the request, read once for both eligibility checks.
    previous: dict[str, PreviousImport]
    snippet_room: SnippetRoom


def _source_id(source: CampaignSource) -> str:
    return str(source.campaign.get("id"))


def _left_alone(team: Team, context: _RequestContext) -> frozenset[str]:
    """The ids of automations whose earlier import the user can't change, either way `import_campaign` skips them."""
    return frozenset(
        source_id
        for source_id, previous in context.previous.items()
        if previous.hog_flow_id is not None
        and (not previous.hog_flow_is_draft or not _can_edit(context.access, team, previous))
    )


def _campaign_source(payload: dict[str, Any]) -> CampaignSource:
    templates = payload.get("templates") or {}
    if isinstance(templates, list):
        templates = {str(template.get("id")): template for template in templates}
    return CampaignSource(
        campaign=payload["campaign"],
        actions=payload["actions"],
        templates={str(key): value for key, value in templates.items()},
    )


def import_campaign(
    team: Team,
    user: User,
    source: CampaignSource,
    options: ImportOptions,
    dry_run: bool,
    extra_notes: tuple[ImportNote, ...],
    context: _RequestContext,
    image_budget: ImageBudget,
) -> dict[str, Any]:
    """Imports one Customer.io automation, or previews it, and returns its result in the response shape."""
    try:
        translated = translate_campaign(source, options, context.snippet_room)
    except (ValueError, TypeError, AttributeError, KeyError, IndexError, RecursionError) as error:
        logger.info("workflows.import.unreadable_campaign", team_id=team.id, error=type(error).__name__)
        return {
            "source_id": _source_id(source),
            "name": str(source.campaign.get("name") or ""),
            "workflow_id": None,
            "notes": [asdict(note) for note in extra_notes],
            "validation_errors": [
                "Customer.io sent a value PostHog could not read, such as a delay that is not a number. "
                "Check the automation in Customer.io and import it again."
            ],
            "status": "failed",
        }
    result: dict[str, Any] = {
        "source_id": translated.source_id,
        "name": translated.name,
        "workflow_id": None,
        "notes": [asdict(note) for note in (*extra_notes, *translated.notes)],
        "validation_errors": [],
    }
    previous = context.previous.get(translated.source_id) or previous_import(team, translated.source_id)
    # Checked before images are copied, so a workflow the import leaves alone costs no downloads.
    if previous.hog_flow_id is not None and not _can_edit(context.access, team, previous):
        return _skipped(
            result,
            previous.hog_flow_id,
            "You can't edit the workflow an earlier import of this automation created, so it was left unchanged.",
        )
    if previous.hog_flow_id is not None and not previous.hog_flow_is_draft:
        return _skipped(result, previous.hog_flow_id, _NO_LONGER_DRAFT)
    # Checked before images are copied too, so a draft that can't save costs no downloads.
    validated, errors = _validated_draft(team, translated.workflow, context.request)
    if validated is None:
        return {**result, "status": "failed", "validation_errors": errors}
    rehosted = rehost_images(team, user, translated.workflow, dry_run, image_budget)
    notes = (*extra_notes, *translated.notes, *rehosted.notes)
    result["notes"] = [asdict(note) for note in notes]
    if dry_run:
        replaces = str(previous.hog_flow_id) if previous.hog_flow_id is not None else None
        return {**result, "status": "preview", "workflow_id": replaces}
    if rehosted.workflow is not translated.workflow:
        validated, errors = _validated_draft(team, rehosted.workflow, context.request)
        if validated is None:
            return {**result, "status": "failed", "validation_errors": errors}
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


def _can_upload_media(request: Request, access: UserAccessControl) -> bool:
    # Copying images writes to the media library, so the caller needs the same access as an upload there.
    scopes = get_authenticator_scopes(getattr(request, "successful_authenticator", None))
    if scopes is not None and "*" not in scopes and scopes_not_covered(scopes, ["uploaded_media:write"]):
        return False
    return access.check_access_level_for_resource("uploaded_media", "editor")


def _can_edit(access: UserAccessControl, team: Team, previous: PreviousImport) -> bool:
    ref = ObjectAccessRef(
        resource="hog_flow",
        id=str(previous.hog_flow_id),
        team_id=team.id,
        created_by_id=previous.hog_flow_created_by_id,
    )
    return access.check_access_level_for_ref(ref, "editor")


def _validated_draft(team: Team, workflow: dict[str, Any], request: Request) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        return checked_draft(team, workflow, EventSource.API, request), []
    except ValidationError as error:
        logger.info("workflows.import.invalid_workflow", team_id=team.id, errors=str(error.detail)[:500])
        return None, _flatten_errors(error.detail)


def _flatten_errors(detail: Any, prefix: str = "") -> list[str]:
    if isinstance(detail, dict):
        return [message for key, value in detail.items() for message in _flatten_errors(value, f"{prefix}{key}.")]
    if isinstance(detail, list):
        return [message for value in detail for message in _flatten_errors(value, prefix)]
    return [f"{prefix.rstrip('.')}: {detail}" if prefix else str(detail)]
