from datetime import timedelta

HOME_TAB_FLAG = "posthog-code-home-tab"

ACTIVITY_WINDOW = timedelta(days=30)

MAX_PRS_PER_TEAM_PER_CYCLE = 50
MAX_TASKS_PER_TEAM = 500
MAX_TEAMS_PER_CYCLE = 2000

# Branch-based PR discovery makes one GitHub API call per unique (repo, branch). Cap the number of
# branches we probe per team per cycle so a team with many active branches can't blow the cycle's
# GitHub budget. Independent of MAX_PRS_PER_TEAM_PER_CYCLE since one branch yields 0..n PRs.
MAX_BRANCH_QUERIES_PER_TEAM_PER_CYCLE = 30

TEAM_FANOUT_CONCURRENCY = 20
