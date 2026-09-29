from posthog.models.team.team import Team

from products.signals.backend.auto_start import ReviewerContent
from products.signals.backend.report_generation.research import ResearchReviewerDecision


def resolve_research_reviewers(team_id: int, decision: ResearchReviewerDecision) -> list[ReviewerContent]:
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
        login = member.get_github_login()
        if login and login.lower().endswith("[bot]"):
            continue
        seen.add(entry.user_uuid)
        reviewers.append(
            ReviewerContent(
                github_login=login.lower() if login else None,
                user_uuid=str(member.uuid),
                github_name=None,
                relevant_commits=[],
                reason=entry.reason,
                is_skill_owner=False,
                source_skill=None,
            )
        )
    return reviewers
