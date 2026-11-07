from posthog.models import Team, User

from ..logic import analytics_sidebar
from ..models import UserInterfaceFragment
from . import contracts
from .feature_flags import is_enabled_for as is_enabled_for


def get_analytics_sidebar(*, team: Team, user: User) -> contracts.AnalyticsSidebar:
    return analytics_sidebar.get_sidebar(team=team, user_id=user.id)


def set_analytics_sidebar(
    *, team: Team, user: User, layout: contracts.AnalyticsSidebarLayout
) -> contracts.AnalyticsSidebar:
    return analytics_sidebar.set_sidebar(team=team, user_id=user.id, layout=layout)


def reset_analytics_sidebar(*, team: Team, user: User) -> contracts.AnalyticsSidebar:
    return analytics_sidebar.reset_sidebar(team=team, user_id=user.id)


def delete_fragments_for_teams(team_ids: list[int]) -> None:
    UserInterfaceFragment.objects.unscoped().filter(team_id__in=team_ids).delete()
