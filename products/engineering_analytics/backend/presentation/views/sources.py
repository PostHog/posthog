"""The GitHub source/repo picker backing every other endpoint's scope."""

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.presentation.serializers.sources import GitHubSourceSerializer
from products.engineering_analytics.backend.presentation.views._base import EngineeringAnalyticsViewSetBase


class SourcesMixin(EngineeringAnalyticsViewSetBase):
    READ_ACTIONS = ["sources"]

    @extend_schema(
        operation_id="engineering_analytics_sources",
        responses={200: GitHubSourceSerializer(many=True)},
        description=(
            "The team's selectable GitHub repositories, oldest source first — one entry per repository a "
            "source is configured to sync, so a source syncing several repositories appears once per repo. "
            "Populate a repo picker from this and pass a chosen entry's `id` back as `source_id` and its "
            "`repo` back as `repo` to the other endpoints. Includes repositories whose tables aren't fully "
            "synced yet."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def sources(self, request: Request, **kwargs) -> Response:
        result = api.list_github_sources(team=self.team, user_access_control=self.user_access_control)
        return Response(GitHubSourceSerializer(instance=result, many=True).data)
