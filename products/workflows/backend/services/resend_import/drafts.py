"""Saves a translated Resend automation as a draft workflow."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import structlog

from posthog.models import Team, User

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.cdp.backend.flag_gated_templates import hidden_gated_template_ids
from products.cohorts.backend.facade.api import CohortRef, create_empty_static_cohort, find_cohort_ref_by_description
from products.workflows.backend.facade.contracts import ImportedEmail, ImportedStepEmail, ProviderAutomationResult
from products.workflows.backend.facade.enums import WorkflowImportSource
from products.workflows.backend.services.customerio_import.service import previous_import
from products.workflows.backend.services.resend_import.translator import (
    SegmentCohort,
    TranslationContext,
    translate_automation,
)

logger = structlog.get_logger(__name__)

# Resend's automation API isn't typed, so a field can hold a value of a type the translator doesn't expect.
_UNREADABLE = (ValueError, TypeError, AttributeError, KeyError, IndexError, RecursionError)

_page_access: ContextVar[dict[tuple[int, int], UserAccessControl] | None] = ContextVar(
    "resend_import_page_access", default=None
)


@contextmanager
def reuse_import_access() -> Iterator[None]:
    """Load each user's access rules once for every automation imported inside the block."""
    token = _page_access.set({})
    try:
        yield
    finally:
        _page_access.reset(token)


def _access(team: Team, user: User) -> UserAccessControl:
    cache = _page_access.get()
    if cache is None:
        return UserAccessControl(user=user, team=team)
    key = (team.id, user.id)
    if key not in cache:
        cache[key] = UserAccessControl(user=user, team=team)
    return cache[key]


def import_resend_automation(
    team_id: int,
    user_id: int | None,
    automation: dict[str, Any],
    emails: Mapping[str, ImportedEmail | None],
    *,
    step_emails: Mapping[str, ImportedStepEmail] | None = None,
    segments: Mapping[str, str | None] | None = None,
) -> ProviderAutomationResult:
    """Saves a Resend automation as a draft workflow. An automation imported before stays as it is, unless its draft
    was deleted.

    `segments` holds the name of each segment the automation adds people to, by id, or None if Resend no longer has it.
    """
    # The draft check lives in the views layer, and importing it at load time would bring the whole API with it.
    from products.workflows.backend.presentation.views.workflow_import_drafts import (  # noqa: PLC0415
        save_provider_draft,
    )

    team = Team.objects.get(id=team_id)
    user = User.objects.filter(id=user_id).first()
    if user is None:
        return ProviderAutomationResult(
            status="failed", workflow_id=None, notes=("The person who started this import no longer exists.",)
        )
    previous = previous_import(team, str(automation.get("id")), WorkflowImportSource.RESEND)
    # A rerun leaves the earlier draft alone, so it must not create cohorts that draft doesn't use.
    if previous.hog_flow_id is not None:
        return ProviderAutomationResult(
            status="skipped",
            workflow_id=str(previous.hog_flow_id),
            notes=("You imported this automation before, so PostHog left it as it is.",),
        )
    access = _access(team, user)
    # The import runs in the background, so the person who started it may have lost access since.
    if (
        not user.is_active
        or not access.has_project_access
        or not access.check_access_level_for_resource("hog_flow", "editor")
    ):
        return ProviderAutomationResult(
            status="failed",
            workflow_id=None,
            notes=("The person who started this import can't edit workflows in this project anymore.",),
        )
    steps = automation.get("steps")
    step_types = {
        step_type
        for step in (steps if isinstance(steps, list) else [])
        if isinstance(step, dict) and isinstance(step_type := step.get("type"), str)
    }
    context = TranslationContext(
        step_emails=step_emails or {},
        segment_cohorts={
            segment_id: _segment_cohort(team_id, user, access, segment_id, name)
            for segment_id, name in (segments or {}).items()
        },
        unavailable_templates=frozenset(hidden_gated_template_ids(team))
        if step_types & {"add_to_segment", "contact_update"}
        else frozenset(),
    )
    try:
        translated = translate_automation(automation, emails, context)
    except _UNREADABLE as error:
        logger.info("workflows.import.unreadable_resend_automation", team_id=team_id, error=type(error).__name__)
        return ProviderAutomationResult(
            status="failed",
            workflow_id=None,
            notes=(
                "Resend sent a value PostHog couldn't read in this automation. Check it in Resend and import it again.",
            ),
        )
    return save_provider_draft(team, user, translated, WorkflowImportSource.RESEND, record_id=previous.record_id)


def _segment_cohort(
    team_id: int, user: User, access: UserAccessControl, segment_id: str, name: str | None
) -> SegmentCohort:
    if name is None:
        return SegmentCohort(problem="This segment no longer exists in Resend.")
    # Nothing else ties a cohort to a segment, and the description stays the same when either one is renamed.
    description = f"Imported from Resend segment {segment_id}."
    existing = find_cohort_ref_by_description(team_id=team_id, description=description)
    if existing is not None:
        return _reused_cohort(existing, access, name)
    if not access.check_access_level_for_resource("cohort", "editor"):
        return SegmentCohort(problem="Creating a cohort for this segment needs edit access to cohorts.")
    cohort_name = f"{name[:380]} (from Resend)"
    created = create_empty_static_cohort(
        team_id=team_id, name=cohort_name, description=description, created_by_id=user.id
    )
    return SegmentCohort(name=cohort_name, cohort_id=created.id)


def _reused_cohort(existing: CohortRef, access: UserAccessControl, name: str) -> SegmentCohort:
    if existing.deleted:
        return SegmentCohort(
            problem=f'The cohort made for the Resend segment "{name}" was deleted, so it stays deleted.'
        )
    if not existing.is_static:
        return SegmentCohort(problem=f'The cohort made for the Resend segment "{name}" isn\'t static anymore.')
    ref = ObjectAccessRef(
        resource="cohort", id=str(existing.id), team_id=existing.team_id, created_by_id=existing.created_by_id
    )
    if not access.check_access_level_for_ref(ref, "editor"):
        return SegmentCohort(problem=f'Adding people to the cohort for the Resend segment "{name}" needs edit access.')
    return SegmentCohort(name=f"{name} (from Resend)", cohort_id=existing.id)
