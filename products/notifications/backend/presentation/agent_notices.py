from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.notifications.backend.facade.api import list_active_agent_notices
from products.notifications.backend.presentation.serializers import AgentNoticeSerializer


class AgentNoticeViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Read-only feed of staff-authored notices for the project's AI agent sessions."""

    scope_object = "project"
    serializer_class = AgentNoticeSerializer
    pagination_class = None

    @extend_schema(
        responses={200: AgentNoticeSerializer(many=True)},
        description="Active agent notices for this project (staff-authored, time-windowed), newest first, capped at 5.",
    )
    def list(self, request: Request, **kwargs) -> Response:
        notices = list_active_agent_notices(team_id=self.team.id)
        return Response(AgentNoticeSerializer(notices, many=True).data)
