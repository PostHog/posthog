"""What waits in the dead-letter queues of the SES events SNS subscriptions."""

import structlog
from botocore.exceptions import BotoCoreError, ClientError

from products.workflows.backend.facade.contracts import SesEventsDlqMessage, SesEventsDlqState
from products.workflows.backend.services.ses_events_dlq import (
    INSPECT_SQS_CONFIG,
    DlqMessageSummary,
    DlqQueue,
    configured_queues,
    inspect_queue,
    sqs_client,
)

logger = structlog.get_logger(__name__)


def inspect_ses_events_dlqs() -> list[SesEventsDlqState]:
    return [_inspect(queue) for queue in configured_queues()]


def _inspect(queue: DlqQueue) -> SesEventsDlqState:
    try:
        snapshot = inspect_queue(queue, sqs_client(queue, INSPECT_SQS_CONFIG))
    except (BotoCoreError, ClientError) as error:
        logger.warning("ses_events_dlq.inspect_failed", queue=queue.name, error=str(error))
        return SesEventsDlqState(
            queue_name=queue.name,
            waiting=None,
            in_flight=None,
            oldest_sampled_at=None,
            sample=(),
            error=_short_reason(error),
        )
    return SesEventsDlqState(
        queue_name=queue.name,
        waiting=snapshot.visible,
        in_flight=snapshot.in_flight,
        oldest_sampled_at=snapshot.oldest_sampled_at,
        sample=tuple(_message(summary) for summary in snapshot.sample),
        error=None,
    )


def _short_reason(error: BotoCoreError | ClientError) -> str:
    # The full boto message repeats the operation and the queue URL, which fills the page's table cell.
    # The log line above keeps the full text.
    if isinstance(error, ClientError):
        return error.response.get("Error", {}).get("Code") or type(error).__name__
    return type(error).__name__


def _message(summary: DlqMessageSummary) -> SesEventsDlqMessage:
    return SesEventsDlqMessage(
        message_id=summary.message_id,
        event_type=summary.event_type,
        team_id=summary.team_id,
        masked_recipient=summary.masked_recipient,
        dead_lettered_at=summary.dead_lettered_at,
        replayable=summary.replayable,
    )
