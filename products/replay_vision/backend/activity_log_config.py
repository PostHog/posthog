# Machine-written. A test asserts this covers `ReplayScanner._MACHINE_OWNED_FIELDS`, a narrower set.
replay_scanner_machine_fields = [
    "scanner_version",
    "origin",
    "inline_key",
    "primed_at",
    "last_swept_at",
    "last_seen_session_id",
    "deep_swept_through",
    "deep_seen_session_id",
    "deep_attempted_at",
    "sweep_read_bytes_by_hour",
    "fast_read_bytes_by_hour",
    "deep_read_bytes_by_hour",
    "sweep_throttle_factor",
    "last_found_candidates_at",
    "sweep_paused_until",
    "sweep_pause_reason",
    "estimated_monthly_observations",
    "estimated_at",
    "estimate_attempted_at",
    "filter_error",
    "filter_error_at",
    "prompt_question",
    "prompt_question_source",
    "prompt_valence",
    "limit_notified_period_start",
    "admission_budget_used",
    "admission_budget_refreshed_at",
    "admission_budget_period_start",
    "admission_credits_since_refresh",
    "updated_at",
]


# Rewritten on every check; an alert's firing history is read from its own event log instead.
vision_alert_machine_fields = [
    "state",
    "consecutive_failures",
    "last_checked_at",
    "last_notified_at",
    "next_check_at",
    "first_enabled_at",
    # The engine passes this alongside next_check_at on every suppressed check.
    "updated_at",
]


FIELD_EXCLUSIONS = {
    # The reverse relations are listed because the diff reads each one in full; a scanner's
    # observations run to millions of rows, and its alerts carry their own audit trail.
    "ReplayScanner": [
        *replay_scanner_machine_fields,
        "observations",
        "backfills",
        "learned_rulesets",
        "alerts",
    ],
    "VisionAlertConfiguration": [*vision_alert_machine_fields, "events", "matches"],
}


FIELD_WITH_MASKED_CONTENTS = {
    # Observation notes are gated on observation access, which activity_log:read does not imply.
    "ReplayObservation": ["content"],
}


SIGNAL_EXCLUSIONS = {
    "ReplayScanner": replay_scanner_machine_fields,
    "VisionAlertConfiguration": vision_alert_machine_fields,
}
