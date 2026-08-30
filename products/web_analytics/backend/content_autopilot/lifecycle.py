from collections.abc import Iterable

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
MAX_PROPOSALS_PER_PULL_REQUEST = 5

ACTIVE_RUN_STATUSES = {ContentAutopilotRun.RunStatus.PENDING, ContentAutopilotRun.RunStatus.GENERATING}


def start_run(*, team: Team, profile_id: str, triggered_by_id: int | None) -> ContentAutopilotRun:
    with transaction.atomic():
        try:
            profile = ContentAutopilotSiteProfile.objects.for_team(team.id).select_for_update().get(id=profile_id)
        except ContentAutopilotSiteProfile.DoesNotExist as error:
            raise ContentAutopilotLifecycleError("Select a site before starting a content run.") from error

        if (
            ContentAutopilotRun.objects.for_team(team.id)
            .filter(profile=profile, run_status__in=ACTIVE_RUN_STATUSES)
            .exists()
        ):
            raise ContentAutopilotLifecycleError("A content run is already in progress for this site.")

        return ContentAutopilotRun.objects.for_team(team.id).create(
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
                "delivery_mode": profile.delivery_mode,
                "github_repository": profile.github_repository,
                "base_branch": profile.base_branch,
                "content_directories": profile.content_directories,
                "url_to_file_convention": profile.url_to_file_convention,
            },
            triggered_by_id=triggered_by_id,
        )


def cancel_run(*, run: ContentAutopilotRun) -> ContentAutopilotRun:
    with transaction.atomic():
        locked_run = ContentAutopilotRun.objects.for_team(run.team_id).select_for_update().get(id=run.id)
        if locked_run.run_status not in ACTIVE_RUN_STATUSES:
            raise ContentAutopilotLifecycleError("Only a pending or generating run can be canceled.")
        locked_run.run_status = ContentAutopilotRun.RunStatus.CANCELED
        locked_run.completed_at = timezone.now()
        locked_run.save(update_fields=["run_status", "completed_at", "updated_at"])
        return locked_run


def reject_proposal(*, proposal: ContentAutopilotProposal) -> ContentAutopilotProposal:
    with transaction.atomic():
        locked_proposal = (
            ContentAutopilotProposal.objects.for_team(proposal.team_id).select_for_update().get(id=proposal.id)
        )
        if locked_proposal.lifecycle_status != ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW:
            raise ContentAutopilotLifecycleError("Only a proposal ready for review can be rejected.")
        locked_proposal.lifecycle_status = ContentAutopilotProposal.LifecycleStatus.REJECTED
        locked_proposal.save(update_fields=["lifecycle_status", "updated_at"])
        return locked_proposal


def _reset_for_regeneration(proposal: ContentAutopilotProposal) -> None:
    proposal.lifecycle_status = ContentAutopilotProposal.LifecycleStatus.GENERATING
    proposal.validation_report = default_content_autopilot_validation_report()
    proposal.delivery_state = ContentAutopilotProposal.DeliveryState.NOT_DELIVERED
    proposal.delivery_reference = ""
    proposal.delivery_error = ""


def regenerate_proposal(*, proposal: ContentAutopilotProposal) -> ContentAutopilotProposal:
    with transaction.atomic():
        locked_proposal = (
            ContentAutopilotProposal.objects.for_team(proposal.team_id).select_for_update().get(id=proposal.id)
        )
        if locked_proposal.lifecycle_status not in {
            ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW,
            ContentAutopilotProposal.LifecycleStatus.FAILED,
        }:
            raise ContentAutopilotLifecycleError("This proposal cannot be regenerated in its current state.")
        _reset_for_regeneration(locked_proposal)
        locked_proposal.save(
            update_fields=[
                "lifecycle_status",
                "validation_report",
                "delivery_state",
                "delivery_reference",
                "delivery_error",
                "updated_at",
            ]
        )
        return locked_proposal


def edit_proposal(
    *,
    proposal: ContentAutopilotProposal,
    proposed_markdown: str,
    content_package: dict[str, object],
) -> ContentAutopilotProposal:
    if len(proposed_markdown) > MAX_PROPOSAL_MARKDOWN_CHARS:
        raise ContentAutopilotLifecycleError("Proposal Markdown must be 500,000 characters or fewer.")
    with transaction.atomic():
        locked_proposal = (
            ContentAutopilotProposal.objects.for_team(proposal.team_id).select_for_update().get(id=proposal.id)
        )
        if locked_proposal.lifecycle_status != ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW:
            raise ContentAutopilotLifecycleError("Only a proposal ready for review can be edited.")
        locked_proposal.proposed_markdown = proposed_markdown
        locked_proposal.content_package = {**content_package, "markdown": proposed_markdown}
        _reset_for_regeneration(locked_proposal)
        locked_proposal.save(
            update_fields=[
                "proposed_markdown",
                "content_package",
                "lifecycle_status",
                "validation_report",
                "delivery_state",
                "delivery_reference",
                "delivery_error",
                "updated_at",
            ]
        )
        return locked_proposal


def claim_proposals_for_delivery(*, team_id: int, proposal_ids: Iterable[str]) -> list[ContentAutopilotProposal]:
    ids = list(dict.fromkeys(proposal_ids))
    if not ids:
        raise ContentAutopilotLifecycleError("Select at least one proposal.")
    if len(ids) > MAX_PROPOSALS_PER_PULL_REQUEST:
        raise ContentAutopilotLifecycleError("Select no more than five proposals.")

    with transaction.atomic():
        proposals = list(
            ContentAutopilotProposal.objects.for_team(team_id)
            .select_for_update()
            .select_related("run__profile")
            .filter(id__in=ids)
            .order_by("created_at")
        )
        if len(proposals) != len(ids):
            raise ContentAutopilotLifecycleError("One or more proposals could not be found.")
        if any(
            proposal.lifecycle_status != ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW
            for proposal in proposals
        ):
            raise ContentAutopilotLifecycleError("Every selected proposal must be ready for review.")
        if any(proposal.validation_report.get("passed") is not True for proposal in proposals):
            raise ContentAutopilotLifecycleError("Every selected proposal must pass blocking validation.")
        if any(proposal.delivery_state == ContentAutopilotProposal.DeliveryState.DELIVERING for proposal in proposals):
            raise ContentAutopilotLifecycleError("One or more selected proposals are already being delivered.")
        if len({proposal.run_id for proposal in proposals}) != 1:
            raise ContentAutopilotLifecycleError("Selected proposals must come from the same run.")
        if len(proposals) > 1 and any(
            proposal.proposal_type == ContentAutopilotProposal.ProposalType.NEW_CONTENT for proposal in proposals
        ):
            raise ContentAutopilotLifecycleError("New content must be delivered in its own pull request.")

        now = timezone.now()
        ContentAutopilotProposal.objects.for_team(team_id).filter(id__in=ids).update(
            delivery_state=ContentAutopilotProposal.DeliveryState.DELIVERING,
            delivery_reference="",
            delivery_error="",
            updated_at=now,
        )
        for proposal in proposals:
            proposal.delivery_state = ContentAutopilotProposal.DeliveryState.DELIVERING
            proposal.updated_at = now
        return proposals


def mark_delivery_failed(*, team_id: int, proposal_ids: Iterable[str], message: str) -> None:
    ContentAutopilotProposal.objects.for_team(team_id).filter(id__in=list(proposal_ids)).update(
        delivery_state=ContentAutopilotProposal.DeliveryState.FAILED,
        delivery_error=message[:1024],
        updated_at=timezone.now(),
    )
