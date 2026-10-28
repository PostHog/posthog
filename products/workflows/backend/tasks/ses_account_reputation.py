import time
from collections import Counter

from botocore.exceptions import ClientError
from celery import shared_task
from prometheus_client import Gauge
from structlog import get_logger

from posthog.metrics import pushed_metrics_registry
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.providers.ses import SESProvider

logger = get_logger(__name__)

# Each push replaces every metric previously pushed under its job name, so each poll and its
# failure marker get their own job. The enforcement poll keeps the original job name: pushgateway
# never expires a group, so a renamed job would leave the old timestamp frozen and alerting forever.
ENFORCEMENT_JOB = "ses_account_reputation"
FINDINGS_JOB = "ses_reputation_findings"

THROTTLE_ERROR_CODES = frozenset({"TooManyRequestsException", "Throttling", "ThrottlingException"})


def _failure_reason(error: Exception) -> str:
    if isinstance(error, ClientError) and error.response.get("Error", {}).get("Code") in THROTTLE_ERROR_CODES:
        return "throttled"
    return "error"


def _record_poll_failure(poll: str, job_name: str, error: Exception) -> None:
    """
    Push when and why the last poll failed, so the staleness alert can tell AWS throttling apart
    from a broken poller. Regions without SES access (self-hosted, dev) land here every tick, and
    those regions have no pushgateway, so the push is a no-op there.
    """
    reason = _failure_reason(error)
    logger.warning("SES reputation poll failed", poll=poll, reason=reason, exc_info=error)
    with pushed_metrics_registry(f"{job_name}_failure") as registry:
        Gauge(
            "posthog_ses_reputation_poll_last_failure_timestamp_seconds",
            "Unix timestamp of the last failed SES reputation poll, by poll and failure reason.",
            labelnames=["poll", "reason"],
            registry=registry,
            multiprocess_mode="mostrecent",
        ).labels(poll=poll, reason=reason).set(time.time())


# multiprocess_mode="mostrecent" everywhere: the celery workers run prometheus_client in
# multiprocess mode, which re-exports these gauges on the pod's own /metrics regardless of
# the private registry. Without it, every worker process exposes its own copy frozen at the
# last value that pid set, and alerts evaluating those fossil series flap.


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def poll_ses_account_enforcement() -> None:
    """
    Export AWS's account-level SES enforcement status as a gauge for alerting, plus a poll
    timestamp. The timestamp exists because pushgateway gauges never expire. Without it, a dead
    poller freezes the last "healthy" value forever and nothing would fire.
    """
    try:
        enforcement_status = SESProvider().get_account_enforcement_status()
    except Exception as error:
        _record_poll_failure("enforcement", ENFORCEMENT_JOB, error)
        return

    with pushed_metrics_registry(ENFORCEMENT_JOB) as registry:
        Gauge(
            "posthog_ses_account_enforcement_healthy",
            "1 while AWS SES reports the account EnforcementStatus as HEALTHY, 0 otherwise.",
            registry=registry,
            multiprocess_mode="mostrecent",
        ).set(1 if enforcement_status == "HEALTHY" else 0)

        Gauge(
            "posthog_ses_account_reputation_last_poll_timestamp_seconds",
            "Unix timestamp of the last successful SES account enforcement status poll.",
            registry=registry,
            multiprocess_mode="mostrecent",
        ).set(time.time())


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def poll_ses_reputation_findings() -> None:
    """
    Export the open AWS SES reputation findings, counted by the resource scope they reference,
    plus a poll timestamp. This walk pages through every tenant's findings, so it runs less often
    than the enforcement poll and has its own timestamp, which keeps a throttled walk from making
    the enforcement signal look stale.
    """
    try:
        findings = SESProvider().get_account_reputation_findings()
    except Exception as error:
        _record_poll_failure("findings", FINDINGS_JOB, error)
        return

    finding_counts = Counter((finding["scope"], finding["finding_type"], finding["impact"]) for finding in findings)

    with pushed_metrics_registry(FINDINGS_JOB) as registry:
        findings_gauge = Gauge(
            "posthog_ses_open_reputation_findings",
            "Open AWS SES reputation findings (ListRecommendations), by referenced resource scope.",
            labelnames=["scope", "finding_type", "impact"],
            registry=registry,
            multiprocess_mode="mostrecent",
        )
        for (scope, finding_type, impact), count in finding_counts.items():
            findings_gauge.labels(scope=scope, finding_type=finding_type, impact=impact).set(count)

        Gauge(
            "posthog_ses_reputation_findings_last_poll_timestamp_seconds",
            "Unix timestamp of the last successful SES reputation findings poll.",
            registry=registry,
            multiprocess_mode="mostrecent",
        ).set(time.time())
