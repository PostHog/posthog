from .analytics import capture
from .models import Account, DailyReport


def render_report_email(account: Account, report: DailyReport) -> str:
    dollars = report.total_cents / 100
    lines = [
        f"Hi {account.name},",
        "",
        f"Your Acme summary for {report.date}:",
        f"  Orders: {report.order_count}",
        f"  Revenue: ${dollars:,.2f}",
    ]
    if report.order_count == 0:
        lines.append("  (No orders recorded for this day.)")
    return "\n".join(lines)


def send_report_email(account: Account, report: DailyReport) -> None:
    body = render_report_email(account, report)
    # SMTP relay in production; local runs just print.
    print(f"--- to: {account.email} ---\n{body}\n")
    capture(account.id, "report_emailed", {"report_date": report.date})
