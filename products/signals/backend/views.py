import json
import math
from typing import Any, cast

from django.db.models import Count

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission

from .models import SignalReport
from .serializers import SignalReportArtefactSerializer, SignalReportDebugSerializer, SignalReportSerializer


@extend_schema(tags=["signal-reports"])
class SignalReportViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API for reading signal reports. Reports are auto-generated from video segment clustering.
    """

    serializer_class = SignalReportSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    scope_object = "task"  # Using task scope as signal_report doesn't have its own scope yet
    queryset = SignalReport.objects.all()
    posthog_feature_flag = {
        "product-autonomy": [
            "list",
            "retrieve",
            "artefacts",
            "debug",
        ]
    }

    def safely_get_queryset(self, queryset):
        qs = (
            queryset.filter(
                team=self.team,
                status=SignalReport.Status.READY,
            )
            .annotate(artefact_count=Count("artefacts"))
            .order_by("-total_weight", "-updated_at")
        )

        return qs

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team}

    @extend_schema(
        responses={
            200: OpenApiResponse(description="List of artefacts for the report"),
            404: OpenApiResponse(description="Report not found"),
        },
        summary="List report artefacts",
        description="Get list of artefacts for a signal report.",
    )
    @action(detail=True, methods=["get"], url_path="artefacts", required_scopes=["task:read"])
    def artefacts(self, request, pk=None, **kwargs):
        report = cast(SignalReport, self.get_object())
        artefacts = report.artefacts.filter(type="video_segment").order_by("-created_at")
        serializer = SignalReportArtefactSerializer(artefacts, many=True)
        return Response(
            {
                "results": serializer.data,
                "count": len(serializer.data),
            }
        )

    @extend_schema(
        responses={
            200: SignalReportDebugSerializer,
            403: OpenApiResponse(description="Staff only"),
            404: OpenApiResponse(description="Report not found"),
        },
        summary="Debug trace for a report",
        description="Staff-only endpoint returning pipeline metadata, segment embeddings, and session export info.",
    )
    @action(detail=True, methods=["get"], url_path="debug", required_scopes=["task:read"])
    def debug(self, request, pk=None, **kwargs):
        if not (request.user.is_staff or getattr(request.user, "is_impersonated", False)):
            raise PermissionDenied("Staff access required.")

        report = cast(SignalReport, self.get_object())

        # Gather artefacts to extract session_ids and document_ids
        artefacts = report.artefacts.filter(type="video_segment").order_by("-created_at")
        session_ids: set[str] = set()
        document_ids: list[str] = []

        for artefact in artefacts:
            try:
                content_bytes = (
                    bytes(artefact.content) if isinstance(artefact.content, memoryview) else artefact.content
                )
                content = json.loads(content_bytes.decode("utf-8"))
                if content.get("session_id"):
                    session_ids.add(content["session_id"])
                # Reconstruct document_id from artefact content
                if content.get("session_id") and content.get("start_time") and content.get("end_time"):
                    document_ids.append(f"{content['session_id']}:{content['start_time']}:{content['end_time']}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        segments = _fetch_segment_debug_data(self.team, document_ids, report.cluster_centroid)
        sessions = _fetch_session_export_data(self.team, list(session_ids))

        serializer = SignalReportDebugSerializer(
            {
                "id": report.id,
                "title": report.title,
                "summary": report.summary,
                "status": report.status,
                "total_weight": report.total_weight,
                "signal_count": report.signal_count,
                "relevant_user_count": report.relevant_user_count,
                "created_at": report.created_at,
                "updated_at": report.updated_at,
                "pipeline_metadata": report.pipeline_metadata,
                "segments": segments,
                "sessions": sessions,
            }
        )
        return Response(serializer.data)


def _fetch_segment_debug_data(
    team,
    document_ids: list[str],
    cluster_centroid: list[float] | None,
) -> list[dict[str, Any]]:
    """Fetch segment data from ClickHouse and compute distances to centroid."""
    if not document_ids:
        return []

    from posthog.hogql import ast
    from posthog.hogql.parser import parse_select
    from posthog.hogql.query import execute_hogql_query

    result = execute_hogql_query(
        query_type="SignalReportDebugSegments",
        query=parse_select(
            """
            SELECT
                document_id,
                content,
                embedding,
                metadata,
                timestamp
            FROM raw_document_embeddings
            WHERE document_id IN {doc_ids}
                AND product = {product}
                AND document_type = {document_type}
                AND rendering = {rendering}
            LIMIT 500"""
        ),
        placeholders={
            "doc_ids": ast.Constant(value=document_ids),
            "product": ast.Constant(value="session-replay"),
            "document_type": ast.Constant(value="video-segment"),
            "rendering": ast.Constant(value="video-analysis"),
        },
        team=team,
    )

    segments: list[dict[str, Any]] = []
    for row in result.results or []:
        doc_id, content, embedding, metadata_str, timestamp = row
        try:
            metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else (metadata_str or {})
        except (json.JSONDecodeError, TypeError):
            metadata = {}

        centroid_distance = None
        if cluster_centroid and embedding and len(embedding) > 0:
            centroid_distance = _cosine_distance(embedding, cluster_centroid)

        segments.append(
            {
                "document_id": doc_id,
                "content": content,
                "session_id": metadata.get("session_id"),
                "timestamp": timestamp.isoformat() if timestamp else None,
                "centroid_distance": centroid_distance,
            }
        )

    # Sort by centroid distance ascending (closest first)
    segments.sort(key=lambda s: s.get("centroid_distance") or float("inf"))
    return segments


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Compute cosine distance between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return 1.0 - dot / (norm_a * norm_b)


def _fetch_session_export_data(team, session_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch video export info from ExportedAsset for given session IDs."""
    if not session_ids:
        return []

    from posthog.models.exported_asset import ExportedAsset

    sessions: list[dict[str, Any]] = []
    for session_id in session_ids:
        assets = ExportedAsset.objects_including_ttl_deleted.filter(
            team=team,
            export_context__session_recording_id=session_id,
        ).order_by("-created_at")[:5]

        exports = []
        for asset in assets:
            exports.append(
                {
                    "id": asset.id,
                    "export_format": asset.export_format,
                    "created_at": asset.created_at.isoformat() if asset.created_at else None,
                    "content_location": asset.content_location,
                    "expires_after": asset.expires_after.isoformat() if asset.expires_after else None,
                }
            )

        sessions.append(
            {
                "session_id": session_id,
                "exports": exports,
            }
        )

    return sessions
