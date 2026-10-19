"""The thread above a Slack message, rendered for the prompt of a run that message started."""

from posthog.models.integration import Integration, SlackIntegration

from products.slack_app.backend.logic.thread_prompt import build_thread_history_block
from products.slack_app.backend.services.slack_messages import collect_thread_messages

# The caller is a workflow fire inside a web request that the workflow engine abandons after
# a few seconds, and it starts the run without the history on any failure. A slow Slack is
# cut short rather than waited on, so the fire does not time out and get retried for it.
THREAD_HISTORY_TIMEOUT_SECONDS = 5


def thread_history_before(integration: Integration, *, channel: str, thread_ts: str, before_ts: str) -> str | None:
    """The thread as it stood before the message at ``before_ts``, framed as a prompt context block.

    ``None`` when nothing was said before ``before_ts``. A Slack read failure raises, so the
    caller decides whether the run still starts without the history.
    """
    slack = SlackIntegration(integration)
    # The bot's own earlier replies stay in: the run reading them is a new agent, not the
    # one that wrote them, and what an earlier run answered in the thread is context too.
    messages = collect_thread_messages(
        slack,
        integration,
        channel,
        thread_ts,
        our_bot_id=None,
        until_ts=before_ts,
        timeout=THREAD_HISTORY_TIMEOUT_SECONDS,
    )
    return build_thread_history_block(messages, before_ts=before_ts)
