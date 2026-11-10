from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import RecordWizardScanInput, WizardScanSignal, WizardScanTool
from products.wizard.backend.presentation.scans.serializers import (
    ListDetectedWarehouseSourcesQuerySerializer,
    RecordWizardScanRequestSerializer,
    WizardDetectedWarehouseSourceSerializer,
    WizardScanResultSerializer,
)


class WizardScanViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "wizard_session"
    scope_object_read_actions = ["detected_sources"]
    scope_object_write_actions = ["create"]
    http_method_names = ["get", "post", "options"]

    @validated_request(
        request_serializer=RecordWizardScanRequestSerializer,
        responses={
            201: OpenApiResponse(response=WizardScanResultSerializer, description="The scan was stored."),
            200: OpenApiResponse(
                response=WizardScanResultSerializer, description="This session already reported its scan."
            ),
        },
        summary="Record the tools a wizard scan found in a codebase",
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        data = request.validated_data
        user = getattr(request, "user", None)
        result = wizard_facade.record_scan(
            RecordWizardScanInput(
                team_id=self.team_id,
                created_by_id=user.id if user is not None and not user.is_anonymous else None,
                session_id=data["session_id"],
                program=data["program"],
                wizard_version=data["wizard_version"],
                workspace_fingerprint=data["workspace_fingerprint"],
                scanned_at=data["scanned_at"],
                complete=data["complete"],
                tools=tuple(
                    WizardScanTool(
                        kind=tool["kind"],
                        signals=tuple(
                            WizardScanSignal(source=signal["source"], name=signal["name"], file=signal["file"])
                            for signal in tool["signals"]
                        ),
                    )
                    for tool in data["tools"]
                ),
            )
        )
        return Response(
            WizardScanResultSerializer(result).data,
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )

    @validated_request(
        query_serializer=ListDetectedWarehouseSourcesQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=WizardDetectedWarehouseSourceSerializer(many=True),
                description="Detected warehouse sources, most recently seen first.",
            ),
        },
        summary="List the data warehouse sources wizard scans found in this project's codebases",
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def detected_sources(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        sources = wizard_facade.list_detected_warehouse_sources(
            self.team_id, seen_since=request.validated_query_data.get("seen_since")
        )
        return Response(WizardDetectedWarehouseSourceSerializer(sources, many=True).data)
