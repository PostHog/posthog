"""DRF views for founder_mode.

The viewset wires CRUD on FounderProject and the validation kickoff action.
Real route registration lives in `posthog/api/__init__.py` — see the
`founder_projects` register call there. presentation/urls.py is a stub kept
for documentation symmetry with other isolated products.
"""

from typing import Any

from django.db import transaction
from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.founder_mode.backend.models import FounderProject
from products.founder_mode.backend.tasks.tasks import run_landing_page_task, run_validation_task

from .serializers import FounderProjectSerializer


@extend_schema(tags=["founder_mode"])
class FounderProjectViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    # TODO: promote to a real "founder_project" scope object in posthog/scopes.py + frontend
    # mirrors before this exits alpha. "INTERNAL" works because the product is hackathon-only
    # and not yet exposed via personal API keys / OAuth.
    scope_object = "INTERNAL"
    serializer_class = FounderProjectSerializer
    queryset = FounderProject.objects.all()

    def safely_get_queryset(self, queryset: QuerySet[FounderProject]) -> QuerySet[FounderProject]:
        return queryset.filter(team_id=self.team_id)

    def perform_create(self, serializer: FounderProjectSerializer) -> None:
        instance = serializer.save(team_id=self.team_id, created_by=self.request.user)
        # Fire validation immediately if the create included an ideation payload — saves the
        # founder a round-trip when they paste stage 1 results into a new project.
        if instance.ideation:
            user_id = self.request.user.id
            transaction.on_commit(lambda: run_validation_task.delay(str(instance.id), user_id))

    def perform_update(self, serializer: FounderProjectSerializer) -> None:
        # Snapshot before save so we can detect whether ideation actually changed.
        # Without this we'd re-run validation on every PATCH (e.g. when stage 3 writes gtm).
        previous_ideation = serializer.instance.ideation
        instance = serializer.save()
        if instance.ideation and instance.ideation != previous_ideation:
            user_id = self.request.user.id
            transaction.on_commit(lambda: run_validation_task.delay(str(instance.id), user_id))

    @extend_schema(
        responses={202: FounderProjectSerializer},
        description=(
            "Manually re-run validation against the current ideation payload. Returns the "
            "FounderProject with `validation.status` set to running. Poll the detail endpoint "
            "until status is `completed` or `failed`."
        ),
    )
    @action(detail=True, methods=["POST"], url_path="run_validation")
    def run_validation(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: FounderProject = self.get_object()
        if not instance.ideation:
            return Response(
                {"detail": "Cannot run validation: ideation is empty."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user_id = request.user.id
        transaction.on_commit(lambda: run_validation_task.delay(str(instance.id), user_id))
        # The task will flip status to running before its first save, but we eagerly mark it
        # here so the response the founder sees doesn't briefly show stale `completed` state.
        instance.validation = {**(instance.validation or {}), "status": "pending"}
        instance.save(update_fields=["validation", "updated_at"])
        return Response(self.get_serializer(instance).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        responses={202: FounderProjectSerializer},
        description=(
            "Generate (or re-generate) the stage 4 landing page from the project's ideation, "
            "validation report, and GTM. Returns the FounderProject with `mvp.status` set to "
            "running. Poll the detail endpoint until status is `completed` or `failed`."
        ),
    )
    @action(detail=True, methods=["POST"], url_path="run_landing_page")
    def run_landing_page(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: FounderProject = self.get_object()
        if not instance.ideation:
            return Response(
                {"detail": "Cannot generate landing page: ideation is empty."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user_id = request.user.id
        transaction.on_commit(lambda: run_landing_page_task.delay(str(instance.id), user_id))
        instance.mvp = {**(instance.mvp or {}), "status": "pending"}
        instance.save(update_fields=["mvp", "updated_at"])
        return Response(self.get_serializer(instance).data, status=status.HTTP_202_ACCEPTED)
