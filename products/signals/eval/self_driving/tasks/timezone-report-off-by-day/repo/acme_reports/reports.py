from datetime import UTC, datetime, time, timedelta

from .analytics import capture
from .models import Account, DailyReport
from .store import InMemoryStore


def generate_daily_report(store: InMemoryStore, account: Account, now: datetime | None = None) -> DailyReport:
    """Build the account's summary for the day containing `now`."""
    if now is None:
        now = datetime.now(tz=UTC)
    report_date = now.date()
    start = datetime.combine(report_date, time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    orders = store.orders_between(account.id, start, end)
    report = DailyReport(
        account_id=account.id,
        date=report_date.isoformat(),
        order_ids=tuple(order.id for order in orders),
        order_count=len(orders),
        total_cents=sum(order.total_cents for order in orders),
    )
    capture(
        account.id,
        "report_generated",
        {
            "report_date": report.date,
            "order_count": report.order_count,
            "total_cents": report.total_cents,
            "account_timezone": account.timezone,
        },
    )
    return report
