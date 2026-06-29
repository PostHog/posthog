from datetime import timedelta

from django.db.models import QuerySet

from temporalio import common

from posthog.models.organization import Organization

ACTIVITY_RETRY_POLICY = common.RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
)


def paginate_index(items: list[str], cursor: str | None, page_size: int) -> tuple[list[str], str | None]:
    start = int(cursor) if cursor is not None else 0
    page = items[start : start + page_size]
    next_index = start + len(page)
    next_cursor = str(next_index) if next_index < len(items) else None
    return page, next_cursor


def paginate_keyset(qs: QuerySet[Organization], cursor: str | None, page_size: int) -> tuple[list[str], str | None]:
    if cursor is not None:
        qs = qs.filter(id__gt=cursor)
    fetched = [str(oid) for oid in qs.order_by("id").values_list("id", flat=True)[: page_size + 1]]
    page = fetched[:page_size]
    has_more = len(fetched) > page_size
    next_cursor = page[-1] if has_more and page else None
    return page, next_cursor
