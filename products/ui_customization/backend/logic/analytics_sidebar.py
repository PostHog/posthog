from ..facade.analytics import (
    AnalyticsFragmentLayout,
    AnalyticsFragmentLink,
    AnalyticsFragmentList,
    AnalyticsFragmentSection,
    AnalyticsListSource,
    AnalyticsPage,
    AnalyticsPageTarget,
)
from ..facade.enums import CustomizationContext, FragmentIcon
from .context_definition import CustomizationContextDefinition


def _page(page: AnalyticsPage) -> AnalyticsFragmentLink:
    return AnalyticsFragmentLink(type="link", to=AnalyticsPageTarget(kind="page", page=page))


def _list(source: AnalyticsListSource) -> AnalyticsFragmentList:
    return AnalyticsFragmentList(type="list", source=source)


# pinned: the section ids key each person's open and closed sections and the `section` property of
# `analytics section toggled`. Renaming one reopens that section for everyone and breaks dashboards.
DEFAULT_LAYOUT = AnalyticsFragmentLayout(
    sections=[
        AnalyticsFragmentSection(
            id="browse",
            items=[
                _page(AnalyticsPage.ANALYTICS_ALL),
                _page(AnalyticsPage.ANALYTICS_MINE),
                _page(AnalyticsPage.COLLECTIONS),
                _page(AnalyticsPage.DASHBOARDS),
            ],
        ),
        AnalyticsFragmentSection(id="pinned", title="Pinned", items=[_list(AnalyticsListSource.PINNED)]),
        AnalyticsFragmentSection(id="recents", title="Recents", items=[_list(AnalyticsListSource.RECENTS)]),
        AnalyticsFragmentSection(
            id="by-posthog",
            title="By PostHog",
            icon=FragmentIcon.POSTHOG,
            items=[_list(AnalyticsListSource.BY_POSTHOG)],
        ),
        AnalyticsFragmentSection(
            id="monitor", title="Monitor", items=[_page(AnalyticsPage.ALERTS), _page(AnalyticsPage.SUBSCRIPTIONS)]
        ),
    ]
)


ANALYTICS_SIDEBAR = CustomizationContextDefinition(
    context=CustomizationContext.ANALYTICS_SIDEBAR, layout_schema=AnalyticsFragmentLayout, defaults=DEFAULT_LAYOUT
)
