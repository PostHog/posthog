"""Session eligibility limits shared by the query layer and the temporal package.

A leaf module: the candidate queries need these, and importing them from `temporal.constants`
would pull the whole temporal package (workflows + activities) into the query layer's import chain.
"""

# Capped so `replay-vision-apply-scanner-{scanner_uuid:36}-{session_id}` fits the 255-char `ReplayObservation.workflow_id` column.
MAX_SESSION_ID_LENGTH = 128

# Sessions shorter than this don't carry enough signal for the LLM to analyze.
MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S = 15

# Sessions with less than this much actual interaction are skipped — they're mostly idle.
MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S = 10

# Sessions with more than 1 hour of active interaction take too long to analyze well.
MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S = 3600
