"""Pull request links that people post in a Broadcast channel.

The slack_app product receives every channel message and offers each top-level post by a person to the
handlers in ``posthog.slack.channel_messages``. stamphog registers there, because a direct import of
stamphog would make a dependency cycle.
"""

from __future__ import annotations

from posthog.slack.channel_messages import ChannelMessage, register_channel_message_handler


def handle_channel_message(message: ChannelMessage) -> bool:
    """Take a post whose pull request links name a repository that uses this channel for Broadcast.

    Runs inside Slack's event request for every top-level post, so a post without a link stops at the
    pattern, and the channel check is one cached read. The rest runs in a task.
    """
    # Deferred, because connect() runs in AppConfig.ready() and must not load the models and Celery tasks there.
    from products.stamphog.backend.logic.broadcast_links import (  # noqa: PLC0415
        LinkPost,
        broadcast_channel_repositories,
        claim_link_post,
        poster_within_limit,
        pull_request_links,
    )
    from products.stamphog.backend.tasks.broadcast_requests import (  # noqa: PLC0415
        queue_open_broadcast_request_from_link,
    )

    links = pull_request_links(message.text)
    if not links:
        return False
    repositories = broadcast_channel_repositories(message.slack_team_id, message.channel_id)
    links = tuple(link for link in links if link.repository.lower() in repositories)
    if not links:
        return False
    if not claim_link_post(message.slack_team_id, message.channel_id, message.message_ts):
        return True
    if not poster_within_limit(message.slack_team_id, message.slack_user_id):
        return True
    user_ids = message.poster_user_ids()
    if user_ids:
        for link in links:
            queue_open_broadcast_request_from_link(
                LinkPost(
                    slack_team_id=message.slack_team_id,
                    channel_id=message.channel_id,
                    message_ts=message.message_ts,
                    slack_user_id=message.slack_user_id,
                    link=link,
                    link_count=len(links),
                    user_ids=user_ids,
                )
            )
    return True


def connect() -> None:
    register_channel_message_handler("stamphog_broadcast_links", handle_channel_message)
