from posthog.models import Team, User

from products.signals.backend.first_report_scout_types import FirstReportStatus as FirstReportStatus
from products.signals.backend.inbox_status import (
    InboxSetupState as InboxSetupState,
    InboxStatus,
    get_inbox_status as resolve_inbox_status,
)


def get_inbox_status(*, team_id: int, user_id: int) -> InboxStatus:
    team = Team.objects.select_related("organization", "parent_team").get(id=team_id)
    user = User.objects.get(id=user_id)
    return resolve_inbox_status(team, user)
