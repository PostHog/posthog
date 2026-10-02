"""Exported enums for feature_flags."""

from posthog.enums import LabeledIntEnum


class FlagEvaluationsMode(LabeledIntEnum):
    """Which table the product reads an organization's $feature_flag_called data from. The
    INGESTION_FLAG_EVALUATIONS_TEAMS allowlist in FlagEvaluationsService decides which teams ingestion
    writes to flag_evaluations. FLAG_EVALUATIONS_ONLY also stops the events writes for the teams that
    allowlist includes.
    """

    # The Usage tab reads the events table. The flag_evaluations HogQL table stays hidden unless
    # the flag-evaluations-hogql-table flag is on for the organization.
    EVENTS = 0, "Events"
    # The Usage tab reads flag_evaluations, and the HogQL table is visible.
    READ_FLAG_EVALUATIONS = 1, "Read flag evaluations"
    # As READ_FLAG_EVALUATIONS, and ingestion stops writing $feature_flag_called to events. Some readers
    # stay on events in READ_FLAG_EVALUATIONS and read flag_evaluations only in this mode. A team
    # outside the ingestion allowlist still writes to events. INGESTION_FLAG_EVALUATIONS_ONLY_DISABLED
    # makes ingestion treat this mode as READ_FLAG_EVALUATIONS for every organization.
    FLAG_EVALUATIONS_ONLY = 2, "Flag evaluations only"
