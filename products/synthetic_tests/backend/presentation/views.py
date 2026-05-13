"""DRF views for synthetic_tests."""

from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.synthetic_tests.backend.logic.execution import execute_synthetic_test
from products.synthetic_tests.backend.logic.playwright_converter import steps_to_playwright
from products.synthetic_tests.backend.logic.replay_to_steps import generate_steps_from_replay
from products.synthetic_tests.backend.models import SyntheticTest, SyntheticTestRun

from .serializers import (
    GenerateFromReplayRequestSerializer,
    GenerateFromReplayResponseSerializer,
    SyntheticTestRunSerializer,
    SyntheticTestSerializer,
)


class SyntheticTestViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = SyntheticTest.objects.all()
    serializer_class = SyntheticTestSerializer

    def safely_get_queryset(self, queryset: QuerySet[SyntheticTest]) -> QuerySet[SyntheticTest]:
        return queryset.filter(team_id=self.team_id).order_by("-created_at")

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        serializer.save(
            team_id=self.team_id,
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )

    @extend_schema(
        request=None,
        responses=SyntheticTestRunSerializer,
        description="Trigger an immediate synchronous run of this synthetic test (does not wait for the next scheduled tick).",
    )
    @action(detail=True, methods=["post"])
    def run_now(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        test: SyntheticTest = self.get_object()
        run = execute_synthetic_test(test)
        return Response(SyntheticTestRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        request=None,
        responses=SyntheticTestSerializer,
        description="Pause the test so the scheduler stops picking it up.",
    )
    @action(detail=True, methods=["post"])
    def pause(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        test: SyntheticTest = self.get_object()
        test.status = SyntheticTest.Status.PAUSED
        test.next_run_at = None
        test.save(update_fields=["status", "next_run_at", "updated_at"])
        return Response(self.get_serializer(test).data)

    @extend_schema(
        request=None,
        responses=SyntheticTestSerializer,
        description="Resume a paused test; the scheduler will pick it up on the next tick.",
    )
    @action(detail=True, methods=["post"])
    def resume(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        test: SyntheticTest = self.get_object()
        test.status = SyntheticTest.Status.ACTIVE
        test.next_run_at = timezone.now()
        test.save(update_fields=["status", "next_run_at", "updated_at"])
        return Response(self.get_serializer(test).data)

    @extend_schema(
        request=None,
        responses={"200": {"type": "object", "properties": {"script": {"type": "string"}}}},
        description="Return the compiled Playwright Python script for this test. Read-only preview.",
    )
    @action(detail=True, methods=["get"], url_path="playwright_script")
    def playwright_script(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        test: SyntheticTest = self.get_object()
        script = steps_to_playwright(test.steps, target_url=test.target_url)
        return Response({"script": script})

    @extend_schema(
        request=GenerateFromReplayRequestSerializer,
        responses=GenerateFromReplayResponseSerializer,
        description=(
            "Convert a session recording into a draft synthetic test step list. "
            "Returns suggested name, target URL, and steps — the client should let the user "
            "review and edit before persisting via the standard create endpoint."
        ),
    )
    @action(detail=False, methods=["post"], url_path="generate_from_replay")
    def generate_from_replay(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        request_ser = GenerateFromReplayRequestSerializer(data=request.data)
        request_ser.is_valid(raise_exception=True)
        result = generate_steps_from_replay(
            team_id=self.team_id,
            session_recording_id=request_ser.validated_data["session_recording_id"],
        )
        response_ser = GenerateFromReplayResponseSerializer(result)
        return Response(response_ser.data)


class SyntheticTestRunViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"
    queryset = SyntheticTestRun.objects.all()
    serializer_class = SyntheticTestRunSerializer

    def safely_get_queryset(self, queryset: QuerySet[SyntheticTestRun]) -> QuerySet[SyntheticTestRun]:
        qs = queryset.filter(synthetic_test__team_id=self.team_id)
        test_id = self.request.query_params.get("synthetic_test")
        if test_id:
            qs = qs.filter(synthetic_test_id=test_id)
        return qs.order_by("-started_at")
