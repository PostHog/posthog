from collections.abc import Iterator
from contextlib import contextmanager, suppress

from posthog.clickhouse.client.limit import ConcurrencySlot, RateLimit

WIDGET_GENERATION_GLOBAL_CONCURRENCY = 12
_SLOT_TTL_SECONDS = 20 * 60

__GLOBAL_LIMITER: RateLimit | None = None


def _get_global_limiter() -> RateLimit:
    global __GLOBAL_LIMITER
    if __GLOBAL_LIMITER is None:
        __GLOBAL_LIMITER = RateLimit(
            max_concurrency=WIDGET_GENERATION_GLOBAL_CONCURRENCY,
            limit_name="notebook_widget_generation_global",
            get_task_name=lambda *args, **kwargs: "notebooks:widget-generation:global",
            get_task_id=lambda *args, **kwargs: kwargs["job_id"],
            ttl=_SLOT_TTL_SECONDS,
            apply_clickhouse_kill_switch=False,
            allow_team_bypass=False,
        )
    return __GLOBAL_LIMITER


@contextmanager
def widget_generation_slot(*, team_id: int, job_id: str) -> Iterator[None]:
    limiter = _get_global_limiter()
    slot: ConcurrencySlot | None = limiter.use(team_id=team_id, job_id=job_id)
    try:
        yield
    finally:
        if slot is not None:
            with suppress(Exception):
                limiter.release(slot)
