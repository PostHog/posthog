import time
from collections import Counter

from celery import shared_task
from prometheus_client import Gauge
from structlog import get_logger

from posthog.metrics import pushed_metrics_registry
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.providers.ses import SESProvider

logger = get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def poll_ses_account_reputation() -> None:
    """
    Export AWS's account-level SES verdict as gauges for alerting: enforcement status, open
    reputation findings, and a poll timestamp. The timestamp exists because pushgateway
    gauges never expire — without it, a dead poller freezes the last "healthy" values
    forever and nothing would fire.
    """
    try:
        reputation = SESProvider().get_account_reputation()
    except Exception:
        # Regions without SES access (self-hosted, dev) land here every tick; a stale
        # last_poll_timestamp is the alertable signal for genuine poller breakage in cloud.
        logger.warning("SES account reputation poll failed", exc_info=True)
        return

    finding_counts = Counter(
        (finding["scope"], finding["finding_type"], finding["impact"]) for finding in reputation["findings"]
    )

    # multiprocess_mode="mostrecent" everywhere: the celery workers run prometheus_client in
    # multiprocess mode, which re-exports these gauges on the pod's own /metrics regardless of
    # the private registry. Without it, every worker process exposes its own copy frozen at the
    # last value that pid set, and alerts evaluating those fossil series flap.
    with pushed_metrics_registry("ses_account_reputation") as registry:
        Gauge(
            "posthog_ses_account_enforcement_healthy",
            "1 while AWS SES reports the account EnforcementStatus as HEALTHY, 0 otherwise.",
            registry=registry,
            multiprocess_mode="mostrecent",
        ).set(1 if reputation["enforcement_status"] == "HEALTHY" else 0)

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
            "posthog_ses_account_reputation_last_poll_timestamp_seconds",
            "Unix timestamp of the last successful SES account reputation poll.",
            registry=registry,
            multiprocess_mode="mostrecent",
        ).set(time.time())
