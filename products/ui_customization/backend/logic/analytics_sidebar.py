from ..facade.contracts import AnalyticsSidebarLayout, SidebarLink, SidebarList, SidebarPageTarget, SidebarSection
from ..facade.enums import CustomizationContext, SidebarIcon, SidebarListSource, SidebarPage
from .context_definition import CustomizationContextDefinition


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


ANALYTICS_SIDEBAR = CustomizationContextDefinition(
    context=CustomizationContext.ANALYTICS_SIDEBAR, layout_schema=AnalyticsSidebarLayout, defaults=DEFAULT_LAYOUT
)
