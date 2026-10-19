from products.web_analytics.backend.models import WebAnalyticsAchievementProgress


def clear_achievement_filter_retry(team_id: int) -> None:
    WebAnalyticsAchievementProgress.clear_filter_retry(team_id)
