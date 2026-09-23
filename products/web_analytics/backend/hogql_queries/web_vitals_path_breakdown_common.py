"""Shared between the raw and the lazy-precomputed web vitals path breakdown, so
both paths band, filter and sort the same rows."""

from posthog.schema import WebVitalsPathBreakdownQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

# A percentile over a single measurement is not evidence that a page is slow, and
# the tile only shows 20 rows per band, so without a floor the long tail crowds out
# the pages worth acting on. Callers that want the whole tail can pass 1.
DEFAULT_MINIMUM_OCCURRENCES = 10


def minimum_occurrences(query: WebVitalsPathBreakdownQuery) -> int:
    if query.minimumOccurrences is None:
        return DEFAULT_MINIMUM_OCCURRENCES
    return max(query.minimumOccurrences, 0)


def band_sort_expr() -> ast.Expr:
    """Sort the poor band worst-first and the other two best-first.

    A single `ORDER BY value ASC` with `LIMIT 20 BY band` keeps the 20 least-poor
    paths in the poor column and drops the slowest pages, which is the opposite of
    what that column is for.
    """
    return parse_expr("if(band = 'poor', -value, value)")
