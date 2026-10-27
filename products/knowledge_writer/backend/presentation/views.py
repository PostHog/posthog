from drf_spectacular.utils import OpenApiResponse, extend_schema
from pydantic import TypeAdapter, ValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api
from ..facade.contracts import MergeCheckReport

_merge_report_validator = TypeAdapter(MergeCheckReport)


class MergeCheckReportSerializer(serializers.Serializer):
    commit_sha = serializers.CharField(help_text="The 40-character SHA of the master merge commit.")
    commit_url = serializers.URLField(help_text="The merge commit on GitHub.")
    title = serializers.CharField(help_text="The merged pull request's title.")
    needs_docs = serializers.BooleanField(help_text="Whether the merge check judged the docs out of date.")
    reason = serializers.CharField(help_text="Why the merge check decided as it did.")
    change_kind = serializers.ChoiceField(
        choices=["update", "create", "remove"], required=False, allow_null=True, help_text="The docs change needed."
    )
    page_urls = serializers.ListField(
        child=serializers.CharField(), max_length=3, required=False, help_text="Up to three docs pages to change."
    )
    evidence = serializers.CharField(required=False, allow_blank=True, help_text="What the merge check saw.")


class MergeVerdictResponseSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="What intake did with the verdict.")


class MergeVerdictViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "knowledge_writer"
    scope_object_write_actions = ["create"]
    scope_object_read_actions: list[str] = []

    @extend_schema(
        request=MergeCheckReportSerializer,
        responses={200: OpenApiResponse(response=MergeVerdictResponseSerializer)},
    )
    def create(self, request: Request, **kwargs) -> Response:
        if api.writer_team_id() != self.team_id:
            return Response({"detail": "The knowledge writer does not run in this project."}, status=404)
        try:
            report = _merge_report_validator.validate_python(request.data)
        except ValidationError as error:
            return Response({"detail": error.errors(include_url=False)}, status=status.HTTP_400_BAD_REQUEST)
        outcome = api.submit_merge_report(report, team_id=self.team_id)
        return Response({"status": outcome.status})
