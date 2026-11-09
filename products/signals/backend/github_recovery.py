from datetime import timedelta

GITHUB_RECOVERY_WINDOW = timedelta(days=7)
GITHUB_ACCESS_FAILURE = "GitHubAccessUnavailable"
GITHUB_RECOVERY_STATE_KEYS = (
    "github_recovery_deadline",
    "github_recovery_repository",
    "github_recovery_user_id",
)
