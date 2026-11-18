from typing import cast

from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models import User
from posthog.permissions import APIScopePermission

from products.signals.backend.facade.inbox_status import FirstReportStatus, InboxSetupState, get_inbox_status
from products.signals.backend.presentation.scout_permissions import ScoutCanonicalTeamAccessPermission


@extend_schema_serializer(many=False)
class InboxStatusSerializer(serializers.Serializer):
    setup_state = serializers.ChoiceField(choices=InboxSetupState.choices, help_text="Current project setup state.")
    has_report_history = serializers.BooleanField(
        help_text="Whether a report has surfaced in this project, including reports already handled or assigned to someone else."
    )
    first_report_status = serializers.ChoiceField(
        choices=FirstReportStatus.choices,
        allow_null=True,
        help_text="First investigation outcome, when known and the project has no report history. Does not expose scout run details.",
    )
    can_configure = serializers.BooleanField(
        help_text="Whether the user has inbox and scout configuration access on the web. Integration and organization settings may require additional permissions."
    )


class InboxStatusViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = InboxStatusSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, ScoutCanonicalTeamAccessPermission]
    scope_object = "inbox"
    requires_resource_level_access = True
    pagination_class = None

    @extend_schema(responses=InboxStatusSerializer)
    def list(self, request: Request, **kwargs: object) -> Response:
        return Response(
            InboxStatusSerializer(get_inbox_status(team_id=self.team_id, user_id=cast(User, request.user).pk)).data
        )
