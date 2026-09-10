import logging
import dataclasses
from typing import Literal

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models import Team

from products.signals.backend.report_generation.resolve_reviewers import (
    ReviewerResolutionDiagnostics,
    normalized_user_uuids_from_reviewer_payloads,
    resolve_org_github_login_to_users,
    resolve_org_users_by_uuid,
)

logger = logging.getLogger(__name__)

# Pipeline suggestions are capped at MAX_SUGGESTED_REVIEWERS, but scout assignee lists are
# model-proposed and unbounded, so cap what reaches event properties.
_MAX_LOGINS_PER_EVENT = 10

ReviewerSuggestionSource = Literal["pipeline", "scout", "scout_edit", "custom_agent", "user_edit", "api"]


@frozen
class ReviewerLinkability:
    linkable_logins: list[str]
    unlinkable_logins: list[str]
    linkable_user_uuids: list[str]
    unlinkable_user_uuids: list[str]

    @property
    def linkable_count(self) -> int:
        return len(self.linkable_logins) + len(self.linkable_user_uuids)

    @property
    def unlinkable_count(self) -> int:
        return len(self.unlinkable_logins) + len(self.unlinkable_user_uuids)


def split_reviewer_linkability(
    team_id: int, github_logins: list[str], user_uuids: list[str] | None = None
) -> ReviewerLinkability:
    """Split suggested reviewers by whether they resolve to an active org member.

    `user_uuids` are the reviewers stored by PostHog user alone. Only the write paths that resolve
    membership before writing can vouch for them; the generic artefact API stores any well-formed
    uuid, so they are resolved here the same way logins are rather than trusted.
    """
    normalized = list(dict.fromkeys(login.strip().lower() for login in github_logins if login and login.strip()))
    login_to_user = resolve_org_github_login_to_users(team_id, normalized)
    normalized_uuids = sorted(normalized_user_uuids_from_reviewer_payloads({"user_uuid": u} for u in user_uuids or []))
    uuid_to_user = resolve_org_users_by_uuid(team_id, normalized_uuids) if normalized_uuids else {}
    return ReviewerLinkability(
        linkable_logins=[login for login in normalized if login in login_to_user],
        unlinkable_logins=[login for login in normalized if login not in login_to_user],
        linkable_user_uuids=[u for u in normalized_uuids if u in uuid_to_user],
        unlinkable_user_uuids=[u for u in normalized_uuids if u not in uuid_to_user],
    )


def capture_suggested_reviewers_resolved(
    *,
    team_id: int,
    report_id: str,
    github_logins: list[str],
    source: ReviewerSuggestionSource,
    user_uuids: list[str] | None = None,
    correction_notes_written: int | None = None,
    correction_note_targets: int | None = None,
) -> None:
    """Emit `signals_suggested_reviewers_resolved` when a report's suggested reviewers are persisted.

    A reviewer stored by GitHub login is only linked to a PostHog user downstream (Slack routing,
    autostart, API read), where an unmapped login falls through silently. A report whose logins map
    to nobody cannot be routed to a person, yet still counts as "assigned" in
    `suggested_reviewers`-based metrics. This event records the linkable/unlinkable split at
    suggestion time so that bucket is measurable.

    `user_uuids` are the reviewers identified by PostHog user alone, with no GitHub login. One that
    resolves to an active org member is linkable and is reported in `user_uuid_only_count`, kept
    separate because autostart still needs a login to run as someone. One that does not resolve is
    unlinkable like an unknown login: nothing downstream will route it to a person.

    A human edit that changed the set also steers the scouts holding the routing memory it
    corrects (`reviewer_correction_notes.py`). `correction_notes_written` and
    `correction_note_targets` report what that forwarding did — notes written, and scouts the
    correction was addressed to, which is the larger number when the suppression window swallowed a
    target's logins. Both are absent on every other path, so absence reads as "no correction".

    Best-effort: never raises, so analytics can't break report generation.
    """
    try:
        linkability = split_reviewer_linkability(team_id, github_logins, user_uuids)
        if linkability.unlinkable_count:
            # GitHub logins are member PII, so logs carry counts only; the logins themselves go in
            # the event properties, the same internal-analytics surface the artefact already feeds.
            logger.info(
                "suggested reviewers for report %s (team %d): %d of %d reviewer(s) have no PostHog user",
                report_id,
                team_id,
                linkability.unlinkable_count,
                linkability.linkable_count + linkability.unlinkable_count,
            )
        team = Team.objects.select_related("organization").get(id=team_id)
        posthoganalytics.capture(
            event="signals_suggested_reviewers_resolved",
            distinct_id=str(team.uuid),
            properties={
                "team_id": team_id,
                "report_id": report_id,
                "source": source,
                "suggested_count": linkability.linkable_count + linkability.unlinkable_count,
                "linkable_count": linkability.linkable_count,
                "unlinkable_count": linkability.unlinkable_count,
                "linkable_logins": linkability.linkable_logins[:_MAX_LOGINS_PER_EVENT],
                "unlinkable_logins": linkability.unlinkable_logins[:_MAX_LOGINS_PER_EVENT],
                "user_uuid_only_count": len(linkability.linkable_user_uuids),
                "unlinkable_user_uuid_count": len(linkability.unlinkable_user_uuids),
                "all_unlinkable": bool(linkability.unlinkable_count) and not linkability.linkable_count,
                **(
                    {}
                    if correction_notes_written is None
                    else {
                        "correction_notes_written": correction_notes_written,
                        "correction_note_targets": correction_note_targets,
                    }
                ),
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.exception("Failed to capture signals_suggested_reviewers_resolved for report %s", report_id)


def capture_suggested_reviewers_unresolved(
    *,
    team_id: int,
    report_id: str,
    diagnostics: ReviewerResolutionDiagnostics,
    finding_count: int,
    has_new_finding: bool,
) -> None:
    """Emit `signals_suggested_reviewers_unresolved` when a pipeline run yields no reviewers.

    Nothing is persisted for an empty list, so this is the only record of *why* a report ended
    up with no one to route to: no repository, findings without commits, no reachable GitHub
    integration, or lookups that came back without an attributable author. Fires per run;
    read it as the latest event per `report_id`.

    Best-effort: never raises, so analytics can't break report generation.
    """
    try:
        logger.info(
            "no suggested reviewers for report %s (team %d): %s (%d commit hash(es), %d/%d lookups resolved)",
            report_id,
            team_id,
            diagnostics.outcome,
            diagnostics.commit_hash_count,
            diagnostics.lookups_resolved,
            diagnostics.lookups_attempted,
        )
        team = Team.objects.select_related("organization").get(id=team_id)
        posthoganalytics.capture(
            event="signals_suggested_reviewers_unresolved",
            distinct_id=str(team.uuid),
            properties={
                "team_id": team_id,
                "report_id": report_id,
                "source": "pipeline",
                "finding_count": finding_count,
                "has_new_finding": has_new_finding,
                **dataclasses.asdict(diagnostics),
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.exception("Failed to capture signals_suggested_reviewers_unresolved for report %s", report_id)
