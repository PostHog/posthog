from datetime import timedelta

HOME_TAB_FLAG = "posthog-code-home-tab"

ACTIVITY_WINDOW = timedelta(days=30)

MAX_PRS_PER_TEAM_PER_CYCLE = 50
MAX_TASKS_PER_TEAM = 500
MAX_TEAMS_PER_CYCLE = 2000

# Caps GitHub API calls per cycle (one per unique repo+branch); separate from
# MAX_PRS_PER_TEAM_PER_CYCLE because one branch can yield 0..n PRs.
MAX_BRANCH_QUERIES_PER_TEAM_PER_CYCLE = 30

TEAM_FANOUT_CONCURRENCY = 20
