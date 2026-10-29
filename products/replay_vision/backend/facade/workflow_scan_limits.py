"""Default daily limits on Replay Vision scans that workflow steps request.

A module of its own, free of imports, so the team settings serializer can read it cheaply.
"""

# A project raises its own limits in settings up to the self-serve ceiling; support goes past it in admin.
WORKFLOW_SCAN_RATE_CAP_PER_DAY = 100
WORKFLOW_SCAN_TEAM_RATE_CAP_PER_DAY = 500
MAX_SELF_SERVE_WORKFLOW_SCAN_RATE_CAP_PER_DAY = WORKFLOW_SCAN_RATE_CAP_PER_DAY * 5
MAX_SELF_SERVE_WORKFLOW_SCAN_TEAM_RATE_CAP_PER_DAY = WORKFLOW_SCAN_TEAM_RATE_CAP_PER_DAY * 5
