import structlog

logger = structlog.get_logger(__name__)


def process_posthog_code_task_termination(payload: dict) -> None:
    """Backwards-compatible wrapper for terminate handling."""
    from posthog.temporal.ai.posthog_code_slack_interactivity import process_posthog_code_task_termination_payload

    process_posthog_code_task_termination_payload(payload)
