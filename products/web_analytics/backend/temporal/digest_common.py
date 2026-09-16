import dataclasses
from datetime import timedelta
from typing import Self

from django.db.models import QuerySet

from temporalio import common

from posthog.models.organization import Organization

ACTIVITY_RETRY_POLICY = common.RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
)


@dataclasses.dataclass(frozen=True)
class OrgBatchPageResult:
    batches: list[list[str]]
    cursor: str | None

    @property
    def org_count(self) -> int:
        return sum(len(batch) for batch in self.batches)

    @property
    def batch_count(self) -> int:
        return len(self.batches)


@dataclasses.dataclass(frozen=False)
class DigestBatchTotals:
    """`failure_rate` excludes `orgs_skipped`: digest skips are benign
    pre-processing exclusions (no targeted members, no teams, race-deleted
    org), not detector errors, so they shouldn't trip the workflow's threshold
    alarm.
    """

    batch_size: int = 0
    orgs_processed: int = 0
    orgs_skipped: int = 0
    orgs_failed: int = 0
    teams_failed: int = 0
    build_duration: float = 0.0
    send_duration: float = 0.0

    @property
    def total_duration(self) -> float:
        return self.build_duration + self.send_duration

    @property
    def failure_rate(self) -> float:
        attempted = self.orgs_processed + self.orgs_failed
        return self.orgs_failed / attempted if attempted > 0 else 0.0

    def __iadd__(self, other: Self) -> Self:
        for f in dataclasses.fields(self):
            setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))
        return self


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
