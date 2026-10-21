from datetime import datetime
from typing import TYPE_CHECKING

from posthog.schema import DateRange

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

if TYPE_CHECKING:
    from posthog.models import Team

# Metrics dashboards are usually about "what is happening now", so the
# node defaults to a tighter window than the analytics-wide -7d.
DEFAULT_DATE_FROM = "-24h"


def metrics_query_date_range(team: "Team", date_range: DateRange | None) -> QueryDateRange:
    # The facade picks and aligns the bucket interval, so this passes interval=None.
    # With interval=None, QueryDateRange falls back to day. exact_timerange stops it truncating a
    # relative date_from to midnight (so "-30M" would read the whole day), and explicitDate stops it
    # rounding an explicit date_to up to the end of the day.
    return QueryDateRange(
        date_range=DateRange(
            date_from=(date_range.date_from if date_range else None) or DEFAULT_DATE_FROM,
            date_to=date_range.date_to if date_range else None,
            explicitDate=True,
        ),
        team=team,
        interval=None,
        now=datetime.now(),
        exact_timerange=True,
    )
