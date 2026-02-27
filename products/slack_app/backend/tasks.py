import structlog

logger = structlog.get_logger(__name__)


def process_twig_task_termination(payload: dict) -> None:
    """Backwards-compatible wrapper for terminate handling."""
    from posthog.temporal.ai.twig_slack_interactivity import process_twig_task_termination_payload

    process_twig_task_termination_payload(payload)
