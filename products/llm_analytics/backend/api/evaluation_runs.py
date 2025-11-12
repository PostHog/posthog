import time
import asyncio

from django.conf import settings

import structlog
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.temporal.common.client import sync_connect
from posthog.temporal.llm_analytics.run_evaluation import RunEvaluationInputs

from ..models.evaluations import Evaluation

logger = structlog.get_logger(__name__)


class EvaluationRunRequestSerializer(serializers.Serializer):
    evaluation_id = serializers.UUIDField(required=True)
    target_event_id = serializers.UUIDField(required=True)
    timestamp = serializers.DateTimeField(required=True)


class EvaluationRunViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "evaluation"
    permission_classes = [IsAuthenticated]

    def create(self, request: Request, **kwargs) -> Response:
        """
        Create a new evaluation run.

        This endpoint validates the request and enqueues a Temporal workflow
        to asynchronously execute the evaluation.
        """
        serializer = EvaluationRunRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)

        evaluation_id = str(serializer.validated_data["evaluation_id"])
        target_event_id = str(serializer.validated_data["target_event_id"])
        timestamp = serializer.validated_data["timestamp"].isoformat()

        # Verify evaluation exists and belongs to this team
        try:
            evaluation = Evaluation.objects.get(id=evaluation_id, team_id=self.team_id, deleted=False)
        except Evaluation.DoesNotExist:
            return Response({"error": f"Evaluation {evaluation_id} not found"}, status=404)

        # Build workflow inputs
        inputs = RunEvaluationInputs(
            evaluation_id=evaluation_id,
            target_event_id=target_event_id,
            timestamp=timestamp,
        )

        # Generate unique workflow ID
        workflow_id = f"{evaluation_id}-{target_event_id}-manual-{int(time.time() * 1000)}"

        # Start Temporal workflow
        try:
            client = sync_connect()
            asyncio.run(
                client.start_workflow(
                    "run-evaluation",
                    inputs,
                    id=workflow_id,
                    task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            )

            logger.info(
                "Started evaluation workflow",
                workflow_id=workflow_id,
                evaluation_id=evaluation_id,
                target_event_id=target_event_id,
                team_id=self.team_id,
            )

            return Response(
                {
                    "workflow_id": workflow_id,
                    "status": "started",
                    "evaluation": {
                        "id": str(evaluation.id),
                        "name": evaluation.name,
                    },
                    "target_event_id": target_event_id,
                },
                status=202,
            )

        except Exception as e:
            logger.exception(
                "Failed to start evaluation workflow",
                evaluation_id=evaluation_id,
                target_event_id=target_event_id,
                error=str(e),
            )
            return Response({"error": "Failed to start evaluation"}, status=500)
