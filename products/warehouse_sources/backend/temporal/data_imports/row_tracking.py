import uuid
import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypeVar

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
from tenacity import retry, retry_if_exception, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.cloud_utils import get_cached_instance_license
from posthog.exceptions_capture import capture_exception
from posthog.models import Organization, Team
from posthog.redis import get_async_client, get_client
from posthog.settings import EE_AVAILABLE
from posthog.settings.base_variables import TEST
from posthog.sync import database_sync_to_async_pool

from products.warehouse_sources.backend.billing import FREE_HISTORICAL_WINDOW, FREE_PERIOD_END, FREE_PERIOD_START
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob, billable_destination_multiplier

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


logger = structlog.get_logger(__name__)

T = TypeVar("T")

# A connect blip, a "too many open files" refusal and a replica redirect during a failover all
# clear on their own, usually inside a second. Row tracking runs inside the import that calls it,
# so the retry stays short: the import waits for every attempt.
_retry_transient_redis_errors = retry(
    retry=retry_if_exception_type(
        (
            redis_exceptions.ConnectionError,
            redis_exceptions.TimeoutError,
            redis_exceptions.ReadOnlyError,
        )
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=0.1, max=1),
    reraise=True,
)


def _get_hash_key(team_id: int) -> str:
    return f"posthog:data_warehouse_row_tracking:{team_id}"


def _redis_url() -> str | None:
    """The dedicated warehouse Redis, or the shared one when no dedicated instance is configured.

    The fallback used to be localhost. Nothing listens there in a deployed environment, so an
    environment that sets neither DATA_WAREHOUSE_REDIS_HOST nor POSTHOG_REDIS_HOST turned every
    row-tracking call into a connection error. The shared Redis is the same fallback the other
    per-product instances take (see SESSION_RECORDING_REDIS_URL), and settings refuse to start
    without it, so a genuinely unconfigured install fails at startup instead of here.
    """
    if settings.DATA_WAREHOUSE_REDIS_HOST and settings.DATA_WAREHOUSE_REDIS_PORT:
        return f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/"

    return settings.REDIS_URL or None


async def _fail_open(description: str, command: Callable[[], Awaitable[T]], fallback: T) -> T:
    """Run a row-tracking Redis command, retry a transient failure, then return `fallback`.

    Row tracking is bookkeeping for the billing estimate, so no Redis failure may reach the import
    that called it. A retried command runs twice if Redis applied the first attempt and the reply
    was lost, which at most counts one batch of rows twice until the next sync resets the counter.
    """
    try:
        return await _retry_transient_redis_errors(command)()
    except redis_exceptions.RedisError as e:
        await logger.awarning(f"Redis error while {description}, failing open", error=str(e))
        return fallback


@asynccontextmanager
async def _get_redis():
    """Returns an async Redis client for row tracking operations."""
    redis = None
    url = _redis_url()

    if url is None:
        await logger.aerror("No Redis is configured for row tracking, failing open")
    else:
        try:
            client = get_async_client(url)

            async def _ping() -> None:
                await client.ping()

            # get_async_client only builds a lazy client, so the ping is the first real connection
            # attempt. Hand the client to the caller only once it answers, so that a caller's
            # `if not redis: return` guard skips the real command instead of raising the same
            # error uncaught.
            await _retry_transient_redis_errors(_ping)()
            redis = client
        except redis_exceptions.RedisError as e:
            # Row tracking already fails open when redis is unavailable (every caller
            # checks `if not redis: return`), so a Redis-side blip - unreachable, refusing
            # writes because RDB snapshotting failed, loading, etc. - isn't a bug, and
            # shouldn't be reported to error tracking. Same rationale as the RedisError
            # handling in will_hit_billing_limit below.
            await logger.awarning("Redis error while getting row tracking client, failing open", error=str(e))
        except Exception as e:
            capture_exception(e)

    yield redis


async def setup_row_tracking(team_id: int, schema_id: uuid.UUID | str) -> None:
    async with _get_redis() as redis:
        if not redis:
            return

        async def _command() -> None:
            await redis.hset(_get_hash_key(team_id), str(schema_id), 0)
            await redis.expire(_get_hash_key(team_id), 60 * 60 * 24 * 7)  # 7 day expire

        await _fail_open("setting up row tracking", _command, None)


async def increment_rows(team_id: int, schema_id: uuid.UUID | str, rows: int) -> None:
    async with _get_redis() as redis:
        if not redis:
            return

        async def _command() -> None:
            await redis.hincrby(_get_hash_key(team_id), str(schema_id), rows)

        await _fail_open("incrementing row tracking", _command, None)


async def decrement_rows(team_id: int, schema_id: uuid.UUID | str, rows: int) -> None:
    async with _get_redis() as redis:
        if not redis:
            return

        async def _command() -> None:
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

        await _fail_open("decrementing row tracking", _command, None)


async def finish_row_tracking(team_id: int, schema_id: uuid.UUID | str) -> None:
    async with _get_redis() as redis:
        if not redis:
            return

        async def _command() -> None:
            await redis.hdel(_get_hash_key(team_id), str(schema_id))

        await _fail_open("finishing row tracking", _command, None)


async def get_rows(team_id: int, schema_id: uuid.UUID | str) -> int:
    async with _get_redis() as redis:
        if not redis:
            return 0

        async def _command() -> int:
            if await redis.hexists(_get_hash_key(team_id), str(schema_id)):
                value = await redis.hget(_get_hash_key(team_id), str(schema_id))
                if value:
                    return int(value)

            return 0

        return await _fail_open("reading row tracking", _command, 0)


async def get_all_rows_for_team(team_id: int) -> int:
    async with _get_redis() as redis:
        if not redis:
            return 0

        async def _command() -> int:
            pairs = await redis.hgetall(_get_hash_key(team_id))
            return sum(int(v) for v in pairs.values())

        return await _fail_open("reading team row tracking", _command, 0)


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
    url = _redis_url()
    if url is None:
        return None

    return get_client(url)


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
        Q(finished_at__gte=F("pipeline__created_at") + FREE_HISTORICAL_WINDOW),
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


# Billing answers a request it could not finish in time with a 408, and a request it could not
# serve with a 5xx. Both clear on a retry, and the check runs once per sync, so a few seconds of
# retry is cheaper than a sync that skips the limit.
_TRANSIENT_BILLING_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


def _is_transient_billing_error(error: BaseException) -> bool:
    # A connect failure or a read timeout clears on its own. `RequestException` also covers a
    # permanently broken request, such as an invalid `BILLING_SERVICE_URL`, and that must not be
    # retried: it fails the same way on every attempt, so retrying only adds backoff to every sync.
    if isinstance(error, requests.exceptions.ConnectionError | requests.exceptions.Timeout):
        return True

    # BillingServiceResponseError carries the status code billing answered with. The status is
    # read through getattr because ee is not importable in every deployment.
    return getattr(error, "status_code", None) in _TRANSIENT_BILLING_STATUS_CODES


_retry_transient_billing_errors = retry(
    retry=retry_if_exception(_is_transient_billing_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=0.5, max=4),
    reraise=True,
)


@_retry_transient_billing_errors
async def _fetch_billing_data(get_billing_data: Callable[[], Awaitable[T]]) -> T:
    return await get_billing_data()


async def will_hit_billing_limit(team_id: int, source: "ExternalDataSource", logger: FilteringBoundLogger) -> bool:
    if not EE_AVAILABLE:
        return False

    try:
        from ee.billing.billing_manager import BillingManager

        await logger.adebug("Running will_hit_billing_limit")

        # Handle free period for newly created data sources
        if source.created_at >= datetime.now(UTC) - FREE_HISTORICAL_WINDOW:
            await logger.ainfo(
                f"Skipping billing limits check for newly created data source for 7-days free rows. source.created_at = {source.created_at}"
            )
            return False

        # Handle free period for data synced during free period (to be removed after 2025-11-06)
        if not TEST and datetime.now(UTC) >= FREE_PERIOD_START and datetime.now(UTC) <= FREE_PERIOD_END:
            await logger.ainfo(
                f"Skipping billing limits check for data synced during free period from {FREE_PERIOD_START} to {FREE_PERIOD_END}."
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
        ) = await _fetch_billing_data(_get_billing_data)

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
        if _is_transient_billing_error(e):
            # Billing refused with a status that clears on its own, and the retries above are
            # spent. The check already fails open, so this is infrastructure noise rather than a
            # bug to report to error tracking.
            await logger.awarning(f"BillingLimits: billing service is unavailable, failing open: {e}")

            return False

        await logger.adebug(f"BillingLimits: Failed with exception {e}")
        capture_exception(e)

        return False
