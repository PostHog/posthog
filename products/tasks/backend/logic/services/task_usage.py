from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.tasks.backend.logic.services.sandbox_pricing import (
    COMPUTE_RATE_CARDS,
    calculate_sandbox_compute_cost,
    validate_compute_rate_cards,
)
from products.tasks.backend.models import SandboxSession, Task, TaskClientProvenance


@dataclass(frozen=True)
class TaskUsage:
    token_cost_usd: Decimal
    compute_cost_usd: Decimal

    @property
    def total_cost_usd(self) -> Decimal:
        return self.token_cost_usd + self.compute_cost_usd


def get_task_usage(*, team_id: int, task_id: UUID, task_created_at: datetime) -> TaskUsage:
    return TaskUsage(
        token_cost_usd=_get_task_token_cost(task_id=task_id, task_created_at=task_created_at),
        compute_cost_usd=_get_task_compute_cost(team_id=team_id, task_id=task_id),
    )


def _get_task_token_cost(*, task_id: UUID, task_created_at: datetime) -> Decimal:
    query = parse_select(
        """
        SELECT round(sum(toFloat(properties.$ai_total_cost_usd)), 6)
        FROM events
        WHERE equals(event, '$ai_generation')
            AND greaterOrEquals(timestamp, {task_created_at})
            AND equals(properties.ai_product, 'posthog_code')
            AND (
                equals(properties.task_id, {task_id})
                OR equals(properties.$ai_session_id, {task_id})
            )
        """
    )
    result = execute_hogql_query(
        query=query,
        placeholders={
            "task_created_at": ast.Constant(value=task_created_at),
            "task_id": ast.Constant(value=str(task_id)),
        },
        team=Team.objects.get(pk=settings.LLM_ANALYTICS_INTERNAL_TEAM_ID),
        query_type="TaskUsageTokenCost",
    )
    value = (result.results or [(0,)])[0][0]
    return Decimal(str(value or 0))


def _get_task_compute_cost(*, team_id: int, task_id: UUID) -> Decimal:
    if not COMPUTE_RATE_CARDS:
        return Decimal(0)

    rate_cards = validate_compute_rate_cards(COMPUTE_RATE_CARDS)
    calculated_at = timezone.now()
    sessions = (
        SandboxSession.objects.for_team(team_id)
        .filter(
            task_run__task_id=task_id,
            client_provenance=TaskClientProvenance.POSTHOG_DESKTOP,
            user_attributed_at__isnull=False,
        )
        .filter(
            Q(origin_product=Task.OriginProduct.USER_CREATED)
            | Q(
                origin_product=Task.OriginProduct.LOOP,
                task_run__task__loop__isnull=False,
                task_run__task__loop__internal=False,
            )
        )
    )
    return sum(
        (
            calculate_sandbox_compute_cost(
                session,
                rate_cards[0].effective_at,
                calculated_at,
                calculated_at=calculated_at,
                rate_cards=rate_cards,
            ).total_cost_usd
            for session in sessions.iterator()
        ),
        Decimal(0),
    )
