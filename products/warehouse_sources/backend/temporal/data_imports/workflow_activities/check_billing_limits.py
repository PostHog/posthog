import typing
import dataclasses
from datetime import UTC, datetime

from django.db import close_old_connections

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.models.team.team import Team
from posthog.settings.base_variables import TEST
from posthog.temporal.common.logger import get_logger

from products.warehouse_sources.backend.billing import FREE_HISTORICAL_WINDOW, FREE_PERIOD_END, FREE_PERIOD_START

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


@activity.defn
def check_billing_limits_activity(inputs: CheckBillingLimitsActivityInputs) -> bool:
    from products.warehouse_sources.backend.temporal.data_imports.external_data_job import (
        ExternalDataJob,
        ExternalDataSource,
    )

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

    source: ExternalDataSource = job.pipeline

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

    team: Team = Team.objects.only("api_token").get(id=inputs.team_id)

    if is_team_limited(team.api_token, QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY):
        logger.info("Billing limits hit. Canceling sync")
        return True

    return False
