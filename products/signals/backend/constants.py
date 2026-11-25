SIGNALS_FIRST_REPORT_EMAIL_TEMPLATE_ID: str = "01a1598d-9186-0000-b20d-d91813fc05ff"

# Keep the agent polling budget below the activity timeout so teardown can finish.
DEFAULT_MAX_RUNTIME_S = 30 * 60

FIRST_REPORT_SCOUT = "signals-scout-first-report"
SYSTEM_SCOUT_NAMES = frozenset({FIRST_REPORT_SCOUT})
# Onboarding waits on this run, so it keeps a shorter budget than the fleet.
FIRST_REPORT_SCOUT_TIMEOUT_SECONDS = 20 * 60


def first_report_idempotency_key(team_id: int) -> str:
    return f"first-report:{team_id}"


SCRATCHPAD_REVISIONS_PER_KEY = 10

# `SignalScratchpadRevision.changed_by_identity` of the daily sweep that expires `report:` pointers to a gone
# report. A scout that reads the expired entry sees this name, so it can tell the sweep from another scout.
REPORT_POINTER_SWEEP_IDENTITY = "system:report-pointer-sweep"
