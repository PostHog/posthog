FIELD_EXCLUSIONS = {
    "SignalScoutConfig": [
        # Run bookkeeping, not user intent — keep it out of change detection even when it
        # rides along with a real change (belt-and-suspenders with signal_exclusions above).
        "last_run_at",
        "consecutive_failure_count",
        # Companion bookkeeping that rides along with every logged `status` change; the
        # activity log entry itself already carries who and when.
        "status_changed_at",
        "status_changed_by",
        # Reverse relations auto-managed by FK creates, not user-initiated config changes.
        "runs",
    ],
}


FIELD_NAME_OVERRIDES = {
    "SignalScoutConfig": {
        "run_interval_minutes": "run interval (minutes)",
        "emit": "emit findings",
        "pause_reason": "pause reason",
        "managed_by": "managed by",
        "auto_pause_exempt": "never pause for inactivity",
        "write_scopes": "write access",
        "report_actions": "report actions",
        "max_report_actions_per_day": "report actions per day",
        "lifecycle_locked": "owner-only pause, resume, and delete",
        "allowed_mcp_tools": "allowed MCP tools",
        "tool_preset": "tool preset",
    },
    # Match the labels the inbox settings show, so an entry reads the way the setting was flipped.
    "SignalTeamConfig": {
        "autostart_enabled": "PR generation",
        "default_autostart_priority": "project PR threshold",
        "default_slack_notification_channel": "team Slack channel",
        "default_slack_notification_min_priority": "team Slack minimum priority",
        "autostart_base_branches": "base branch overrides",
        "issue_tracking_integration": "issue tracker",
        "issue_tracking_config": "issue tracker target",
        "default_open_pull_request_ready": "PRs open as",
        "github_issue_writeback_enabled": "comment back on GitHub issues",
        "pull_request_label_enabled": "label self-driving PRs",
        "pull_request_label": "self-driving PR label",
        "anomaly_scoring_enabled": "anomaly scoring",
        "scout_instructions": "scout instructions",
        "research_instructions": "research instructions",
        "implementation_instructions": "implementation instructions",
    },
}


FIELD_WITH_MASKED_CONTENTS = {
    "SignalTeamConfig": ["onboarding"],
    # The rubric API is limited to staff, so saved criteria and generated suggestions must not be
    # readable through activity_log:read. Record that the rubrics changed, never their contents.
    "SignalScoutConfig": ["rubrics"],
}


SIGNAL_EXCLUSIONS = {
    # `last_run_at` is written by the scout coordinator on every tick (~every 15 min per scout),
    # the pre-check fields on every scheduled pre-check, and the failure streak by the runner on
    # every run outcome. When those are the only
    # change, suppress the activity signal entirely so run bookkeeping never spams the audit
    # log. A breaker trip is NOT suppressed: it moves `status`, which logs like any pause.
    "SignalScoutConfig": [
        "last_run_at",
        "consecutive_failure_count",
        "last_precheck_at",
        "last_precheck_outcome",
        "last_precheck_row_count",
    ],
}
