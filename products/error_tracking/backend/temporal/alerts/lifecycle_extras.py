"""The lifecycle extras that alert and Inbox filters read, and how they cross Temporal.

The internal event carries these properties as their producers set them. The alert path forwards them as
strings and drops nulls, so the filter evaluator restores numbers and nulls to match the internal event.
"""

# Spike measurements. Filters compare them as numbers; every other extra, such as a release version
# like "1.10", stays a string.
NUMERIC_EXTRA_KEYS = frozenset({"computed_baseline", "current_bucket_value"})

# Set on every ingestion reopen. The release keys are null when no release reopened the issue.
REOPEN_EXTRA_KEYS = (
    "reopen_reason",
    "reopened_by_release_version",
    "reopened_by_release_project",
    "reopened_by_release_id",
)

# Extras an event always carries, null included, so an exception property of the same name cannot stand in
# for a missing one.
EVENT_EXTRA_KEYS: dict[str, tuple[str, ...]] = {"$error_tracking_issue_reopened": REOPEN_EXTRA_KEYS}

# Every extra the alert path forwards to the filters.
FORWARDED_EXTRA_KEYS = NUMERIC_EXTRA_KEYS | frozenset(REOPEN_EXTRA_KEYS)
