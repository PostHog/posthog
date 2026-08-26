import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags

from products.tasks.backend.logic.services import task_usage
from products.tasks.backend.logic.services.sandbox_pricing import ComputeRateCard
from products.tasks.backend.models import SandboxSession, Task, TaskClientProvenance, TaskRun


class TestTaskUsageQueryTagging(SimpleTestCase):
    def test_token_cost_query_is_attributed_to_posthog_code(self) -> None:
        captured_tags: dict[str, object] = {}

        def capture_query_tags(**kwargs: object) -> SimpleNamespace:
            tags = get_query_tags()
            captured_tags["product"] = tags.product
            captured_tags["feature"] = tags.feature
            return SimpleNamespace(results=[(0,)])

        with (
            self.settings(LLM_ANALYTICS_INTERNAL_TEAM_ID=1),
            patch.object(task_usage.Team.objects, "get", return_value=object()),
            patch.object(task_usage, "execute_hogql_query", side_effect=capture_query_tags),
        ):
            task_usage.get_local_task_token_cost(
                team_id=1,
                task_id=UUID("00000000-0000-0000-0000-000000000001"),
                task_created_at=datetime(2026, 8, 1, tzinfo=UTC),
            )

        assert captured_tags == {"product": Product.POSTHOG_CODE, "feature": Feature.QUERY}


class TestTaskUsage(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Usage task",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            client_provenance=TaskClientProvenance.POSTHOG_DESKTOP,
        )

    def test_token_cost_only_includes_generations_for_the_task_and_product(self) -> None:
        for team_id, task_id, product, cost in (
            (self.team.id, str(self.task.id), "posthog_code", 2.5),
            (self.team.id, str(self.task.id), "background_agents", 10),
            (self.team.id, "00000000-0000-0000-0000-000000000001", "posthog_code", 20),
            (self.team.id + 1, str(self.task.id), "posthog_code", 40),
        ):
            _create_event(
                event="$ai_generation",
                team=self.team,
                distinct_id=str(self.user.distinct_id),
                timestamp=self.task.created_at + timedelta(seconds=1),
                properties={
                    "team_id": team_id,
                    "task_id": task_id,
                    "ai_product": product,
                    "$ai_total_cost_usd": cost,
                },
            )
        flush_persons_and_events()

        with self.settings(LLM_ANALYTICS_INTERNAL_TEAM_ID=self.team.id):
            usage = task_usage.get_task_usage(
                team_id=self.team.id,
                task_id=self.task.id,
                task_created_at=self.task.created_at,
            )

        assert usage.token_cost_usd == Decimal("2.5")
        assert usage.compute_cost_usd == 0
        assert usage.total_cost_usd == Decimal("2.5")

    def test_compute_cost_only_includes_billable_desktop_sessions(self) -> None:
        rate_start = datetime(2026, 8, 1, tzinfo=UTC)
        rate_card = ComputeRateCard(
            version="test",
            effective_at=rate_start,
            expires_at=None,
            cpu_core_second_usd=Decimal("0.01"),
            memory_gib_second_usd=Decimal("0.01"),
        )
        for provenance in (TaskClientProvenance.POSTHOG_DESKTOP, None):
            run = TaskRun.objects.create(task=self.task, team=self.team)
            SandboxSession.objects.unscoped().create(
                team=self.team,
                task_run=run,
                sandbox_id=f"sandbox-{provenance or 'untrusted'}",
                origin_product=Task.OriginProduct.USER_CREATED,
                client_provenance=provenance,
                cpu_cores=1,
                memory_gb=1,
                ttl_seconds=3600,
                burstable=False,
                created_at=rate_start,
                ttl_expires_at=rate_start + timedelta(hours=1),
                user_attributed_at=rate_start,
                ended_at=rate_start + timedelta(seconds=10),
            )

        with (
            patch.object(task_usage, "COMPUTE_RATE_CARDS", (rate_card,)),
            patch.object(task_usage, "_get_task_token_cost", return_value=Decimal(0)),
            patch.object(task_usage.timezone, "now", return_value=rate_start + timedelta(minutes=1)),
        ):
            usage = task_usage.get_task_usage(
                team_id=self.team.id,
                task_id=self.task.id,
                task_created_at=self.task.created_at,
            )

        assert usage.compute_cost_usd == Decimal("0.20")

    def test_usage_is_reported_before_the_first_rate_card_takes_effect(self) -> None:
        rate_start = datetime(2026, 8, 1, tzinfo=UTC)
        rate_card = ComputeRateCard(
            version="test",
            effective_at=rate_start,
            expires_at=None,
            cpu_core_second_usd=Decimal("0.01"),
            memory_gib_second_usd=Decimal("0.01"),
        )
        run = TaskRun.objects.create(task=self.task, team=self.team)
        SandboxSession.objects.unscoped().create(
            team=self.team,
            task_run=run,
            sandbox_id="sandbox-before-rates",
            origin_product=Task.OriginProduct.USER_CREATED,
            client_provenance=TaskClientProvenance.POSTHOG_DESKTOP,
            cpu_cores=1,
            memory_gb=1,
            ttl_seconds=3600,
            burstable=False,
            created_at=rate_start - timedelta(hours=2),
            ttl_expires_at=rate_start - timedelta(hours=1),
            user_attributed_at=rate_start - timedelta(hours=2),
            ended_at=rate_start - timedelta(hours=1, seconds=50),
        )

        with (
            patch.object(task_usage, "COMPUTE_RATE_CARDS", (rate_card,)),
            patch.object(task_usage, "_get_task_token_cost", return_value=Decimal("2.5")),
            patch.object(task_usage.timezone, "now", return_value=rate_start - timedelta(days=1)),
        ):
            usage = task_usage.get_task_usage(
                team_id=self.team.id,
                task_id=self.task.id,
                task_created_at=self.task.created_at,
            )

        assert usage.compute_cost_usd == Decimal(0)
        assert usage.total_cost_usd == Decimal("2.5")

    def test_eu_token_cost_uses_cross_region_source(self) -> None:
        with (
            self.settings(
                CLOUD_DEPLOYMENT="EU",
                PERSONAL_SPEND_CROSS_REGION_SECRET="secret",
                DEBUG=False,
            ),
            patch.object(task_usage.requests, "post") as post,
        ):
            post.return_value.json.return_value = {"token_cost_usd": 1.25}
            token_cost = task_usage._get_task_token_cost(
                team_id=self.team.id,
                task_id=self.task.id,
                task_created_at=self.task.created_at,
            )

        assert token_cost == Decimal("1.25")
        assert post.call_args.args[0] == "https://us.posthog.com/api/code/internal/task_usage/"
        assert json.loads(post.call_args.kwargs["data"]) == {
            "team_id": self.team.id,
            "task_id": str(self.task.id),
            "task_created_at": self.task.created_at.isoformat(),
        }

    def test_eu_token_cost_is_unavailable_without_cross_region_secret(self) -> None:
        with (
            self.settings(CLOUD_DEPLOYMENT="EU", PERSONAL_SPEND_CROSS_REGION_SECRET=""),
            self.assertRaises(task_usage.TaskTokenUsageUnavailable),
        ):
            task_usage._get_task_token_cost(
                team_id=self.team.id, task_id=self.task.id, task_created_at=self.task.created_at
            )

    def test_token_cost_is_cached(self) -> None:
        with patch.object(task_usage, "get_local_task_token_cost", return_value=Decimal("1.25")) as get_cost:
            first = task_usage._get_task_token_cost(
                team_id=self.team.id, task_id=self.task.id, task_created_at=self.task.created_at
            )
            second = task_usage._get_task_token_cost(
                team_id=self.team.id, task_id=self.task.id, task_created_at=self.task.created_at
            )

        assert first == second == Decimal("1.25")
        get_cost.assert_called_once()
