from datetime import timedelta

HOME_TAB_FLAG = "posthog-code-home-tab"

# Kill switch for auto-running quick actions. Independent of HOME_TAB_FLAG so the
# feature can be dark-launched / rolled out gradually and turned off instantly.
HOME_AUTO_ACTIONS_FLAG = "posthog-code-home-auto-actions"

# Upper bound on cloud tasks the auto-run step will start for one team in a single
# cycle — a blast-radius guard so a misconfiguration can't fan out unbounded work.
MAX_AUTO_RUNS_PER_TEAM = 10

ACTIVITY_WINDOW = timedelta(days=30)

MAX_PRS_PER_TEAM_PER_CYCLE = 50
MAX_TASKS_PER_TEAM = 500
MAX_TEAMS_PER_CYCLE = 2000

# Caps GitHub API calls per cycle (one per unique repo+branch); separate from
# MAX_PRS_PER_TEAM_PER_CYCLE because one branch can yield 0..n PRs.
MAX_BRANCH_QUERIES_PER_TEAM_PER_CYCLE = 30

TEAM_FANOUT_CONCURRENCY = 20
