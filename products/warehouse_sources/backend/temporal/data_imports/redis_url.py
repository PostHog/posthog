from django.conf import settings


def data_warehouse_redis_url() -> str:
    """The dedicated warehouse Redis, or the shared instance when none is configured.

    DATA_WAREHOUSE_REDIS_HOST/PORT are optional — an install without a dedicated warehouse
    Redis relies on this falling back to REDIS_URL (which settings refuses to start without),
    rather than on every caller treating the unset host as a hard failure.
    """
    if settings.DATA_WAREHOUSE_REDIS_HOST and settings.DATA_WAREHOUSE_REDIS_PORT:
        return f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/"
    return settings.REDIS_URL
