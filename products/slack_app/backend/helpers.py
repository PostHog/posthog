from django.conf import settings


def local_dev_slack_email() -> str | None:
    """Return the seeded fixture email to force during local dev, or None.

    Lets local setups skip Slack's users.info lookup and match the seeded test
    user. Returns None outside DEBUG, or when the email is set empty, so callers
    can treat it as "no override" and fall through to the real Slack email.
    """
    if not settings.DEBUG:
        return None
    return settings.SLACK_APP_LOCAL_DEV_EMAIL.strip() or None
