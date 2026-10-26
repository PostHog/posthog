from datetime import timedelta

# A new experiment often has no exposure in its first hours, so the zero exposures finding waits as long as the
# experiments scout does.
ZERO_EXPOSURES_GRACE_HOURS = 24

# `last_called_at` moves only when `sync_feature_flag_last_called` runs, every 30 minutes (`posthog/tasks/scheduled.py`).
# A run reads the calls up to a buffer before its start (`FEATURE_FLAG_LAST_CALLED_AT_SYNC_*_BUFFER_SECONDS`, 1 or 6
# minutes by default), so a call waits up to one interval plus that buffer. Update both when the schedule changes, and
# keep them equal: the findings say the text, and the context waits the duration.
LAST_CALLED_AT_LAG = "an hour"
LAST_CALLED_AT_LAG_DURATION = timedelta(hours=1)
