"""What happens after a report claim commits: tell the scouts, then record what the claim did.

Kept out of `report_assignments`, which the scout harness imports, so the claim path does not
import the harness back.
"""

from __future__ import annotations

import logging
import dataclasses

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models import Team, User

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.reviewer_correction_notes import (
    ReviewerClaim,
    claim_scout_notes_enabled,
    forward_reviewer_claim_note,
)
from products.signals.backend.scout_note_actor import actor_github_login
from products.signals.backend.suggested_reviewer_index import match_reviewer_set

logger = logging.getLogger(__name__)


@frozen
class ClaimantOutcome:
    """What a claim by a person or their agent said about routing, and what forwarding it achieved."""

    claimant_was_suggested: bool
    suggested_count: int
    claim_notes_enabled: bool
    claim_notes_written: int
    claim_note_targets: int


def record_report_claimed(
    *,
    team_id: int,
    report_id: str,
    actor: ArtefactAttribution,
    scoped_team_ids: tuple[int, ...] | None,
    was_impersonated: bool,
    takeover: bool,
) -> None:
    """Forward a new claim to the scouts, then emit `signals_report_claimed`.

    Only a person or their agent chose the work, so task and system claims are recorded but never
    forwarded. An impersonated claim is a support action, not routing evidence, the same rule the
    reviewer correction notes follow.
    """
    try:
        team = Team.objects.select_related("organization").get(id=team_id)
        claimant: ClaimantOutcome | None = None
        user = User.objects.filter(pk=actor.user_id).first() if actor.kind in ("user", "agent") else None
        if user is not None:
            match = match_reviewer_set(
                team_id=team_id,
                report_id=report_id,
                user_uuid=str(user.uuid),
                github_login=actor_github_login(team_id, user),
            )
            notes_enabled = claim_scout_notes_enabled(team)
            forwarded = (
                forward_reviewer_claim_note(
                    team=team,
                    claim=ReviewerClaim(
                        report_id=report_id,
                        actor_user_id=user.id,
                        scoped_team_ids=scoped_team_ids,
                        claimant_was_suggested=match.names_identity,
                        via_agent=actor.agent_name if actor.kind == "agent" else None,
                    ),
                )
                if notes_enabled and not was_impersonated
                else None
            )
            claimant = ClaimantOutcome(
                claimant_was_suggested=match.names_identity,
                suggested_count=match.reviewer_count,
                claim_notes_enabled=notes_enabled,
                claim_notes_written=len(forwarded.note_ids) if forwarded else 0,
                claim_note_targets=forwarded.targets_resolved if forwarded else 0,
            )
        _capture_report_claimed(team=team, report_id=report_id, actor=actor, takeover=takeover, claimant=claimant)
    except Exception:
        # The claim and its activity row already committed. Nothing here may turn it into a 5xx.
        logger.exception("Failed to record a report claim", extra={"team_id": team_id, "report_id": report_id})


def _capture_report_claimed(
    *, team: Team, report_id: str, actor: ArtefactAttribution, takeover: bool, claimant: ClaimantOutcome | None
) -> None:
    # For a person or their agent, the share of claims with `claimant_was_suggested` is the routing hit
    # rate the claim notes try to raise. Compare it by `claim_notes_enabled`.
    posthoganalytics.capture(
        event="signals_report_claimed",
        distinct_id=str(team.uuid),
        properties={
            "team_id": team.id,
            "report_id": report_id,
            "actor_kind": actor.kind,
            "takeover": takeover,
            **(dataclasses.asdict(claimant) if claimant else {}),
        },
        groups=groups(team.organization, team),
    )
