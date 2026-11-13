"""Exported enums for feature_flags."""

from posthog.enums import LabeledIntEnum


class FlagEvaluationsMode(LabeledIntEnum):
    """Which table the product reads an organization's $feature_flag_called data from, and whether ingestion still
    writes it to events. On PostHog Cloud, ingestion copies every team's flag calls to flag_evaluations on every
    mode, except the teams in INGESTION_FLAG_EVALUATIONS_EXCLUDED_TEAMS.
    """

    # Every reader of $feature_flag_called reads the events table.
    EVENTS = 0, "Events"
    # These readers read flag_evaluations:
    # - The flag Usage tab, the per-project counts on a flag's Projects tab, events lists filtered to only
    #   $feature_flag_called, and the "For you today" highlights that count flag calls and experiment enrollments.
    # - A HogQL read of events that pins `event` to $feature_flag_called, pins `$feature_flag` to string keys, and
    #   starts within the FLAG_EVALUATIONS_COMPLETE_DAYS that flag_evaluations covers. Insights, SQL and the cohort
    #   batch calculation go through this swap. A default experiment exposure, which also reads $experiment_exposure,
    #   does not match it and reads events.
    # The event pickers also hide $feature_flag_called. The actions API refuses a new step on it, and the cohorts
    # API refuses a new criterion on it that the batch calculation would read from events.
    # Ingestion still writes every flag call to events, so FLAG_EVALUATIONS_READS_FORCE_EVENTS can move all of this
    # back to events.
    READ_FLAG_EVALUATIONS = 1, "Read flag evaluations"
    # As READ_FLAG_EVALUATIONS, and ingestion stops writing $feature_flag_called to events for the teams it copies to
    # flag_evaluations. INGESTION_FLAG_EVALUATIONS_ONLY_DISABLED makes ingestion treat this mode as
    # READ_FLAG_EVALUATIONS for every organization. Because events holds no new flag calls:
    # - The HogQL swap drops its date and `$feature_flag` conditions. A HogQL read of only flag calls that cannot
    #   swap raises a QueryError instead of reading events.
    # - The cohorts API also refuses a new flag-call criterion on a realtime cohort.
    # - Flags keep no `last_called_at` unless FEATURE_FLAG_LAST_CALLED_AT_SYNC_SOURCE is "flag_evaluations".
    FLAG_EVALUATIONS_ONLY = 2, "Flag evaluations only"


# The activity log trigger `job_type` of a flag save that a scheduled change applies.
SCHEDULED_CHANGE_JOB_TYPE = "scheduled_change"

# The activity log trigger `job_type` of a flag save that restores a past version. Its `payload` carries
# `restored_from_version`, the version the flag was set back to.
VERSION_RESTORE_JOB_TYPE = "version_restore"
