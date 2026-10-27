from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api


class MergePushSerializer(serializers.Serializer):
    commit_sha = serializers.RegexField(
        api.COMMIT_SHA_PATTERN, help_text="The 40-character SHA of the master merge commit."
    )


class MergePushResponseSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="Always accepted; the merge check runs in the background.")


class MergePushViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "knowledge_writer"
    scope_object_write_actions = ["create"]
    scope_object_read_actions: list[str] = []

    @extend_schema(
        request=MergePushSerializer,
        responses={202: OpenApiResponse(response=MergePushResponseSerializer)},
    )
    def create(self, request: Request, **kwargs) -> Response:
        if api.writer_team_id() != self.team_id:
            return Response({"detail": "The knowledge writer does not run in this project."}, status=404)
        merge_push = MergePushSerializer(data=request.data)
        merge_push.is_valid(raise_exception=True)
        api.record_merge_push(merge_push.validated_data["commit_sha"])
        return Response({"status": "accepted"}, status=status.HTTP_202_ACCEPTED)
