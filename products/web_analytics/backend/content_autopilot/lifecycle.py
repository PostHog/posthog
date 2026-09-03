from django.db import transaction
from django.utils import timezone

from posthog.models.team import Team

from products.web_analytics.backend.models import (
    ContentAutopilotProposal,
    ContentAutopilotRun,
    ContentAutopilotSiteProfile,
)
from products.web_analytics.backend.models.content_autopilot import default_content_autopilot_validation_report


class ContentAutopilotLifecycleError(Exception):
    pass


MAX_PROPOSAL_MARKDOWN_CHARS = 500_000

ACTIVE_RUN_STATUSES = {ContentAutopilotRun.RunStatus.PENDING, ContentAutopilotRun.RunStatus.GENERATING}


def canonical_team_id(team: Team) -> int:
    return team.parent_team_id or team.id


def lock_run(team: Team, run_id: str) -> ContentAutopilotRun:
    try:
        return (
            ContentAutopilotRun.objects.for_team(canonical_team_id(team), canonical=True)
            .select_for_update()
            .get(id=run_id)
        )
    except ContentAutopilotRun.DoesNotExist as error:
        raise ContentAutopilotLifecycleError("That content run could not be found.") from error


def lock_proposal(team: Team, proposal_id: str) -> ContentAutopilotProposal:
    try:
        return (
            ContentAutopilotProposal.objects.for_team(canonical_team_id(team), canonical=True)
            .select_for_update()
            .get(id=proposal_id)
        )
    except ContentAutopilotProposal.DoesNotExist as error:
        raise ContentAutopilotLifecycleError("That proposal could not be found.") from error


def start_run(*, team: Team, profile_id: str, triggered_by_id: int | None) -> ContentAutopilotRun:
    team_id = canonical_team_id(team)
    with transaction.atomic():
        try:
            profile = (
                ContentAutopilotSiteProfile.objects.for_team(team_id, canonical=True)
                .select_for_update()
                .get(id=profile_id)
            )
        except ContentAutopilotSiteProfile.DoesNotExist as error:
            raise ContentAutopilotLifecycleError("Select a site before starting a content run.") from error

        if (
            ContentAutopilotRun.objects.for_team(team_id, canonical=True)
            .filter(profile=profile, run_status__in=ACTIVE_RUN_STATUSES)
            .exists()
        ):
            raise ContentAutopilotLifecycleError("A content run is already in progress for this site.")

        return ContentAutopilotRun.objects.for_team(team_id, canonical=True).create(
            team=team,
            profile=profile,
            run_status=ContentAutopilotRun.RunStatus.PENDING,
            input_snapshot={
                "captured_at": timezone.now().isoformat(),
                "domain": profile.domain,
                "search_console_connected": profile.search_console_enabled,
                "confidence": "standard" if profile.search_console_enabled else "lower",
                "source_urls": profile.source_urls,
                "content_boundaries": profile.content_boundaries,
                "brand_rules": profile.brand_rules,
            },
            triggered_by_id=triggered_by_id,
        )


def cancel_run(*, team: Team, run_id: str) -> ContentAutopilotRun:
    with transaction.atomic():
        locked_run = lock_run(team, run_id)
        if locked_run.run_status not in ACTIVE_RUN_STATUSES:
            raise ContentAutopilotLifecycleError("Only a pending or generating run can be canceled.")
        locked_run.run_status = ContentAutopilotRun.RunStatus.CANCELED
        locked_run.completed_at = timezone.now()
        locked_run.save(update_fields=["run_status", "completed_at", "updated_at"])
        return locked_run


def reject_proposal(*, team: Team, proposal_id: str) -> ContentAutopilotProposal:
    with transaction.atomic():
        locked_proposal = lock_proposal(team, proposal_id)
        if locked_proposal.lifecycle_status != ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW:
            raise ContentAutopilotLifecycleError("Only a proposal ready for review can be rejected.")
        locked_proposal.lifecycle_status = ContentAutopilotProposal.LifecycleStatus.REJECTED
        locked_proposal.save(update_fields=["lifecycle_status", "updated_at"])
        return locked_proposal


def _reset_for_regeneration(proposal: ContentAutopilotProposal) -> list[str]:
    proposal.lifecycle_status = ContentAutopilotProposal.LifecycleStatus.GENERATING
    proposal.validation_report = default_content_autopilot_validation_report()
    return ["lifecycle_status", "validation_report"]


def regenerate_proposal(*, team: Team, proposal_id: str) -> ContentAutopilotProposal:
    with transaction.atomic():
        locked_proposal = lock_proposal(team, proposal_id)
        if locked_proposal.lifecycle_status not in {
            ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW,
            ContentAutopilotProposal.LifecycleStatus.FAILED,
        }:
            raise ContentAutopilotLifecycleError("Only proposals ready for review or failed can be regenerated.")
        locked_proposal.save(update_fields=[*_reset_for_regeneration(locked_proposal), "updated_at"])
        return locked_proposal


def edit_proposal(
    *,
    team: Team,
    proposal_id: str,
    proposed_markdown: str,
    content_package: dict[str, object],
) -> ContentAutopilotProposal:
    if len(proposed_markdown) > MAX_PROPOSAL_MARKDOWN_CHARS:
        raise ContentAutopilotLifecycleError(
            f"Proposal Markdown must be {MAX_PROPOSAL_MARKDOWN_CHARS:,} characters or fewer."
        )
    with transaction.atomic():
        locked_proposal = lock_proposal(team, proposal_id)
        if locked_proposal.lifecycle_status != ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW:
            raise ContentAutopilotLifecycleError("Only a proposal ready for review can be edited.")
        locked_proposal.proposed_markdown = proposed_markdown
        locked_proposal.content_package = {key: value for key, value in content_package.items() if key != "markdown"}
        locked_proposal.save(
            update_fields=[
                "proposed_markdown",
                "content_package",
                *_reset_for_regeneration(locked_proposal),
                "updated_at",
            ]
        )
        return locked_proposal
