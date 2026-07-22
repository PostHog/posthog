"""Curated query: merged-PR throughput per time bucket.

Counts PRs by merged_at on the shared window bucketing (hour / day / week), zero-filled
across the whole window: for a count, an empty bucket is a real 0 (nothing merged), not a
gap, unlike the median series where an empty bucket must stay None. Bots are excluded per
the locked throughput rule (SPEC section 6); a merged PR is never a draft, so no draft
filter is needed.

The window start is floored to its bucket boundary before filtering. A raw relative
date_from lands mid-bucket (relative_date_parse keeps wall-clock time), and filtering
from there while the zero-fill spine starts at the bucket boundary would silently
undercount the first bucket: a partial count reads as a real dip, where a partial median
would still be a valid median. After flooring, every bucket is complete except the
trailing in-progress one.
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import MergeActivity, MergeActivityBucket
from products.engineering_analytics.backend.logic.queries._buckets import (
    Granularity,
    bucket_expr,
    normalize_bucket,
    pick_granularity,
    window_buckets,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

_SELECT = """
    SELECT
        __BUCKET_FN__ AS bucket_start,
        countIf(NOT is_bot) AS merged_count
    FROM __PR_SOURCE__ AS pr
    WHERE merged_at IS NOT NULL AND merged_at >= {date_from} __DATE_TO__
    GROUP BY bucket_start
    LIMIT 40000
"""


def _floor_to_bucket(moment: datetime, granularity: Granularity) -> datetime:
    """Align a window bound down to its bucket start, keeping the timezone the spine drops."""
    return normalize_bucket(moment, granularity).replace(tzinfo=moment.tzinfo)


def query_merge_activity(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
) -> MergeActivity:
    granularity = pick_granularity(date_from, date_to)
    date_from = _floor_to_bucket(date_from, granularity)
    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from)}
    date_to_clause = "AND merged_at <= {date_to}" if date_to is not None else ""
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
    sql = (
        _SELECT.replace("__PR_SOURCE__", curated.pr_source())
        .replace("__DATE_TO__", date_to_clause)
        .replace("__BUCKET_FN__", bucket_expr(granularity, "merged_at"))
    )
    response = curated.run(sql, query_type="engineering_analytics.merge_activity", placeholders=placeholders)
    count_by_bucket = {
        normalize_bucket(bucket_start, granularity): int(merged_count or 0)
        for bucket_start, merged_count in response.results or []
    }
    return MergeActivity(
        granularity=granularity,
        buckets=[
            MergeActivityBucket(bucket_start=bucket, merged_count=count_by_bucket.get(bucket, 0))
            for bucket in window_buckets(date_from, date_to, granularity)
        ],
    )
