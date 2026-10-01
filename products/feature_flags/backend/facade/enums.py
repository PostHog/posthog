"""Exported enums for feature_flags."""

from posthog.enums import LabeledIntEnum


class FlagEvaluationsMode(LabeledIntEnum):
    """Which table the product reads an organization's $feature_flag_called data from. This field does not
    control ingestion. The INGESTION_FLAG_EVALUATIONS_TEAMS allowlist in FlagEvaluationsService
    decides which teams ingestion also writes to flag_evaluations. FLAG_EVALUATIONS_ONLY is
    reserved for the ingestion change that stops the events writes.
    """

    # The Usage tab reads the events table. The flag_evaluations HogQL table stays hidden unless
    # the flag-evaluations-hogql-table flag is on for the organization.
    EVENTS = 0, "Events"
    # The Usage tab reads flag_evaluations, and the HogQL table is visible.
    READ_FLAG_EVALUATIONS = 1, "Read flag evaluations"
    # As READ_FLAG_EVALUATIONS, and ingestion stops writing $feature_flag_called to events. Ingestion
    # ignores this mode until the change that implements it deploys. Until then the mode acts as
    # READ_FLAG_EVALUATIONS. An organization already on this mode stops the events writes when that
    # change deploys.
    FLAG_EVALUATIONS_ONLY = 2, "Flag evaluations only"
