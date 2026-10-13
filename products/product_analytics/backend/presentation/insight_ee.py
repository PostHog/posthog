"""Insights viewset variant enforcing dashboard edit permissions, selected by routes.py on EE_AVAILABLE installs."""

from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request

from products.dashboards.backend.facade.enums import PrivilegeLevel
from products.product_analytics.backend.facade.models import Insight
from products.product_analytics.backend.presentation.insight import InsightViewSet


class CanEditInsight(BasePermission):
    message = "This insight is on a dashboard that can only be edited by its owner, team members invited to editing the dashboard, and project admins."

    def has_object_permission(self, request: Request, view, insight: Insight) -> bool:
        if request.method in SAFE_METHODS:
            return True

        return view.user_permissions.insight(insight).effective_privilege_level == PrivilegeLevel.CAN_EDIT


class EnterpriseInsightsViewSet(InsightViewSet):
    permission_classes = [CanEditInsight]
