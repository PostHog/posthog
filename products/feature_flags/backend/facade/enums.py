"""Exported enums for feature_flags."""

from posthog.enums import LabeledIntEnum


class FlagEvaluationsMode(LabeledIntEnum):
    """Which table the product reads an organization's $feature_flag_called data from. The
    INGESTION_FLAG_EVALUATIONS_TEAMS allowlist in FlagEvaluationsService decides which teams ingestion
    writes to flag_evaluations. FLAG_EVALUATIONS_ONLY also stops the events writes for the teams that
    allowlist includes.
    """

    # Every reader of $feature_flag_called reads the events table. The flag_evaluations HogQL table stays
    # hidden unless the flag-evaluations-hogql-table flag is on for the organization.
    EVENTS = 0, "Events"
    # The Usage tab, the per-project counts on a flag's Projects tab, and events lists filtered to only
    # $feature_flag_called read flag_evaluations. Other readers, such as experiment exposures, still read events.
    # The HogQL table is visible.
    # Ingestion still writes every flag call to events, so FLAG_EVALUATIONS_READS_FORCE_EVENTS can move these
    # readers back to events.
    READ_FLAG_EVALUATIONS = 1, "Read flag evaluations"
    # As READ_FLAG_EVALUATIONS, and ingestion stops writing $feature_flag_called to events. A team outside
    # the ingestion allowlist still writes to events. INGESTION_FLAG_EVALUATIONS_ONLY_DISABLED makes
    # ingestion treat this mode as READ_FLAG_EVALUATIONS for every organization.
    FLAG_EVALUATIONS_ONLY = 2, "Flag evaluations only"
