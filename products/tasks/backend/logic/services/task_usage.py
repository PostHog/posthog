import hmac
import json
import time
import hashlib
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
