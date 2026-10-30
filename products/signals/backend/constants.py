SIGNALS_FIRST_REPORT_EMAIL_TEMPLATE_ID: str = "01a1598d-9186-0000-b20d-d91813fc05ff"

FIRST_REPORT_SCOUT = "signals-scout-first-report"
SYSTEM_SCOUT_NAMES = frozenset({FIRST_REPORT_SCOUT})
FIRST_REPORT_SCOUT_TIMEOUT_SECONDS = 20 * 60


def first_report_idempotency_key(team_id: int) -> str:
    return f"first-report:{team_id}"
