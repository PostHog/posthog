from typing import cast

from drf_spectacular.utils import OpenApiResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle, UserRateThrottle

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.rate_limit import BurstRateThrottle, SustainedRateThrottle

from ..facade import api
from .serializers import AnalyticsSidebarRequestSerializer, AnalyticsSidebarSerializer


class AnalyticsSidebarBurstThrottle(UserRateThrottle):
    scope = "ui_customization_analytics_sidebar_burst"
    rate = "30/minute"


class AnalyticsSidebarSustainedThrottle(UserRateThrottle):
    scope = "ui_customization_analytics_sidebar_sustained"
    rate = "300/day"


ANALYTICS_SIDEBAR_THROTTLES = [
    BurstRateThrottle,
    SustainedRateThrottle,
    AnalyticsSidebarBurstThrottle,
    AnalyticsSidebarSustainedThrottle,
]
ANALYTICS_SIDEBAR_WRITES = ["set_analytics_sidebar", "reset_analytics_sidebar"]


class UICustomizationViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "user"
    scope_object_read_actions = ["analytics_sidebar"]
    scope_object_write_actions = ANALYTICS_SIDEBAR_WRITES

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action in ANALYTICS_SIDEBAR_WRITES:
            return [throttle() for throttle in ANALYTICS_SIDEBAR_THROTTLES]
        return super().get_throttles()

    def _customization_user(self) -> User:
        user = cast(User, self.request.user)
        if not api.is_enabled_for(user, self.team):
            raise NotFound()
        return user

    @validated_request(
        responses={200: OpenApiResponse(response=AnalyticsSidebarSerializer)},
        summary="Get the person's analytics sidebar",
        description="The layout of the Analytics pane in the new navigation: the person's own layout, or the default when they have not saved one. Read it before you change it, so you keep the sections the person wants. 404 when the person does not have UI customization enabled.",
    )
    @action(detail=False, methods=["get"], url_path="analytics_sidebar")
    def analytics_sidebar(self, request: Request, **kwargs) -> Response:
        found = api.get_analytics_sidebar(team=self.team, user=self._customization_user())
        return Response(AnalyticsSidebarSerializer(found).data)

    @validated_request(
        request_serializer=AnalyticsSidebarRequestSerializer,
        responses={200: OpenApiResponse(response=AnalyticsSidebarSerializer)},
        summary="Set the person's analytics sidebar",
        description="Replaces the layout of the person's Analytics pane. It changes only the person who calls it, in this project. The pane shows the new layout the next time it loads. 400 lists every value that does not fit the layout schema. 404 when the person does not have UI customization enabled.",
    )
    @analytics_sidebar.mapping.put
    def set_analytics_sidebar(self, request: Request, **kwargs) -> Response:
        saved = api.set_analytics_sidebar(
            team=self.team, user=self._customization_user(), layout=request.validated_data["layout"]
        )
        return Response(AnalyticsSidebarSerializer(saved).data)

    @validated_request(
        responses={200: OpenApiResponse(response=AnalyticsSidebarSerializer)},
        summary="Reset the person's analytics sidebar",
        description="Removes the person's own layout, so the Analytics pane shows the default again. Returns the default layout. 404 when the person does not have UI customization enabled.",
    )
    @analytics_sidebar.mapping.delete
    def reset_analytics_sidebar(self, request: Request, **kwargs) -> Response:
        default = api.reset_analytics_sidebar(team=self.team, user=self._customization_user())
        return Response(AnalyticsSidebarSerializer(default).data)
