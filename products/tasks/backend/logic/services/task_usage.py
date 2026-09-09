import hmac
import json
import time
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

import requests
import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models import Team

from products.tasks.backend.logic.services.sandbox_pricing import (
    COMPUTE_RATE_CARDS,
    calculate_sandbox_compute_cost,
    validate_compute_rate_cards,
)
from products.tasks.backend.models import SandboxSession, Task, TaskClientProvenance

TASK_USAGE_SIGNATURE_HEADER = "X-PostHog-Task-Usage-Signature"
TASK_USAGE_TIMESTAMP_HEADER = "X-PostHog-Task-Usage-Timestamp"
TASK_USAGE_CROSS_REGION_TIMEOUT_SECONDS = (3, 15)
TASK_USAGE_INTERNAL_PATH = "/api/code/internal/task_usage/"
TASK_TOKEN_COST_CACHE_TIMEOUT_SECONDS = 60

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TaskUsage:
    token_cost_usd: Decimal
    compute_cost_usd: Decimal

    @property
    def total_cost_usd(self) -> Decimal:
        return self.token_cost_usd + self.compute_cost_usd


def get_task_usage(*, team_id: int, task_id: UUID, task_created_at: datetime) -> TaskUsage:
    return TaskUsage(
        token_cost_usd=_get_task_token_cost(team_id=team_id, task_id=task_id, task_created_at=task_created_at),
        compute_cost_usd=_get_task_compute_cost(team_id=team_id, task_id=task_id),
    )


class TaskTokenUsageUnavailable(Exception):
    pass


@frozen
class TaskUsageRequestSignature:
    signature: str
    timestamp: str


def sign_task_usage_request(body: bytes, secret: str, *, timestamp: int | None = None) -> TaskUsageRequestSignature:
    request_timestamp = str(int(time.time()) if timestamp is None else timestamp)
    signed_value = f"v0:{request_timestamp}:{body.decode('utf-8')}"
    signature = hmac.new(secret.encode(), signed_value.encode(), hashlib.sha256).hexdigest()
    return TaskUsageRequestSignature(signature=signature, timestamp=request_timestamp)


def _get_task_token_cost(*, team_id: int, task_id: UUID, task_created_at: datetime) -> Decimal:
    cache_key = _task_token_cost_cache_key(team_id=team_id, task_id=task_id, task_created_at=task_created_at)
    cached = cache.get(cache_key)
    if cached is not None:
        return Decimal(str(cached))

    if settings.CLOUD_DEPLOYMENT == "EU":
        token_cost = _get_cross_region_task_token_cost(
            team_id=team_id, task_id=task_id, task_created_at=task_created_at
        )
    else:
        token_cost = get_local_task_token_cost(team_id=team_id, task_id=task_id, task_created_at=task_created_at)
    cache.set(cache_key, str(token_cost), timeout=TASK_TOKEN_COST_CACHE_TIMEOUT_SECONDS)
    return token_cost


def _task_token_cost_cache_key(*, team_id: int, task_id: UUID, task_created_at: datetime) -> str:
    return f"task_token_cost:v2:{team_id}:{task_id}:{task_created_at.isoformat()}"


def _get_cross_region_task_token_cost(*, team_id: int, task_id: UUID, task_created_at: datetime) -> Decimal:
    secret = settings.PERSONAL_SPEND_CROSS_REGION_SECRET
    if not secret:
        logger.error("task_usage.cross_region_not_configured")
        raise TaskTokenUsageUnavailable("Cross-region task usage is not configured")

    body = json.dumps(
        {"team_id": team_id, "task_id": str(task_id), "task_created_at": task_created_at.isoformat()}
    ).encode()
    signed = sign_task_usage_request(body, secret)
    target = f"{settings.SITE_URL if settings.DEBUG else 'https://us.posthog.com'}{TASK_USAGE_INTERNAL_PATH}"
    try:
        response = requests.post(
            target,
            data=body,
            headers={
                "Content-Type": "application/json",
                TASK_USAGE_SIGNATURE_HEADER: signed.signature,
                TASK_USAGE_TIMESTAMP_HEADER: signed.timestamp,
            },
            timeout=TASK_USAGE_CROSS_REGION_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return Decimal(str(response.json()["token_cost_usd"]))
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        logger.exception("task_usage.cross_region_request_failed", error_type=type(error).__name__)
        raise TaskTokenUsageUnavailable("Cross-region task usage is unavailable") from error


# The internal project the gateways capture `$ai_generation` into is region-local: each region's
# generations land in that region's own project. Same mapping AI credit billing reads
# (`CLOUD_REGION_TO_TEAM_ID` in `posthog/tasks/usage_report.py`), kept separately because that
# module imports this product's facade. `LLM_ANALYTICS_INTERNAL_TEAM_ID` is 2 in every region, so
# it can't answer this on its own — it stays the fallback for a deployment that isn't US or EU.
INTERNAL_LLM_ANALYTICS_TEAM_ID_BY_REGION = {"EU": 1, "US": 2}


def _internal_llm_analytics_team() -> Team:
    """The project this region's `$ai_generation` events are captured into.

    A deployment with no such project has nothing to read, and callers must surface that as
    unknown rather than as zero spend.
    """
    team_id = INTERNAL_LLM_ANALYTICS_TEAM_ID_BY_REGION.get(
        settings.CLOUD_DEPLOYMENT or "", settings.LLM_ANALYTICS_INTERNAL_TEAM_ID
    )
    try:
        return Team.objects.get(pk=team_id)
    except Team.DoesNotExist as error:
        logger.exception("task_usage.internal_llm_analytics_team_missing", team_id=team_id)
        raise TaskTokenUsageUnavailable("The internal AI observability project is not readable here") from error


def get_local_task_token_cost(*, team_id: int, task_id: UUID, task_created_at: datetime) -> Decimal:
    query = parse_select(
        """
        SELECT round(sum(toFloat(properties.$ai_total_cost_usd)), 6)
        FROM events
        WHERE equals(event, '$ai_generation')
            AND greaterOrEquals(timestamp, {task_created_at})
            AND equals(properties.ai_product, 'posthog_code')
            AND equals(toString(properties.team_id), {team_id})
            AND (
                equals(properties.task_id, {task_id})
                OR equals(properties.$ai_session_id, {task_id})
            )
        """
    )
    with tags_context(product=Product.POSTHOG_CODE, feature=Feature.QUERY):
        result = execute_hogql_query(
            query=query,
            placeholders={
                "task_created_at": ast.Constant(value=task_created_at),
                "team_id": ast.Constant(value=str(team_id)),
                "task_id": ast.Constant(value=str(task_id)),
            },
            team=_internal_llm_analytics_team(),
            query_type="TaskUsageTokenCost",
        )
    value = (result.results or [(0,)])[0][0]
    return Decimal(str(value or 0))


def get_local_task_run_token_costs(
    *,
    team_id: int,
    origin_product: str,
    task_run_ids: Sequence[UUID],
    generated_after: datetime,
    product: Product,
) -> dict[str, Decimal]:
    """Model spend per task run, for every run in `task_run_ids` that has any attributed to it.

    Keyed on `task_origin_product` rather than `ai_product`, because `ai_product` names the agent
    that made the generation, not the product the run belongs to: one origin product spans several
    `ai_product` values (a signal report reports a different one per pipeline stage), and one
    `ai_product` spans several origin products. A run with no attributed generation is absent from
    the result rather than priced at zero, so a caller can tell it from a run that really spent
    nothing. A run whose generations all lack `$ai_total_cost_usd` is absent for the same reason:
    the property is written only where a cost could be calculated, so the sum is null and the spend
    is unknown, not zero. A run priced in part still reports the sum of what was priced, which is a
    lower bound.
    """
    if not task_run_ids:
        return {}

    query = parse_select(
        """
        SELECT toString(properties.task_run_id) AS task_run_id,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS token_cost_usd
        FROM events
        WHERE equals(event, '$ai_generation')
            AND greaterOrEquals(timestamp, {generated_after})
            AND equals(properties.task_origin_product, {origin_product})
            AND equals(toString(properties.team_id), {team_id})
            AND in(toString(properties.task_run_id), {task_run_ids})
        GROUP BY task_run_id
        LIMIT {row_limit}
        """
    )
    with tags_context(product=product, feature=Feature.QUERY):
        result = execute_hogql_query(
            query=query,
            placeholders={
                "generated_after": ast.Constant(value=generated_after),
                "origin_product": ast.Constant(value=origin_product),
                "team_id": ast.Constant(value=str(team_id)),
                "task_run_ids": ast.Constant(value=[str(task_run_id) for task_run_id in task_run_ids]),
                # The group-by yields at most one row per requested run, but a limit-less select
                # is capped at 100 rows, and a caller may ask about more runs than that.
                "row_limit": ast.Constant(value=len(task_run_ids)),
            },
            team=_internal_llm_analytics_team(),
            query_type="TaskRunUsageTokenCost",
        )
    return {str(row[0]): Decimal(str(row[1])) for row in (result.results or []) if row[0] and row[1] is not None}


def _get_task_compute_cost(*, team_id: int, task_id: UUID) -> Decimal:
    if not COMPUTE_RATE_CARDS:
        return Decimal(0)

    rate_cards = validate_compute_rate_cards(COMPUTE_RATE_CARDS)
    calculated_at = timezone.now()
    pricing_start = rate_cards[0].effective_at
    # Rates are published ahead of the date they take effect, so until then nothing is priced.
    if calculated_at <= pricing_start:
        return Decimal(0)

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
                pricing_start,
                calculated_at,
                calculated_at=calculated_at,
                rate_cards=rate_cards,
            ).total_cost_usd
            for session in sessions.iterator()
        ),
        Decimal(0),
    )
