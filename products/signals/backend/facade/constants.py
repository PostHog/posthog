from datetime import UTC, datetime

from dateutil.relativedelta import relativedelta

SIGNAL_SPEND_RETENTION = relativedelta(months=3)
SIGNAL_USAGE_START = datetime(2026, 10, 1, tzinfo=UTC)

# A suggestion row shows its goal as one line of plain text. The producer clears a longer goal, so the
# row falls back to the description, and the API refuses one on write.
MAX_SCOUT_SUGGESTION_GOAL_CHARS = 200
