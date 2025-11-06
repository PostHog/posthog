from typing import Any

from rest_framework import viewsets
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.integration import IntegrationSerializer
from posthog.api.utils import action
from posthog.models.integration import Integration, SlackIntegration, SlackIntegrationError

from products.enterprise.backend.tasks.slack import handle_slack_event


class PublicIntegrationViewSet(viewsets.GenericViewSet):
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer

    authentication_classes = []
    permission_classes = []

    @action(methods=["POST"], detail=False, url_path="slack/events")
    def slack_events(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            SlackIntegration.validate_request(request)
        except SlackIntegrationError:
            raise AuthenticationFailed()

        if request.data["type"] == "url_verification":
            return Response({"challenge": request.data["challenge"]})

        handle_slack_event(request.data)

        return Response({"status": "ok"})
