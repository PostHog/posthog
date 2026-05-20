"""
DRF views for wizard.

Validates JSON via serializers, routes everything through the facade,
returns DTO-shaped responses. No model imports.
"""

import dataclasses
from typing import Any

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import UpsertWizardSessionInput, UpsertWizardSessionRequest
from products.wizard.backend.presentation.serializers import (
    UpsertWizardSessionRequestSerializer,
    WizardSessionSerializer,
)


class WizardSessionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "wizard_session"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["create"]
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"[^/]+"

    @extend_schema(
        description=(
            "List wizard sessions for the project, ordered by started_at desc. "
            "Optional filters: ?workflow_id=<id> and ?skill_id=<id>."
        ),
        responses={200: WizardSessionSerializer(many=True)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        sessions = wizard_facade.list_for_team(
            self.team_id,
            workflow_id=request.query_params.get("workflow_id"),
            skill_id=request.query_params.get("skill_id"),
        )
        page = self.paginate_queryset(sessions)
        if page is not None:
            return self.get_paginated_response(WizardSessionSerializer(page, many=True).data)
        return Response(WizardSessionSerializer(sessions, many=True).data)

    @extend_schema(
        description="Retrieve a single wizard session by its session_id.",
        parameters=[OpenApiParameter(name="session_id", location=OpenApiParameter.PATH, type=str)],
        responses={
            200: WizardSessionSerializer,
            404: OpenApiResponse(description="No session with that id for this project."),
        },
    )
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        session_id = kwargs.get("pk")
        if not session_id:
            return Response({"detail": "session_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        dto = wizard_facade.get(self.team_id, session_id)
        if dto is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(WizardSessionSerializer(dto).data)

    @extend_schema(
        description=(
            "Upsert a wizard session. The session_id key determines whether this "
            "creates a new row or replaces an existing one. Always returns 201."
        ),
        request=UpsertWizardSessionRequestSerializer,
        responses={201: WizardSessionSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = UpsertWizardSessionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        req: UpsertWizardSessionRequest = serializer.save()

        dto = wizard_facade.upsert(UpsertWizardSessionInput(team_id=self.team_id, **dataclasses.asdict(req)))
        return Response(WizardSessionSerializer(dto).data, status=status.HTTP_201_CREATED)
