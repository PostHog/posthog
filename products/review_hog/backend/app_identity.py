from posthog.models.instance_setting import get_instance_setting


def posthog_app_login() -> str | None:
    """The lowercased login GitHub gives the PostHog GitHub App (`<slug>[bot]`), or None when no slug is set.

    ReviewHog posts as this App, so it is also the only author whose markers and comments ReviewHog trusts.
    Compare logins in lowercase, because GitHub treats them as case-insensitive.
    """
    slug = get_instance_setting("GITHUB_APP_SLUG")
    return f"{slug}[bot]".lower() if slug else None
