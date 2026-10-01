import typing
import dataclasses
from datetime import UTC, datetime

from django.db import close_old_connections

import redis
from structlog.contextvars import bind_contextvars
from structlog.types import FilteringBoundLogger
from temporalio import activity
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.models.team.team import Team
from posthog.settings.base_variables import TEST
from posthog.temporal.common.logger import get_logger

from products.warehouse_sources.backend.billing import FREE_HISTORICAL_WINDOW, FREE_PERIOD_END, FREE_PERIOD_START
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.util import with_internal_db_retries

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CheckBillingLimitsActivityInputs:
    team_id: int
    job_id: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "job_id": self.job_id,
        }


# The limiter list lives in Redis. Inside the job-creation activity this check has a single Temporal
# attempt (a retry there would create a duplicate job row), so a connection blip is absorbed here
# instead of failing the run.
@retry(
    retry=retry_if_exception_type((redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=0.5, max=2),
    reraise=True,
)
def _team_is_rows_synced_limited(api_token: str) -> bool:
    return is_team_limited(api_token, QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)


def billing_limit_reached(
    job: ExternalDataJob, source: ExternalDataSource, team_id: int, logger: FilteringBoundLogger
) -> bool:
    """Whether this run must stop because the team is over its synced-rows quota.

    The decision only needs the job's billable flag and the source's age, so the job-creation
    activity can answer it in the same round trip that creates the job row.
    """
    if not job.billable:
        logger.info("Skipping billing limits check for non-billable job")
        return False

    if source.created_at >= datetime.now(UTC) - FREE_HISTORICAL_WINDOW:
        logger.info(
            f"Skipping billing limits check for newly created data source for 7-days free rows. source.created_at = {source.created_at}"
        )
        return False

    if not TEST and datetime.now(UTC) >= FREE_PERIOD_START and datetime.now(UTC) <= FREE_PERIOD_END:
        logger.info(
            f"Skipping billing limits check for data synced during free period from {FREE_PERIOD_START} to {FREE_PERIOD_END}."
        )
        return False

    team: Team = Team.objects.only("api_token").get(id=team_id)

    if _team_is_rows_synced_limited(team.api_token):
        logger.info("Billing limits hit. Canceling sync")
        return True

    return False


@activity.defn
@with_internal_db_retries
def check_billing_limits_activity(inputs: CheckBillingLimitsActivityInputs) -> bool:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()
    close_old_connections()

    try:
        job = ExternalDataJob.objects.get(id=inputs.job_id)
    except ExternalDataJob.DoesNotExist:
        # job_id can be None (or point at a job that no longer exists) when this input came
        # from an older worker's create_external_data_job_model_activity result — that legacy
        # compatibility path doesn't guarantee a job was created. Nothing to bill for, so let
        # the sync proceed rather than fail the whole workflow.
        logger.info("Skipping billing limits check: job does not exist", job_id=inputs.job_id)
        return False

    return billing_limit_reached(job, job.pipeline, inputs.team_id, logger)
