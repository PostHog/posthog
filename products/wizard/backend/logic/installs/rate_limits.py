from django.core.cache import cache
from django.utils import timezone

from products.wizard.backend.facade.errors import WizardInstallDailyLimitError
from products.wizard.backend.logic.installs.config import TOKEN_DAILY_RUN_COUNTER_TTL, TOKEN_DAILY_RUN_LIMIT


def reserve_token_daily_run(user_id: int) -> str:
    """
    Count one run against the user's daily limit for runs started with an OAuth access token.

    The counter spans all projects, so an agent cannot get around it by moving to another project.
    Returns the counter key, which `release_token_daily_run` takes when no run was created.
    """
    key = f"wizard-install:token-daily-runs:{user_id}:{timezone.now().date().isoformat()}"
    timeout = int(TOKEN_DAILY_RUN_COUNTER_TTL.total_seconds())
    cache.add(key, 0, timeout=timeout)
    try:
        count = cache.incr(key)
    except ValueError:
        # The counter expired between `add` and `incr`.
        cache.add(key, 1, timeout=timeout)
        count = 1

    if count > TOKEN_DAILY_RUN_LIMIT:
        release_token_daily_run(key)
        raise WizardInstallDailyLimitError

    return key


def release_token_daily_run(key: str) -> None:
    try:
        cache.decr(key)
    except ValueError:
        pass
