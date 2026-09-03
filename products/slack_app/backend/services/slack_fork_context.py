"""Which thread a forked DM came from, held between two Slack deliveries.

A fork opens a DM and asks what the user wants to know, so the run does not start
until they answer. Their answer arrives as a separate `message.im` event with
nothing on it to say the thread is a fork — the mapping that would say so is
written by task creation, which has not happened yet.

This bridges that gap: the fork stores the source thread against the DM it just
opened, and the DM handler reads it back when the reply lands. Once the run
exists the `SlackThreadTaskMapping` takes over and the entry is dropped.

Cache rather than a table because the window is one reply long. Losing the entry
degrades to an ordinary DM — the agent answers without the forked thread's
context, and the seed message still links to it — rather than failing.
"""

from django.core.cache import cache

import structlog
from pydantic import BaseModel, ValidationError

logger = structlog.get_logger(__name__)


class PendingFork(BaseModel):
    """The thread a forked DM came from, and the posture it inherits.

    ``is_ext_shared`` travels with it because a DM is never externally shared: without
    it the run would lose the approval gate that keeps customer-facing writes gated for
    content that started life in a Slack Connect channel.
    """

    source_channel: str
    source_thread_ts: str
    # Where in the thread the reader forked. The context block stops here.
    source_message_ts: str | None = None
    # Set when the forked thread was already being worked on. Points the fork at that
    # task's own history — prior runs, session logs, artifacts — which holds far more
    # than the Slack messages ever showed.
    task_id: str | None = None
    is_ext_shared: bool = False


# Long enough to survive stepping away mid-thought, short enough that a DM thread
# abandoned for a day doesn't silently pick up a stale fork on its next message.
FORK_CONTEXT_TTL_SECONDS = 6 * 60 * 60


def _key(integration_id: int, dm_channel: str, thread_ts: str) -> str:
    return f"slack_app_fork_ctx:{integration_id}:{dm_channel}:{thread_ts}"


def store_pending_fork(integration_id: int, dm_channel: str, thread_ts: str, fork: PendingFork) -> None:
    # Stored as a plain dict rather than the model so an entry written before a field
    # was added or renamed can't fail to load — `get_pending_fork` validates on the way
    # back out and treats anything it no longer understands as absent.
    cache.set(_key(integration_id, dm_channel, thread_ts), fork.model_dump(), timeout=FORK_CONTEXT_TTL_SECONDS)


def get_pending_fork(integration_id: int, dm_channel: str, thread_ts: str) -> PendingFork | None:
    value = cache.get(_key(integration_id, dm_channel, thread_ts))
    if not isinstance(value, dict):
        return None
    try:
        return PendingFork(**value)
    except ValidationError:
        logger.warning("slack_app_fork_context_invalid", dm_channel=dm_channel, thread_ts=thread_ts)
        return None


def clear_pending_fork(integration_id: int, dm_channel: str, thread_ts: str) -> None:
    """Drop the entry once the reply that consumes it has been dispatched.

    The run it starts writes a ``SlackThreadTaskMapping`` for this DM thread, and every
    later message is a follow-up against that. Leaving the entry would re-apply the
    forked thread as fresh context to a message that already has its own history.
    """
    cache.delete(_key(integration_id, dm_channel, thread_ts))
