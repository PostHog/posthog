"""Boot-time checks of the stacks configuration. IDs follow the scheme at the top of posthog/checks.py.

Warnings, not errors: a region that has not provisioned stacks yet still boots, and the API answers 503
`stacks_unavailable` until it has.
"""

from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Warning

from posthog.checks import register_check

STACKS_ENCRYPTION_KEYS_MISSING = "posthog.stacks.W001"
STACKS_DATABASE_MISSING = "posthog.stacks.W002"


@register_check(STACKS_ENCRYPTION_KEYS_MISSING, STACKS_DATABASE_MISSING, tags=["stacks"])
def check_stacks_settings(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    if settings.DEBUG or settings.TEST:
        return []
    messages: list[CheckMessage] = []
    if not any(key for key in settings.STACKS_ENCRYPTION_KEYS):
        messages.append(
            Warning(
                "STACKS_ENCRYPTION_KEYS is not set, so stacks refuse every diff, push and secret.",
                hint="Set it to one or more comma-separated Fernet keys, newest first, unique to this environment.",
                id=STACKS_ENCRYPTION_KEYS_MISSING,
            )
        )
    if "stacks_db_writer" not in settings.DATABASES:
        messages.append(
            Warning(
                "PRODUCT_DB_STACKS_WRITER_URL is not set, so stacks refuse all work instead of using the main database.",
                hint="Provision the stacks product database and set its writer URL.",
                id=STACKS_DATABASE_MISSING,
            )
        )
    return messages
