from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from posthog.models.team.team import Team

from products.signals.backend.artefact_schemas import SignalFinding
from products.signals.backend.models import SignalReportArtefact
from products.signals.backend.report_generation.research import ResearchReviewerDecision

if TYPE_CHECKING:
    from products.signals.backend.auto_start import ReviewerContent

logger = structlog.get_logger(__name__)


def resolve_research_reviewers(team_id: int, decision: ResearchReviewerDecision) -> list[ReviewerContent]:
    if not decision.reviewers:
        return []
    team = Team.objects.get(id=team_id)
    members = {
        member.uuid: member
        for member in team.all_users_with_access().filter(uuid__in=[entry.user_uuid for entry in decision.reviewers])
    }
    reviewers: list[ReviewerContent] = []
    seen = set()
    for entry in decision.reviewers:
        member = members.get(entry.user_uuid)
        if member is None or entry.user_uuid in seen:
            continue
        login = member.get_github_login(include_team_fallback=False)
        if login and login.lower().endswith("[bot]"):
            continue
        seen.add(entry.user_uuid)
        reviewers.append(
            {
                "github_login": login.lower() if login else None,
                "user_uuid": str(member.uuid),
                "github_name": None,
                "relevant_commits": [],
                "reason": entry.reason,
                "is_skill_owner": False,
                "is_research_selected": True,
                "source_skill": None,
            }
        )
    return reviewers


def confirmed_research_reviewer_uuids(
    team_id: int, report_id: str, repository: str, reviewers: list[ReviewerContent]
) -> set[str]:
    from products.signals.backend.temporal.agentic.report import (
        _build_reviewers_content,  # noqa: PLC0415 - report persistence imports this module
    )

    candidates = [entry["user_uuid"] for entry in reviewers if entry.get("is_research_selected") and entry["user_uuid"]]
    if not candidates or not repository:
        return set()
    try:
        findings: dict[str, SignalFinding] = {}
        for content in (
            SignalReportArtefact.objects.filter(team_id=team_id, report_id=report_id, type="signal_finding")
            .order_by("created_at", "id")
            .values_list("content", flat=True)
        ):
            finding = SignalFinding.model_validate_json(content)
            findings[finding.signal_id] = finding
        resolution = _build_reviewers_content(team_id, repository, list(findings.values()))
        logins = {entry["github_login"] for entry in resolution.reviewers if entry["github_login"]}
        members = Team.objects.get(id=team_id).all_users_with_access().filter(uuid__in=candidates)
        return {
            str(member.uuid)
            for member in members
            if (login := member.get_github_login(include_team_fallback=False)) and login.lower() in logins
        }
    except Exception as error:
        logger.warning(
            "Research reviewer confirmation failed",
            team_id=team_id,
            report_id=report_id,
            error_type=type(error).__name__,
        )
        return set()
