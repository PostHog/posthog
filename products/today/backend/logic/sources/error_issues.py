"""Active error tracking issues assigned to the person or one of their roles."""

from products.access_control.backend.facade import api as access_control
from products.error_tracking.backend.facade import api as error_tracking

from ...facade.enums import ItemGroup, ItemReason, ItemSource
from ..candidates import Candidate, SourceContext, app_url

_SUBGROUP = 1


def collect(ctx: SourceContext) -> list[Candidate]:
    role_ids = access_control.role_ids_for_user(user_id=ctx.user.id, organization_id=ctx.team.organization_id)
    issues = error_tracking.active_issues_assigned_to(team_id=ctx.team.id, user_id=ctx.user.id, role_ids=role_ids)
    return [
        Candidate(
            key=f"error:{issue.issue_id}",
            group=ItemGroup.OTHER,
            source=ItemSource.ERROR_TRACKING,
            reason=ItemReason.ASSIGNED_ERROR_ISSUE,
            title=issue.name,
            url=app_url(ctx.team.id, f"error_tracking/{issue.issue_id}"),
            sort_key=(_SUBGROUP, 1 if issue.assigned_via_role else 0, -issue.created_at.timestamp()),
            facts={
                "assigned_via_role": issue.assigned_via_role,
                "days_since_first_seen": max((ctx.now - issue.created_at).days, 0),
            },
        )
        for issue in issues
    ]
