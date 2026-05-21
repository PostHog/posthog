"""
DRF views for wizard.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from typing import Any

from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.wizard.backend.facade.api import WizardSessionAPI
from products.wizard.backend.facade.contracts import UpsertWizardSessionInput, WizardTaskDTO
from products.wizard.backend.facade.enums import RunPhase, TaskStatus
from products.wizard.backend.models import WizardSession
from products.wizard.backend.presentation.serializers import WizardSessionSerializer


class WizardSessionViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "wizard_session"
    serializer_class = WizardSessionSerializer
    queryset = WizardSession.objects.unscoped()  # type: ignore[attr-defined]
    lookup_field = "session_id"
    http_method_names = ["get", "post", "head", "options"]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        qs = queryset.filter(team_id=self.team_id)
        workflow_id = self.request.query_params.get("workflow_id")
        skill_id = self.request.query_params.get("skill_id")

        if workflow_id:
            qs = qs.filter(workflow_id=workflow_id)

        if skill_id:
            qs = qs.filter(skill_id=skill_id)

        return qs.order_by("-started_at")

    @extend_schema(
        description=(
            "List wizard sessions for the project, ordered by started_at desc. "
            "Optional filters: ?workflow_id=<id> and ?skill_id=<id>."
        )
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(description="Retrieve a single wizard session by its session_id.")
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        description=(
            "Upsert a wizard session. The session_id key determines whether this "
            "creates a new row or replaces an existing one."
        )
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        dto = WizardSessionAPI.upsert(
            UpsertWizardSessionInput(
                team_id=self.team_id,
                session_id=data["session_id"],
                workflow_id=data["workflow_id"],
                skill_id=data["skill_id"],
                started_at=data["started_at"],
                run_phase=RunPhase(data["run_phase"]),
                tasks=tuple(
                    WizardTaskDTO(
                        id=task["id"],
                        title=task["title"],
                        status=TaskStatus(task["status"]),
                    )
                    for task in data["tasks"]
                ),
                event_plan=data.get("event_plan"),
                error=data.get("error"),
            )
        )

        instance = WizardSession.objects.get(team_id=dto.team_id, session_id=dto.session_id)
        return Response(self.get_serializer(instance).data, status=201)
