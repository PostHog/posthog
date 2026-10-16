from django.conf import settings


def retry_budget_seconds() -> float:
    """The longest time one request may spend on retries, from its first failure."""
    return settings.DATA_WAREHOUSE_SOURCE_RETRY_BUDGET_SECONDS


def max_retry_after_seconds() -> float:
    """The longest server-provided retry delay that shared code waits for."""
    return settings.DATA_WAREHOUSE_SOURCE_MAX_RETRY_AFTER_SECONDS
