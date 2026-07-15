from django.conf import settings

import requests
import structlog
from celery import shared_task

from products.tasks.backend.logic.services.run_log_otlp import build_otlp_payload

logger = structlog.get_logger(__name__)

OTLP_EXPORT_TIMEOUT_SECONDS = 10


@shared_task(
    ignore_result=True,
    autoretry_for=(requests.RequestException,),
    retry_backoff=True,
    max_retries=3,
)
def forward_task_run_logs_to_posthog_logs(
    entries: list[dict],
    team_id: int,
    task_id: str,
    run_id: str,
    origin_product: str,
) -> None:
    """Mirror persisted task-run log entries to a PostHog project's Logs product via OTLP/HTTP."""
    endpoint = settings.TASK_RUN_LOGS_OTLP_ENDPOINT
    token = settings.TASK_RUN_LOGS_OTLP_TOKEN
    if not endpoint or not token:
        return

    payload = build_otlp_payload(
        entries,
        team_id=team_id,
        task_id=task_id,
        run_id=run_id,
        origin_product=origin_product,
    )
    if payload is None:
        return

    response = requests.post(
        endpoint,
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=OTLP_EXPORT_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        logger.warning(
            "task_run.otlp_log_export_rejected",
            run_id=run_id,
            status_code=response.status_code,
            body=response.text[:500],
        )
