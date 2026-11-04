"""The product opt-in: creates the team's managed viewset, which every background job gates on."""

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.presentation.serializers.enrollment import EnrollmentSerializer
from products.engineering_analytics.backend.presentation.views._base import EngineeringAnalyticsViewSetBase


class EnrollmentMixin(EngineeringAnalyticsViewSetBase):
    WRITE_ACTIONS = ["enable"]

    @extend_schema(
        operation_id="engineering_analytics_enable",
        request=None,
        responses={200: EnrollmentSerializer},
        description=(
            "Enable engineering analytics for this project. Creates the project's managed warehouse views "
            "and opts it into the background work (view sync after each GitHub or Depot load, the daily "
            "test census, CI failure log collection). Safe to call again: an enabled project stays enabled."
        ),
    )
    @action(detail=False, methods=["post"], pagination_class=None)
    def enable(self, request: Request, **kwargs) -> Response:
        return Response(EnrollmentSerializer(instance=api.enable(team=self.team)).data)
