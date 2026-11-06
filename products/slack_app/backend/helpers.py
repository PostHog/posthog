from django.conf import settings


def slack_app_mention_queue_workflow_id(slack_workspace_id: str, channel: str, thread_ts: str) -> str:
    """Conversation-scoped id of the queue workflow that serializes a thread's mentions.

    Lives here, away from the workflow module, so a caller that only needs the id — the
    dispatcher, or the debug endpoint reconstructing it from a stored thread mapping —
    does not import the Temporal workflow tree to build a string.
    """
    return f"slack-app-mention-{slack_workspace_id}:{channel}:{thread_ts}"


def local_dev_slack_email() -> str | None:
    """Return the seeded fixture email to force during local dev, or None.

    Lets local setups skip Slack's users.info lookup and match the seeded test
    user. Returns None outside DEBUG, or when the email is set empty, so callers
    can treat it as "no override" and fall through to the real Slack email.
    """
    if not settings.DEBUG:
        return None
    return settings.SLACK_APP_LOCAL_DEV_EMAIL.strip() or None
