import hashlib
from typing import Any

from django.db.models import Max

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.mindmap.backend.api.postit import MindMapPostItSerializer
from products.mindmap.backend.models import MindMapEdge, MindMapPostIt


def _compute_version(team_id: int) -> str:
    postit_qs = MindMapPostIt.objects.filter(team_id=team_id, deleted=False)
    edge_qs = MindMapEdge.objects.filter(team_id=team_id)
    postit_latest = postit_qs.aggregate(latest=Max("last_modified_at"))["latest"]
    edge_latest = edge_qs.aggregate(latest=Max("created_at"))["latest"]
    postit_count = postit_qs.count()
    edge_count = edge_qs.count()
    seed = f"{postit_latest}|{postit_count}|{edge_latest}|{edge_count}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


class MindMapStateViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "mindmap"
    # GenericViewSet still requires a queryset for permission/router introspection.
    queryset = MindMapPostIt.objects.none()

    @extend_schema(
        responses={200: OpenApiResponse(description="Full mindmap state for the team")},
    )
    @action(detail=False, methods=["get"], url_path="state")
    def state(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        version = _compute_version(self.team.pk)
        etag = f'"{version}"'
        if request.headers.get("If-None-Match") == etag:
            return Response(status=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

        postits = list(MindMapPostIt.objects.filter(team=self.team, deleted=False).order_by("created_at"))
        edges = list(
            MindMapEdge.objects.filter(team=self.team).select_related("source", "target").order_by("created_at")
        )
        body = {
            "postits": MindMapPostItSerializer(postits, many=True, context={"request": request}).data,
            "edges": [{"source": e.source.short_id, "target": e.target.short_id} for e in edges],
            "version": version,
        }
        return Response(body, headers={"ETag": etag})
