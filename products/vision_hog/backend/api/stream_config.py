from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.decorators import action


class StreamConfigViewSet(
    TeamAndOrgViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["GET"])
    def config_suggestion(self, request: Request, *args, **kwargs) -> Response:
        return Response({"message": "Hello, world!"})
