import time
import asyncio
from datetime import timedelta
from typing import cast

from django.conf import settings

import structlog
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.client import query_with_columns
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.temporal.common.client import sync_connect
from posthog.temporal.llm_analytics.run_evaluation import RunEvaluationInputs

from products.llm_analytics.backend.api.metrics import llma_track_latency

from ..models.evaluations import Evaluation

logger = structlog.get_logger(__name__)


class EvaluationRunRequestSerializer(serializers.Serializer):
    evaluation_id = serializers.UUIDField(required=True)
    target_event_id = serializers.UUIDField(required=True)
    timestamp = serializers.DateTimeField(required=True)
    event = serializers.CharField(required=True)
    distinct_id = serializers.CharField(required=False, allow_null=True)


class EvaluationRunViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "evaluation"
    permission_classes = [IsAuthenticated]

    @llma_track_latency("llma_evaluation_runs_create")
    @monitor(feature=None, endpoint="llma_evaluation_runs_create", method="POST")
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
        timestamp = serializer.validated_data["timestamp"]
        event = serializer.validated_data["event"]
        distinct_id = serializer.validated_data.get("distinct_id")

        # Verify evaluation exists and belongs to this team
        try:
            evaluation = Evaluation.objects.get(id=evaluation_id, team_id=self.team_id, deleted=False)
        except Evaluation.DoesNotExist:
            return Response({"error": f"Evaluation {evaluation_id} not found"}, status=404)

        # Fetch event data from ClickHouse efficiently using available index keys
        # The compound index is (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))
        where_clauses = [
            "team_id = %(team_id)s",
            "toDate(timestamp) = toDate(%(timestamp)s)",
            "event = %(event)s",
            "uuid = %(event_id)s",
        ]
        params = {
            "team_id": self.team_id,
            "event_id": target_event_id.replace("-", ""),
            "timestamp": timestamp,
            "event": event,
        }

        if distinct_id:
            where_clauses.append("distinct_id = %(distinct_id)s")
            params["distinct_id"] = distinct_id

        query_result = query_with_columns(
            f"""
            SELECT
                uuid,
                event,
                properties,
                timestamp,
                team_id,
                distinct_id,
                elements_chain,
                created_at,
                person_id
            FROM events
            WHERE {" AND ".join(where_clauses)}
            LIMIT 1
            """,
            params,
            team_id=self.team_id,
        )
        if len(query_result) == 0:
            return Response({"error": f"Event {target_event_id} not found"}, status=404)

        event_data = query_result[0]

        # Build workflow inputs
        inputs = RunEvaluationInputs(
            evaluation_id=evaluation_id,
            event_data=event_data,
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
                    task_queue=settings.LLMA_EVALS_TASK_QUEUE,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                    task_timeout=timedelta(minutes=2),
                )
            )

            logger.info(
                "Started evaluation workflow",
                workflow_id=workflow_id,
                evaluation_id=evaluation_id,
                target_event_id=target_event_id,
                team_id=self.team_id,
            )

            # Track evaluation run triggered
            report_user_action(
                cast(User, request.user),
                "llma evaluation run triggered",
                {
                    "evaluation_id": evaluation_id,
                    "evaluation_name": evaluation.name,
                    "target_event_id": target_event_id,
                    "workflow_id": workflow_id,
                    "trigger_type": "manual",
                },
                self.team,
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
