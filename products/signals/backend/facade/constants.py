from datetime import UTC, datetime

from dateutil.relativedelta import relativedelta

SIGNAL_SPEND_RETENTION = relativedelta(months=3)
SIGNAL_USAGE_START = datetime(2026, 10, 1, tzinfo=UTC)
