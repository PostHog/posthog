from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS


def bot_user_agent_patterns(*, exclude_categories: frozenset[str] = frozenset()) -> list[str]:
    """Return the case-sensitive RE2 patterns that match the user agent of a known bot, in definition order."""
    return [pattern for pattern, bot in BOT_DEFINITIONS.items() if bot.category not in exclude_categories]
