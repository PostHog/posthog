from posthog.models import Team, User

from products.dashboards.backend.facade import api as dashboards
from products.notebooks.backend.facade import api as notebooks
from products.product_analytics.backend.facade import api as product_analytics

from ..facade.analytics import (
    AnalyticsDashboardTarget,
    AnalyticsFragmentButton,
    AnalyticsFragmentLink,
    AnalyticsFragmentMetric,
    AnalyticsInsightTarget,
    AnalyticsNotebookTarget,
)
from ..facade.contracts import CustomizationLayout


def unavailable_targets(*, team: Team, user: User, layout: CustomizationLayout) -> list[str]:
    """One message per item that points at something this person cannot open in this project, in layout order."""
    root_team_id = team.parent_team_id or team.id
    located = [
        (f"sections.{section_index}.items.{item_index}", item)
        for section_index, section in enumerate(layout.sections)
        for item_index, item in enumerate(section.items)
    ]
    targets = [item.to for _, item in located if isinstance(item, AnalyticsFragmentLink | AnalyticsFragmentButton)]

    insight_ids = {to.short_id for to in targets if isinstance(to, AnalyticsInsightTarget)}
    insight_ids |= {item.insight for _, item in located if isinstance(item, AnalyticsFragmentMetric)}
    insight_is_trends = (
        product_analytics.viewable_insights_are_trends(team=team, user=user, short_ids=insight_ids)
        if insight_ids
        else {}
    )
    dashboard_ids = [to.id for to in targets if isinstance(to, AnalyticsDashboardTarget)]
    missing_dashboards = (
        set(dashboards.unknown_dashboard_ids(dashboard_ids, team_id=root_team_id)) if dashboard_ids else set()
    )
    missing_notebooks = {
        to.short_id
        for to in targets
        if isinstance(to, AnalyticsNotebookTarget)
        and not notebooks.notebook_exists(root_team_id, to.short_id, include_deleted=False)
    }

    problems = []
    for path, item in located:
        if isinstance(item, AnalyticsFragmentMetric):
            is_trends = insight_is_trends.get(item.insight)
            if is_trends is None:
                problems.append(f"{path}.insight: No insight {item.insight} that you can open in this project.")
            elif not is_trends:
                problems.append(
                    f"{path}.insight: Insight {item.insight} is not a trends insight, so it has no number to show. "
                    "Link to it instead."
                )
            continue
        if not isinstance(item, AnalyticsFragmentLink | AnalyticsFragmentButton):
            continue
        to = item.to
        if isinstance(to, AnalyticsInsightTarget) and to.short_id not in insight_is_trends:
            problems.append(f"{path}.to: No insight {to.short_id} that you can open in this project.")
        elif isinstance(to, AnalyticsDashboardTarget) and to.id in missing_dashboards:
            problems.append(f"{path}.to: No dashboard {to.id} in this project.")
        elif isinstance(to, AnalyticsNotebookTarget) and to.short_id in missing_notebooks:
            problems.append(f"{path}.to: No notebook {to.short_id} in this project.")
    return problems
