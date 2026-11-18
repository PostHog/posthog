from typing import cast
from uuid import UUID

from django.http import HttpResponse

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.config import WIZARD_GIT_DIFF_CONTENT_TYPE
from products.wizard.backend.facade.errors import (
    WizardRunArtifactNotFoundError,
    WizardRunArtifactTooLargeError,
    WizardRunNotFoundError,
)
from products.wizard.backend.presentation.artifacts.pagination import WizardRunArtifactPagination
from products.wizard.backend.presentation.artifacts.serializers import (
    WizardRunArtifactSchema,
    WizardRunArtifactSerializer,
    serialize_wizard_run_artifact,
)
from products.wizard.backend.presentation.permissions import WizardRunSessionAuthenticationRequired
from products.wizard.backend.presentation.runs.serializers import WizardRunErrorSerializer


class WizardRunArtifactTooLarge(APIException):
    status_code = 413
    default_detail = "This diff is too large to download. Open the pull request to review the full change."
    default_code = "wizard_run_artifact_too_large"


class WizardRunArtifactViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    permission_classes = [WizardRunSessionAuthenticationRequired]
    scope_object = "wizard_session"
    scope_object_read_actions = ["list", "content"]
    http_method_names = ["get", "head", "options"]
    pagination_class = WizardRunArtifactPagination
    serializer_class = WizardRunArtifactSerializer

    @extend_schema(
        responses={
            200: WizardRunArtifactSchema,
            404: OpenApiResponse(response=WizardRunErrorSerializer),
        },
        description="List metadata for artifacts produced by a Wizard run.",
    )
    # GET /projects/:projectId/wizard/runs/:runId/artifacts
    def list(self, request: Request, *args: object, **kwargs: object) -> Response:
        try:
            artifacts = wizard_facade.list_run_artifacts(self.team_id, self._run_id())

        except WizardRunNotFoundError:
            raise NotFound("No Wizard run was found for this project.")

        page = self.paginate_queryset(artifacts)

        if page is None:
            raise ValueError("Pagination returned None")

        return self.get_paginated_response([serialize_wizard_run_artifact(artifact) for artifact in page])

    @extend_schema(
        operation_id="wizard_runs_artifacts_content_retrieve",
        responses={
            (200, "text/x-diff"): OpenApiTypes.STR,
            404: OpenApiResponse(response=WizardRunErrorSerializer),
            413: OpenApiResponse(response=WizardRunErrorSerializer),
        },
        description="Get the unified git diff stored for a Wizard run artifact.",
    )
    @action(detail=True, methods=["get"], pagination_class=None)
    def content(self, request: Request, *args: object, **kwargs: object) -> HttpResponse:
        try:
            content = wizard_facade.get_git_diff_artifact_content(
                self.team_id,
                self._run_id(),
                self._artifact_id(),
            )
        except (WizardRunArtifactNotFoundError, WizardRunNotFoundError):
            raise NotFound("No git diff artifact was found for this Wizard run.")
        except WizardRunArtifactTooLargeError:
            raise WizardRunArtifactTooLarge from None

        response = HttpResponse(content, content_type=WIZARD_GIT_DIFF_CONTENT_TYPE)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    def _run_id(self) -> UUID:
        return UUID(cast(str, self.kwargs["parent_lookup_run_id"]))

    def _artifact_id(self) -> UUID:
        return UUID(cast(str, self.kwargs["pk"]))
