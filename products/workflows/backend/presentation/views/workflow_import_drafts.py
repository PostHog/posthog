"""Turns Customer.io automations into draft workflows, checked the way the create endpoint checks them."""

import time
import dataclasses
from dataclasses import asdict
from typing import Any, cast
from uuid import UUID

from django.db import IntegrityError, connection, transaction

import structlog
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.dataclasses import frozen
from posthog.event_usage import EventSource
from posthog.helpers.impersonation import is_impersonated
from posthog.models import Team, User
from posthog.permissions import get_authenticator_scopes
from posthog.scopes import scopes_not_covered

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.cohorts.backend.facade.api import (
    create_cohort_from_filters,
    find_cohort_by_description_prefix,
    realtime_cohorts_available,
)
from products.workflows.backend.facade.activity import log_workflow_activity
from products.workflows.backend.facade.contracts import (
    CampaignSource,
    ImageBudget,
    ImportContent,
    ImportNote,
    ImportOptions,
    ImportSegment,
    PreviousImport,
    SnippetRoom,
    WorkflowActor,
    WorkflowStale,
)
from products.workflows.backend.facade.enums import (
    HogFlowState,
    WorkflowImportNoteLevel,
    WorkflowImportSegmentCohortStatus as SegmentCohortStatus,
)
from products.workflows.backend.facade.workflow_imports import (
    import_content,
    previous_import,
    record_import,
    referenced_segments,
    rehost_images,
    segment_cohort_filters,
    translate_campaign,
)
from products.workflows.backend.facade.writes import create_workflow, defer_hog_flow_reloads, update_workflow
from products.workflows.backend.presentation.views.data_suggestion_drafts import checked_draft
from products.workflows.backend.presentation.views.hog_flow import _cohort_conditions_rolled_out

logger = structlog.get_logger(__name__)


@frozen
class ImportRun:
    results: list[dict[str, Any]]
    # Whether PostHog read message content from Customer.io with the team's stored App API key.
    content_fetched: bool
    # What happened to each Customer.io segment the automations check, in the response shape.
    segment_cohorts: list[dict[str, Any]]


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
    left_alone = _left_alone(team, context)
    content = import_content(team.id, sources, options, sender_identities, segments, deadline, left_alone)
    converted = _convert_segments(team, user, content, dry_run, context, left_alone)
    budget = ImageBudget(deadline=deadline, can_upload=_can_upload_media(request, context.access))
    with defer_hog_flow_reloads():
        results = [
            import_campaign(
                team,
                user,
                source,
                converted.options,
                dry_run,
                (*content.fetch_notes.get(_source_id(source), ()), *converted.notes.get(_source_id(source), ())),
                context,
                budget,
            )
            for source in content.sources
        ]
    return ImportRun(results=results, content_fetched=content.fetched, segment_cohorts=converted.outcomes)


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


@frozen
class _ConvertedSegments:
    options: ImportOptions
    # Per automation id, what happened to the segments it checks.
    notes: dict[str, tuple[ImportNote, ...]]
    outcomes: list[dict[str, Any]]


_STATIC_SEGMENT_TYPES = {"static", "manual"}
MAX_COHORT_NAME_LENGTH = 400
MAX_NEW_COHORTS_PER_IMPORT = 50
_UNREADABLE = (ValueError, TypeError, AttributeError, KeyError, IndexError, RecursionError)


def _segment_marker(segment_id: str) -> str:
    # Starts the description of every cohort the import makes, so importing again finds the cohort instead of
    # making a second one. The full stop keeps segment 1 from matching segment 15.
    return f"Imported from Customer.io segment {segment_id}."


def _convert_segments(
    team: Team,
    user: User,
    content: ImportContent,
    dry_run: bool,
    context: _RequestContext,
    left_alone: frozenset[str],
) -> _ConvertedSegments:
    """Turns the dynamic segments the automations check into realtime cohorts, built from the segments' rules.

    Only segments whose rules all translate become cohorts. A cohort an earlier import made is used again.
    """
    options = content.options
    referenced: dict[str, list[str]] = {}
    for source in content.sources:
        source_id = _source_id(source)
        if source_id in left_alone:
            continue
        try:
            segment_ids = referenced_segments(source.campaign, source.actions)
        except _UNREADABLE:
            continue
        for segment_id in segment_ids:
            segment = options.segments.get(segment_id)
            if (
                segment_id in options.segment_cohorts
                or segment is None
                or segment.conditions is None
                or segment.type in _STATIC_SEGMENT_TYPES
            ):
                continue
            referenced.setdefault(segment_id, []).append(source_id)
    if not referenced:
        return _ConvertedSegments(options=options, notes={}, outcomes=[])

    mapped = dict(options.segment_cohorts)
    pending: dict[str, str] = {}
    notes: dict[str, list[ImportNote]] = {}
    outcomes: list[dict[str, Any]] = []
    creation = _CohortCreation(team=team, user=user, context=context, dry_run=dry_run)
    for segment_id, source_ids in referenced.items():
        segment = options.segments[segment_id]
        result = creation.convert(segment_id, segment)
        if result.status in (SegmentCohortStatus.CREATED, SegmentCohortStatus.REUSED) and result.cohort_id is not None:
            mapped[segment_id] = result.cohort_id
        elif result.status == SegmentCohortStatus.WOULD_CREATE:
            pending[segment_id] = _cohort_name(segment_id, segment)
        outcomes.append(
            {
                "segment_id": segment_id,
                "segment_name": segment.name,
                "status": result.status.value,
                "cohort_id": result.cohort_id,
                "reason": result.reason,
            }
        )
        if result.note is not None:
            for source_id in source_ids:
                notes.setdefault(source_id, []).append(result.note)

    return _ConvertedSegments(
        options=dataclasses.replace(options, segment_cohorts=mapped, pending_segment_cohorts=pending),
        notes={source_id: tuple(source_notes) for source_id, source_notes in notes.items()},
        outcomes=outcomes,
    )


def _cohort_name(segment_id: str, segment: ImportSegment) -> str:
    return (segment.name or f"Customer.io segment {segment_id}")[:MAX_COHORT_NAME_LENGTH]


@frozen
class _SegmentOutcome:
    status: SegmentCohortStatus
    cohort_id: int | None = None
    note: ImportNote | None = None
    reason: str | None = None


class _CohortCreation:
    def __init__(self, team: Team, user: User, context: _RequestContext, dry_run: bool) -> None:
        self.team, self.user, self.context, self.dry_run = team, user, context, dry_run
        # Why cohorts can't be used or created, each worked out once per request, when the first segment needs it.
        self.unavailable: str | None = None
        self.blocked: str | None = None
        self.new_cohorts = 0

    def convert(self, segment_id: str, segment: ImportSegment) -> _SegmentOutcome:
        label = f'"{segment.name}" ({segment_id})' if segment.name else segment_id
        if self.unavailable is None:
            self.unavailable = _cohort_triggers_unavailable(self.team, self.user)
        if self.unavailable:
            return _not_converted(label, self.unavailable)
        # Two imports of the same segment at once would otherwise both miss the lookup and make two cohorts.
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [f"workflow-import-segment-cohort:{self.team.id}:{segment_id}"],
            )
            return self._reuse_or_create(segment_id, segment, label)

    def _reuse_or_create(self, segment_id: str, segment: ImportSegment, label: str) -> _SegmentOutcome:
        existing = find_cohort_by_description_prefix(team_id=self.team.id, prefix=_segment_marker(segment_id))
        if existing is not None:
            if not existing.is_realtime:
                return _not_converted(
                    label,
                    f"The cohort {existing.id} that an earlier import made from it no longer "
                    "updates in real time, so the workflow doesn't use it.",
                    existing.id,
                )
            return _SegmentOutcome(
                status=SegmentCohortStatus.REUSED,
                cohort_id=existing.id,
                note=ImportNote(
                    level=WorkflowImportNoteLevel.APPROXIMATED,
                    message=f"Uses the cohort {existing.id} that an earlier import made from "
                    f"Customer.io segment {label}. Check it still matches the segment.",
                ),
            )

        translated = segment_cohort_filters(segment.conditions)
        if translated.filters is None:
            return _not_converted(
                label,
                "No cohort condition matches these rules exactly: " + "; ".join(translated.untranslated) + ". "
                "Create a realtime cohort for it by hand, then use that cohort in the workflow.",
            )

        if self.blocked is None:
            self.blocked = _cohort_creation_blocked(self.context)
        if self.blocked:
            return _not_converted(label, self.blocked)
        if self.new_cohorts >= MAX_NEW_COHORTS_PER_IMPORT:
            return _not_converted(
                label,
                f"One import creates at most {MAX_NEW_COHORTS_PER_IMPORT} cohorts. Import again to convert the rest.",
            )
        self.new_cohorts += 1
        if self.dry_run:
            return _SegmentOutcome(
                status=SegmentCohortStatus.WOULD_CREATE,
                note=ImportNote(
                    level=WorkflowImportNoteLevel.APPROXIMATED,
                    message=f'Importing for real creates the realtime cohort "{_cohort_name(segment_id, segment)}" '
                    f"from the rules of Customer.io segment {label}, and uses it wherever this automation checks "
                    "the segment.",
                ),
            )

        try:
            created = create_cohort_from_filters(
                team_id=self.team.id,
                user_id=self.user.id,
                was_impersonated=is_impersonated(self.context.request),
                name=_cohort_name(segment_id, segment),
                description=f"{_segment_marker(segment_id)} Made by the workflow import from the segment's rules.",
                filters=translated.filters,
            )
        except ValueError as error:
            logger.info("workflows.import.cohort_not_created", team_id=self.team.id, errors=str(error)[:500])
            return _not_converted(label, f"PostHog could not save a cohort with its rules: {error}")
        if not created.is_realtime:
            return _not_converted(
                label,
                f'The cohort "{created.name}" ({created.id}) made from it can\'t update in real time, so the '
                "workflow doesn't use it.",
                created.id,
            )
        return _SegmentOutcome(
            status=SegmentCohortStatus.CREATED,
            cohort_id=created.id,
            note=ImportNote(
                level=WorkflowImportNoteLevel.APPROXIMATED,
                message=f'Created the realtime cohort "{created.name}" ({created.id}) from the rules of Customer.io '
                f"segment {label}. Check its conditions before enabling.",
            ),
        )


def _not_converted(label: str, reason: str, cohort_id: int | None = None) -> _SegmentOutcome:
    return _SegmentOutcome(
        status=SegmentCohortStatus.NOT_CONVERTED,
        cohort_id=cohort_id,
        reason=reason,
        note=ImportNote(
            level=WorkflowImportNoteLevel.NEEDS_INPUT,
            message=f"Customer.io segment {label} was not turned into a cohort. {reason}",
        ),
    )


def _cohort_triggers_unavailable(team: Team, user: User) -> str:
    """Why workflows here can't use realtime cohorts, or an empty string when they can."""
    # The draft's checks refuse a cohort trigger without both, so a cohort used anyway would only fail the draft.
    if not realtime_cohorts_available(team_id=team.id):
        return "Realtime cohorts aren't available in this project yet."
    if not _cohort_conditions_rolled_out(user, str(team.organization_id)):
        return "Cohort triggers aren't available in this organization yet."
    return ""


def _cohort_creation_blocked(context: _RequestContext) -> str:
    """Why this caller can't create cohorts, or an empty string when they can."""
    # Creating a cohort is a write outside the workflow, so the caller needs the access the cohort API asks for.
    scopes = get_authenticator_scopes(getattr(context.request, "successful_authenticator", None))
    if scopes is not None and "*" not in scopes and scopes_not_covered(scopes, ["cohort:write"]):
        return "Creating a cohort needs the cohort:write scope, which this API key or sign-in doesn't have."
    if not context.access.check_access_level_for_resource("cohort", "editor"):
        return "You need edit access to cohorts to create one."
    return ""


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
