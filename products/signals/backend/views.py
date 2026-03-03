import json
import uuid
import logging
from typing import cast

from django.conf import settings
from django.db import IntegrityError
from django.db.models import Count, Q

from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import filters, serializers, status, viewsets
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
from products.signals.backend.models import (
    InvalidStatusTransition,
    SignalReport,
    SignalReportArtefact,
    SignalSourceConfig,
)
from products.signals.backend.serializers import (
    SignalReportArtefactSerializer,
    SignalReportSerializer,
    SignalSourceConfigSerializer,
)

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


class SignalSourceConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    serializer_class = SignalSourceConfigSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "INTERNAL"
    queryset = SignalSourceConfig.objects.all().order_by("-updated_at")

    def perform_create(self, serializer):
        try:
            serializer.save(team_id=self.team_id, created_by=self.request.user)
        except IntegrityError:
            raise serializers.ValidationError(
                {"source_product": "A configuration for this source product and type already exists for this team."}
            )

    def perform_update(self, serializer):
        try:
            serializer.save()
        except IntegrityError:
            raise serializers.ValidationError(
                {"source_product": "A configuration for this source product and type already exists for this team."}
            )


@extend_schema_view(
    list=extend_schema(exclude=True),
    retrieve=extend_schema(exclude=True),
)
class SignalReportViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = SignalReportSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    queryset = SignalReport.objects.all()
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["signal_count", "total_weight", "created_at", "updated_at"]
    ordering = ["-signal_count"]

    def safely_get_queryset(self, queryset):
        qs = queryset.filter(team=self.team).annotate(artefact_count=Count("artefacts"))
        # Deleted reports are terminal -- exclude from all endpoints (detail, list, actions)
        qs = qs.exclude(status=SignalReport.Status.DELETED)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status__in=[s.strip() for s in status_filter.split(",") if s.strip()])
        else:
            qs = qs.exclude(status=SignalReport.Status.SUPPRESSED)
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(summary__icontains=search))
        return qs

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team}

    @extend_schema(exclude=True)
    @action(detail=True, methods=["get"], url_path="artefacts", required_scopes=["task:read"])
    def artefacts(self, request, pk=None, **kwargs):
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

    @extend_schema(exclude=True)
    @action(detail=True, methods=["get"], url_path="signals", required_scopes=["task:read"])
    def signals(self, request, pk=None, **kwargs):
        """Fetch all signals for a report from ClickHouse, including full metadata."""
        report = self.get_object()
        report_data = SignalReportSerializer(report).data

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
              AND NOT JSONExtractBool(metadata, 'deleted')
            ORDER BY timestamp ASC
        """

        result = execute_hogql_query(
            query_type="SignalsDebugFetchForReport",
            query=query,
            team=self.team,
            placeholders={
                "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
                "report_id": ast.Constant(value=str(report.id)),
            },
        )

        signals_list = []
        for row in result.results or []:
            document_id, content, metadata_str, timestamp = row
            metadata = json.loads(metadata_str)
            signals_list.append(
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

        return Response({"report": report_data, "signals": signals_list})

    @extend_schema(exclude=True)
    @action(detail=True, methods=["post"], url_path="state", required_scopes=["task:write"])
    def state(self, request, pk=None, **kwargs):
        """
        Transition a report to a new state. The model validates allowed transitions.

        Body: { "state": "suppressed" | "potential", ...kwargs passed to transition_to }
        """
        report = cast(SignalReport, self.get_object())

        target = request.data.get("state")
        if target not in ("suppressed", "potential"):
            return Response(
                {"error": "state must be one of ['suppressed', 'potential']"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        transition_kwargs = {k: v for k, v in request.data.items() if k != "state"}
        try:
            updated_fields = report.transition_to(SignalReport.Status(target), **transition_kwargs)
        except InvalidStatusTransition as e:
            logger.warning("Invalid status transition for SignalReport %s: %s", report.id, e, exc_info=True)
            return Response(
                {"error": "Invalid state transition for this report."},
                status=status.HTTP_409_CONFLICT,
            )
        except (ValueError, TypeError) as e:
            logger.warning("Invalid data when transitioning SignalReport %s: %s", report.id, e, exc_info=True)
            return Response(
                {"error": "Invalid data for state transition."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        report.save(update_fields=updated_fields)

        return Response(SignalReportSerializer(report, context=self.get_serializer_context()).data)
