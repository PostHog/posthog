import json
import uuid
import logging

from django.conf import settings

from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission

from products.signals.backend.api import emit_signal
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.serializers import SignalReportArtefactSerializer, SignalReportSerializer

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536


class EmitSignalSerializer(serializers.Serializer):
    source_product = serializers.CharField(max_length=100)
    source_type = serializers.CharField(max_length=100)
    description = serializers.CharField()
    weight = serializers.FloatField(default=0.5, min_value=0.0, max_value=1.0)
    extra = serializers.DictField(required=False, default=dict)


# Simple debug view, to make testing out the flow easier. Disabled in production.
class SignalViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    @extend_schema(exclude=True)
    @action(methods=["POST"], detail=False)
    def emit(self, request: Request, *args, **kwargs):
        if not settings.DEBUG:
            raise NotFound()

        serializer = EmitSignalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        async_to_sync(emit_signal)(
            team=self.team,
            source_product=data["source_product"],
            source_type=data["source_type"],
            source_id=str(uuid.uuid4()),
            description=data["description"],
            weight=data["weight"],
            extra=data["extra"],
        )

        return Response({"status": "ok"}, status=status.HTTP_202_ACCEPTED)

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=False, url_path="report_signals")
    def report_signals(self, request: Request, *args, **kwargs):
        """Fetch all signals for a report from ClickHouse, including full metadata. DEBUG only."""
        if not settings.DEBUG:
            raise NotFound()

        report_id = request.query_params.get("report_id")
        if not report_id:
            return Response({"error": "report_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Fetch the report from Postgres for context
        report_data = None
        try:
            report = SignalReport.objects.get(id=report_id, team=self.team)
            report_data = {
                "id": str(report.id),
                "title": report.title,
                "summary": report.summary,
                "status": report.status,
                "total_weight": report.total_weight,
                "signal_count": report.signal_count,
                "created_at": report.created_at.isoformat() if report.created_at else None,
                "updated_at": report.updated_at.isoformat() if report.updated_at else None,
            }
        except SignalReport.DoesNotExist:
            pass

        # Fetch signals from ClickHouse
        query = """
            SELECT
                document_id,
                content,
                metadata,
                toString(timestamp) as timestamp
            FROM (
                SELECT
                    document_id,
                    argMax(content, inserted_at) as content,
                    argMax(metadata, inserted_at) as metadata,
                    argMax(timestamp, inserted_at) as timestamp
                FROM document_embeddings
                WHERE model_name = {model_name}
                  AND product = 'signals'
                  AND document_type = 'signal'
                GROUP BY document_id
            )
            WHERE JSONExtractString(metadata, 'report_id') = {report_id}
            ORDER BY timestamp ASC
        """

        result = execute_hogql_query(
            query_type="SignalsDebugFetchForReport",
            query=query,
            team=self.team,
            placeholders={
                "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
                "report_id": ast.Constant(value=report_id),
            },
        )

        signals = []
        for row in result.results or []:
            document_id, content, metadata_str, timestamp = row
            metadata = json.loads(metadata_str)
            signals.append(
                {
                    "signal_id": document_id,
                    "content": content,
                    "source_product": metadata.get("source_product", ""),
                    "source_type": metadata.get("source_type", ""),
                    "source_id": metadata.get("source_id", ""),
                    "weight": metadata.get("weight", 0.0),
                    "timestamp": timestamp,
                    "extra": metadata.get("extra", {}),
                    "match_metadata": metadata.get("match_metadata"),
                }
            )

        return Response({"report": report_data, "signals": signals})


@extend_schema_view(
    list=extend_schema(exclude=True),
    retrieve=extend_schema(exclude=True),
)
class SignalReportViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = SignalReportSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"  # Using task scope as signal_report doesn't have its own scope yet
    queryset = SignalReport.objects.all()

    def safely_get_queryset(self, queryset):
        from django.db.models import Count

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

    @extend_schema(exclude=True)
    @action(detail=True, methods=["get"], url_path="artefacts", required_scopes=["signal_report:read"])
    def artefacts(self, request, pk=None, **kwargs):
        from typing import cast

        report = cast(SignalReport, self.get_object())
        artefacts = report.artefacts.filter(type=SignalReportArtefact.ArtefactType.VIDEO_SEGMENT).order_by(
            "-created_at"
        )
        serializer = SignalReportArtefactSerializer(artefacts, many=True)
        return Response(
            {
                "results": serializer.data,
                "count": len(serializer.data),
            }
        )
