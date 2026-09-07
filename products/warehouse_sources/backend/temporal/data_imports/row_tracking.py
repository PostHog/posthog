import uuid
import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.db.models import F, Q, Sum
from django.db.utils import InternalError, OperationalError

import requests
import structlog
from dateutil import parser
from redis import (
    Redis,
    exceptions as redis_exceptions,
)
from structlog.types import FilteringBoundLogger

from posthog.cloud_utils import get_cached_instance_license
from posthog.exceptions_capture import capture_exception
from posthog.models import Organization, Team
from posthog.redis import get_async_client, get_client
from posthog.settings import EE_AVAILABLE
from posthog.settings.base_variables import TEST
from posthog.sync import database_sync_to_async_pool

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob, billable_destination_multiplier

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


logger = structlog.get_logger(__name__)


def _get_hash_key(team_id: int) -> str:
    return f"posthog:data_warehouse_row_tracking:{team_id}"


@asynccontextmanager
async def _get_redis():
    """Returns an async Redis client for row tracking operations."""
    redis = None
    try:
        if not settings.DATA_WAREHOUSE_REDIS_HOST or not settings.DATA_WAREHOUSE_REDIS_PORT:
            raise Exception(
                "Missing env vars for dwh row tracking: DATA_WAREHOUSE_REDIS_HOST or DATA_WAREHOUSE_REDIS_PORT"
            )

        redis = get_async_client(f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/")
        await redis.ping()
    except redis_exceptions.RedisError as e:
        # Row tracking already fails open when redis is unavailable (every caller
        # checks `if not redis: return`), so a Redis-side blip - unreachable, refusing
        # writes because RDB snapshotting failed, loading, etc. - isn't a bug, and
        # shouldn't be reported to error tracking. Same rationale as the RedisError
        # handling in will_hit_billing_limit below.
        await logger.awarning("Redis error while getting row tracking client, failing open", error=str(e))
        redis = None
    except Exception as e:
        capture_exception(e)
        # get_async_client only builds a lazy client, so a failed ping means redis is
        # still unreachable - reset it to None so callers' `if not redis: return` guard
        # actually skips the real command instead of raising the same error uncaught.
        redis = None

    yield redis


async def setup_row_tracking(team_id: int, schema_id: uuid.UUID | str) -> None:
    async with _get_redis() as redis:
        if not redis:
            return

        try:
            await redis.hset(_get_hash_key(team_id), str(schema_id), 0)
            await redis.expire(_get_hash_key(team_id), 60 * 60 * 24 * 7)  # 7 day expire
        except redis_exceptions.RedisError as e:
            # A successful ping doesn't guarantee later commands succeed (e.g. Redis
            # refusing writes because it can't persist an RDB snapshot). Row tracking is
            # best-effort, so a command failing here shouldn't fail the whole import.
            capture_exception(e)


async def increment_rows(team_id: int, schema_id: uuid.UUID | str, rows: int) -> None:
    async with _get_redis() as redis:
        if not redis:
            return

        try:
            await redis.hincrby(_get_hash_key(team_id), str(schema_id), rows)
        except redis_exceptions.RedisError as e:
            capture_exception(e)


async def decrement_rows(team_id: int, schema_id: uuid.UUID | str, rows: int) -> None:
    async with _get_redis() as redis:
        if not redis:
            return

        try:
            if not await redis.hexists(_get_hash_key(team_id), str(schema_id)):
                return

            value = await redis.hget(_get_hash_key(team_id), str(schema_id))
            if not value:
                return

            value_int = int(value)
            if value_int - rows < 0:
                await redis.hset(_get_hash_key(team_id), str(schema_id), 0)
            else:
                await redis.hincrby(_get_hash_key(team_id), str(schema_id), -rows)
        except redis_exceptions.RedisError as e:
            capture_exception(e)


async def finish_row_tracking(team_id: int, schema_id: uuid.UUID | str) -> None:
    async with _get_redis() as redis:
        if not redis:
            return

        try:
            await redis.hdel(_get_hash_key(team_id), str(schema_id))
        except redis_exceptions.RedisError as e:
            capture_exception(e)


async def get_rows(team_id: int, schema_id: uuid.UUID | str) -> int:
    async with _get_redis() as redis:
        if not redis:
            return 0

        try:
            if await redis.hexists(_get_hash_key(team_id), str(schema_id)):
                value = await redis.hget(_get_hash_key(team_id), str(schema_id))
                if value:
                    return int(value)
        except redis_exceptions.RedisError as e:
            capture_exception(e)

        return 0


async def get_all_rows_for_team(team_id: int) -> int:
    async with _get_redis() as redis:
        if not redis:
            return 0

        try:
            pairs = await redis.hgetall(_get_hash_key(team_id))
            return sum(int(v) for v in pairs.values())
        except redis_exceptions.RedisError as e:
            capture_exception(e)
            return 0


# To be removed after 2025-11-06
dwh_pricing_free_period_start = datetime(2025, 10, 29, 0, 0, 0, tzinfo=UTC)
dwh_pricing_free_period_end = datetime(2025, 11, 6, 0, 0, 0, tzinfo=UTC)

# The billing-period sum only moves when a job completes, so serving it from a cache for a
# few minutes costs at most the rows one organization completes inside the window. The hard
# stop behind this check (check_billing_limits_activity, reading the quota-limiting cache)
# already refreshes on a 15 minute cron, so this adds no staleness the gate did not have.
BILLING_PERIOD_ROWS_CACHE_TTL_SECONDS = 5 * 60


def _billing_period_rows_key(organization_id: uuid.UUID | str, billing_cycle_start: datetime) -> str:
    # The cycle start is part of the key so a new billing period reads a fresh sum instead of
    # waiting out the TTL of the previous period's total.
    return f"posthog:data_warehouse_billing_period_rows:{organization_id}:{billing_cycle_start.isoformat()}"


def _get_sync_redis() -> Redis | None:
    """Synchronous Redis client for the billing-period cache, or None when it is not configured.

    The cache is read inside the same database thread as the query it replaces, so it uses the
    synchronous client rather than the async one the row-tracking helpers use.
    """
    if not settings.DATA_WAREHOUSE_REDIS_HOST or not settings.DATA_WAREHOUSE_REDIS_PORT:
        return None

    return get_client(f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/")


def _rows_synced_in_billing_period(
    organization_id: uuid.UUID | str, team_ids: list[int], billing_cycle_start: datetime
) -> int:
    key = _billing_period_rows_key(organization_id, billing_cycle_start)
    redis = _get_sync_redis()

    if redis is not None:
        try:
            cached_rows = redis.get(key)
            if cached_rows is not None:
                return int(cached_rows)
        except redis_exceptions.RedisError as e:
            # A cache failure must fall through to the query rather than raise: the caller treats
            # a RedisError as "fail open", which would skip the billing check for this run
            # instead of paying for the query.
            #
            # Drop the client so the write below is skipped too. This runs on a shared database
            # executor thread, and a Redis endpoint that answers slowly can hold one for up to
            # REDIS_SOCKET_TIMEOUT_SECONDS per command, which would delay unrelated activities.
            redis = None
            logger.warning("BillingLimits: could not read the cached row count, querying Postgres", error=str(e))
        except ValueError as e:
            # A value that is not an integer means a corrupt key rather than an unhealthy Redis,
            # so keep the client: the write below replaces the bad value.
            logger.warning("BillingLimits: cached row count is not a number, querying Postgres", error=str(e))

    # Completed rows for every team in the org, excluding each source's first 7 free days.
    # Rows bill once per destination the run delivered to. A run completes only when every
    # destination took it, so the count is exact.
    result = ExternalDataJob.objects.filter(
        Q(finished_at__gte=F("pipeline__created_at") + timedelta(days=7)),
        team_id__in=team_ids,
        finished_at__gte=billing_cycle_start,
        billable=True,
        status=ExternalDataJob.Status.COMPLETED,
    ).aggregate(total_rows=Sum(F("rows_synced") * billable_destination_multiplier()))
    rows_synced_in_billing_period = result.get("total_rows") or 0

    if redis is not None:
        try:
            redis.set(key, rows_synced_in_billing_period, ex=BILLING_PERIOD_ROWS_CACHE_TTL_SECONDS)
        except redis_exceptions.RedisError as e:
            logger.warning("BillingLimits: could not cache the row count", error=str(e))

    return rows_synced_in_billing_period


async def will_hit_billing_limit(team_id: int, source: "ExternalDataSource", logger: FilteringBoundLogger) -> bool:
    if not EE_AVAILABLE:
        return False

    try:
        from ee.billing.billing_manager import BillingManager

        await logger.adebug("Running will_hit_billing_limit")

        # Handle free period for newly created data sources
        if source.created_at >= datetime.now(UTC) - timedelta(days=7):
            await logger.ainfo(
                f"Skipping billing limits check for newly created data source for 7-days free rows. source.created_at = {source.created_at}"
            )
            return False

        # Handle free period for data synced during free period (to be removed after 2025-11-06)
        if (
            not TEST
            and datetime.now(UTC) >= dwh_pricing_free_period_start
            and datetime.now(UTC) <= dwh_pricing_free_period_end
        ):
            await logger.ainfo(
                f"Skipping billing limits check for data synced during free period from {dwh_pricing_free_period_start} to {dwh_pricing_free_period_end}."
            )
            return False

        @database_sync_to_async_pool
        def _get_billing_data():
            license = get_cached_instance_license()
            billing_manager = BillingManager(license)
            team = Team.objects.get(id=team_id)
            organization: Organization = team.organization
            all_teams_in_org: list[int] = [
                value[0] for value in Team.objects.filter(organization_id=organization.id).values_list("id")
            ]

            billing_res = billing_manager.get_billing(organization)

            rows_synced_in_billing_period = 0

            current_billing_cycle_start = billing_res.get("billing_period", {}).get("current_period_start")
            if current_billing_cycle_start is not None:
                rows_synced_in_billing_period = _rows_synced_in_billing_period(
                    organization.id, all_teams_in_org, parser.parse(current_billing_cycle_start)
                )

            return (
                organization.id,
                all_teams_in_org,
                billing_res,
                current_billing_cycle_start,
                rows_synced_in_billing_period,
            )

        (
            org_id,
            all_teams_in_org,
            billing_res,
            current_billing_cycle_start,
            rows_synced_in_billing_period,
        ) = await _get_billing_data()

        await logger.adebug(f"BillingLimits: Organisation_id = {org_id}")
        await logger.adebug(f"BillingLimits: Teams in org: {all_teams_in_org}")

        if current_billing_cycle_start is None:
            await logger.adebug(
                f"BillingLimits: returning early, no current_period_start available. current_billing_cycle_start = {current_billing_cycle_start}"
            )
            return False

        await logger.adebug(f"BillingLimits: current_billing_cycle_start = {current_billing_cycle_start}")

        usage_summary = billing_res["usage_summary"]
        rows_synced_summary = usage_summary.get("rows_synced", None)

        if not rows_synced_summary:
            await logger.adebug(f"BillingLimits: returning early, no rows_synced key in usage_summary. {usage_summary}")
            return False

        rows_synced_limit = rows_synced_summary.get("limit")

        await logger.adebug(f"BillingLimits: rows_synced_limit = {rows_synced_limit}")

        if rows_synced_limit is None or not isinstance(rows_synced_limit, int | float):
            await logger.adebug("BillingLimits: rows_synced_limit is None or not a number, returning False")
            return False

        await logger.adebug(f"BillingLimits: rows_synced_in_billing_period = {rows_synced_in_billing_period}")

        rows_per_team = await asyncio.gather(*[get_all_rows_for_team(t_id) for t_id in all_teams_in_org])
        existing_rows_in_progress = sum(rows_per_team)

        expected_rows = rows_synced_in_billing_period + existing_rows_in_progress

        result = expected_rows > rows_synced_limit

        await logger.adebug(
            f"BillingLimits: expected_rows = {expected_rows}. rows_synced_limit = {rows_synced_limit}. Returning {result}"
        )

        return result
    except redis_exceptions.RedisError as e:
        # The billing check already fails open, so a Redis connectivity blip (e.g. a
        # DNS resolution failure reaching the quota-limiting cache) shouldn't be reported
        # as an error-tracking issue.
        await logger.awarning(f"BillingLimits: Redis error while checking billing limits, failing open: {e}")

        return False
    except (OperationalError, InternalError) as e:
        # Same rationale as above: a dropped Postgres connection, or a read-only
        # transaction hitting a replica/failover blip, while fetching billing data is
        # a transient infra issue, and the check already fails open.
        await logger.awarning(f"BillingLimits: Database error while checking billing limits, failing open: {e}")

        return False
    except requests.exceptions.RequestException as e:
        # Same rationale as above: a network blip (e.g. a proxy timeout) reaching the
        # billing service is a transient infra issue, and the check already fails open.
        await logger.awarning(f"BillingLimits: Network error while checking billing limits, failing open: {e}")

        return False
    except Exception as e:
        await logger.adebug(f"BillingLimits: Failed with exception {e}")
        capture_exception(e)

        return False
