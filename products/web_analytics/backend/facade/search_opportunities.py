import hashlib
import datetime as dt
from collections.abc import Mapping

# These thresholds describe a page that already ranks and has enough impressions to make a low
# click-through rate actionable. Signals and Web Analytics use the same values through this facade.
GSC_MIN_IMPRESSIONS = 100
GSC_MAX_CTR = 0.02
GSC_MAX_POSITION = 20.0

# Google publishes Search Console data in arrears. The trailing window catches missed schedules, and
# the Signals emission record prevents rows in the overlapping window from being emitted twice.
GSC_LOOKBACK_DAYS = 7
GSC_FIELDS = ("date", "query", "page", "clicks", "impressions", "ctr", "position")
OPPORTUNITY_WHERE_CLAUSE = (
    f"impressions >= {GSC_MIN_IMPRESSIONS} AND ctr < {GSC_MAX_CTR} AND position <= {GSC_MAX_POSITION}"
)


def search_opportunity_date(value: object) -> str:
    if isinstance(value, dt.datetime | dt.date):
        return value.date().isoformat() if isinstance(value, dt.datetime) else value.isoformat()
    return str(value)[:10]


def search_opportunity_source_id(record: Mapping[str, object]) -> str:
    """Return a stable identifier that stays bounded when page URLs and queries are unbounded."""
    key = f"{record.get('page', '')}\n{record.get('query', '')}".encode()
    return f"{search_opportunity_date(record.get('date'))}:{hashlib.sha256(key).hexdigest()}"


def search_opportunity_weight(impressions: int) -> float:
    """Cap large opportunities below 1.0 so a single search day cannot dominate signal ranking."""
    return round(min(0.95, 0.5 + impressions / 50000), 3)


def build_search_opportunity_description(
    page: str,
    query: str,
    date_str: str,
    impressions: int,
    clicks: int,
    ctr: float,
    position: float,
) -> str:
    ctr_pct = round(ctr * 100, 2)
    position_str = round(position, 1)
    return (
        f"Search ranking opportunity for {page}. "
        f'On {date_str} this page appeared in Google Search results for the query "{query}" '
        f"{impressions} times but was clicked only {clicks} times, a {ctr_pct}% click-through rate, "
        f"while ranking at average position {position_str}. "
        f"A click-through rate this low for a page already ranking near the first page of results usually "
        f"means the search result title or meta description is not compelling for this query, or the page "
        f"does not match what searchers expect. Improving the title and description for this query, or the "
        f"page content itself, could recover lost organic traffic."
    )
