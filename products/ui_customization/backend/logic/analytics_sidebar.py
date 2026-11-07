from django.db import IntegrityError, router, transaction
from django.utils import timezone

import structlog
from pydantic import ValidationError

from posthog.models import Team

from ..facade.contracts import (
    AnalyticsSidebar,
    AnalyticsSidebarLayout,
    SidebarLink,
    SidebarList,
    SidebarPageTarget,
    SidebarSection,
)
from ..facade.enums import SidebarIcon, SidebarListSource, SidebarPage
from ..models import UserInterfaceFragment

logger = structlog.get_logger(__name__)
SIDEBAR_CONTEXT = "analytics_sidebar"


def _page(page: SidebarPage) -> SidebarLink:
    return SidebarLink(type="link", to=SidebarPageTarget(kind="page", page=page))


def _list(source: SidebarListSource) -> SidebarList:
    return SidebarList(type="list", source=source)


# pinned: the section ids key each person's open and closed sections and the `section` property of
# `analytics section toggled`. Renaming one reopens that section for everyone and breaks dashboards.
DEFAULT_LAYOUT = AnalyticsSidebarLayout(
    sections=[
        SidebarSection(
            id="browse",
            items=[_page(SidebarPage.ANALYTICS_ALL), _page(SidebarPage.ANALYTICS_MINE), _page(SidebarPage.COLLECTIONS)],
        ),
        SidebarSection(id="pinned", title="Pinned", items=[_list(SidebarListSource.PINNED)]),
        SidebarSection(id="recents", title="Recents", items=[_list(SidebarListSource.RECENTS)]),
        SidebarSection(
            id="by-posthog", title="By PostHog", icon=SidebarIcon.POSTHOG, items=[_list(SidebarListSource.BY_POSTHOG)]
        ),
        SidebarSection(
            id="monitor", title="Monitor", items=[_page(SidebarPage.ALERTS), _page(SidebarPage.SUBSCRIPTIONS)]
        ),
    ]
)

DEFAULT = AnalyticsSidebar(layout=DEFAULT_LAYOUT, customized=False)


def get_sidebar(*, team: Team, user_id: int) -> AnalyticsSidebar:
    row = (
        UserInterfaceFragment.objects.for_team(_canonical(team), canonical=True)
        .filter(user_id=user_id, context=SIDEBAR_CONTEXT)
        .first()
    )
    if row is None:
        return DEFAULT
    try:
        return AnalyticsSidebar(layout=AnalyticsSidebarLayout.model_validate(row.content), customized=True)
    except ValidationError:
        # The row stays, so a rolled-back deploy that does not know a newer value gets the layout back on the next one.
        logger.warning("ui_customization_analytics_sidebar_invalid", team_id=row.team_id, user_id=user_id)
        return DEFAULT


def set_sidebar(*, team: Team, user_id: int, layout: AnalyticsSidebarLayout) -> AnalyticsSidebar:
    team_id = _canonical(team)
    stored = layout.model_dump(mode="json", exclude_none=True)
    try:
        with transaction.atomic(using=router.db_for_write(UserInterfaceFragment)):
            UserInterfaceFragment.objects.for_team(team_id, canonical=True).update_or_create(
                team_id=team_id, user_id=user_id, context=SIDEBAR_CONTEXT, defaults={"content": stored}
            )
    except IntegrityError:
        UserInterfaceFragment.objects.for_team(team_id, canonical=True).filter(
            user_id=user_id, context=SIDEBAR_CONTEXT
        ).update(content=stored, updated_at=timezone.now())
    return AnalyticsSidebar(layout=layout, customized=True)


def reset_sidebar(*, team: Team, user_id: int) -> AnalyticsSidebar:
    UserInterfaceFragment.objects.for_team(_canonical(team), canonical=True).filter(
        user_id=user_id, context=SIDEBAR_CONTEXT
    ).delete()
    return DEFAULT


def _canonical(team: Team) -> int:
    return team.parent_team_id or team.id
