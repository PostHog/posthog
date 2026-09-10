import json
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.signals.backend.signal_costs import CostStage, add_cost, costs_in_cents
from products.signals.backend.signal_costs_query import update_signal_costs
from products.signals.backend.signal_metadata import EMBEDDING_MODEL
from products.tasks.backend.logic.services.sandbox_pricing import ComputeRateCard
from products.tasks.backend.models import SandboxSession, Task, TaskRun


def test_rounds_accumulated_spend_once_per_stage() -> None:
    costs: dict[CostStage, Decimal] = {}
    add_cost(costs, "research", "model-a", Decimal("0.004"))
    add_cost(costs, "research", "model-b", Decimal("0.004"))
    add_cost(costs, "implementation", "model-b", Decimal("0.025"))
    assert costs_in_cents(costs) == {"research": 1, "implementation": 2}


@freeze_time()
class TestSignalCosts(ClickhouseTestMixin, BaseTest):
    @parameterized.expand([(False,), (True,)])
    def test_projects_direct_and_task_spend_only_onto_the_trigger(self, unpriced: bool) -> None:
        signal_id = str(uuid4())
        started = timezone.now().replace(microsecond=0) - timedelta(hours=2)
        metadata = {
            "report_id": str(uuid4()),
            "costs_started_at": started.isoformat(),
            "source_id": "invented-issue",
            "deleted": True,
            "extra": {"preserve": "this"},
        }
        embedding = [0.1] * 1536
        table = f"distributed_posthog_document_embeddings_{EMBEDDING_MODEL.value.replace('-', '_')}"
        sync_execute(
            f"""INSERT INTO {table}
                (team_id, product, document_type, rendering, document_id, timestamp,
                 inserted_at, content, metadata, embedding, _timestamp, _offset, _partition)
                VALUES""",
            [
                (
                    self.team.id,
                    "signals",
                    "signal",
                    "plain",
                    signal_id,
                    started,
                    started,
                    "Synthetic signal",
                    json.dumps(metadata),
                    embedding,
                    started,
                    0,
                    0,
                )
            ],
        )
        research_task = Task.objects.create(
            team=self.team,
            title="Research",
            description="",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            state={"triggering_signal_id": signal_id},
        )
        implementation_task = Task.objects.create(
            team=self.team,
            title="Implementation",
            description="",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            state={"triggering_signal_id": signal_id},
        )
        research = TaskRun.objects.create(
            task=research_task,
            team=self.team,
            state={"ai_stage": "research"},
            status=TaskRun.Status.COMPLETED,
            completed_at=started + timedelta(minutes=10),
        )
        implementation = TaskRun.objects.create(
            task=implementation_task,
            team=self.team,
            state={"ai_stage": "implementation"},
            status=TaskRun.Status.COMPLETED,
            completed_at=started + timedelta(minutes=10),
        )
        for run in (research, implementation):
            SandboxSession.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                task_run=run,
                sandbox_id=str(run.id),
                origin_product=Task.OriginProduct.SIGNAL_REPORT,
                cpu_cores=1,
                memory_gb=1,
                ttl_seconds=3600,
                burstable=False,
                user_attributed_at=started,
                ttl_expires_at=started + timedelta(hours=1),
                ended_at=started + timedelta(seconds=10),
            )
        properties = [
            {"triggering_signal_id": signal_id, "$ai_total_cost_usd": 0.004, "ai_stage": "safety_filter"},
            {"triggering_signal_id": signal_id, "$ai_total_cost_usd": 0.004, "ai_stage": "matching"},
            {"task_run_id": str(research.id), "$ai_total_cost_usd": 0.025},
            {"task_run_id": str(research.id), "triggering_signal_id": signal_id, "$ai_total_cost_usd": 0.007},
            {"task_run_id": str(implementation.id), "$ai_total_cost_usd": 0.115},
            {"triggering_signal_id": str(uuid4()), "$ai_total_cost_usd": 99},
            {"triggering_signal_id": signal_id, "$ai_total_cost_usd": 99, "team_id": -1},
        ]
        if unpriced:
            properties.append({"triggering_signal_id": signal_id})
        for props in properties:
            _create_event(
                event="$ai_generation",
                team=self.team,
                distinct_id="cost-test",
                timestamp=started + timedelta(minutes=1),
                properties={
                    "team_id": self.team.id,
                    "$ai_model": "model-a",
                    **props,
                },
            )
        flush_persons_and_events()
        rate_card = ComputeRateCard(
            version="test",
            effective_at=started,
            expires_at=None,
            cpu_core_second_usd=Decimal("0.01"),
            memory_gib_second_usd=Decimal("0.01"),
        )
        with (
            self.settings(CLOUD_DEPLOYMENT=None, LLM_ANALYTICS_INTERNAL_TEAM_ID=self.team.id),
            patch("products.tasks.backend.logic.services.task_usage.COMPUTE_RATE_CARDS", (rate_card,)),
            patch("products.signals.backend.signal_costs_query.get_producer") as producer,
        ):
            assert update_signal_costs(self.team.id, signal_id) is unpriced
            first = producer.return_value.produce.call_args.kwargs["data"]
            assert update_signal_costs(self.team.id, signal_id) is unpriced
            assert producer.return_value.produce.call_args.kwargs["data"] == first

        projected = json.loads(first["metadata"])
        assert projected == {
            **metadata,
            "token_cost": {"research": 4, "implementation": 12},
            "compute_cost": {"research": 20, "implementation": 20},
            "costs_pending": unpriced,
        }
        assert first["document_id"] == signal_id
        assert first["embedding"] == embedding
        assert first["timestamp"] == started.strftime("%Y-%m-%d %H:%M:%S.%f")
