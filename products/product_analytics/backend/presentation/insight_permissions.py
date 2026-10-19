from typing import TYPE_CHECKING, cast

from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request

from products.dashboards.backend.facade.api import insights_with_dashboard_edit_access
from products.product_analytics.backend.facade.models import Insight

if TYPE_CHECKING:
    from rest_framework.views import APIView

    from products.product_analytics.backend.presentation.insight import InsightViewSet


class CanEditInsightDashboards(BasePermission):
    message = "You don't have permission to edit this insight"

    def has_object_permission(self, request: Request, view: "APIView", insight: Insight) -> bool:
        if request.method in SAFE_METHODS:
            return True
        insight_view = cast("InsightViewSet", view)
        return insight.id in insights_with_dashboard_edit_access(
            [insight.id], user_access_control=insight_view.user_access_control, project_id=insight_view.team.project_id
        )
