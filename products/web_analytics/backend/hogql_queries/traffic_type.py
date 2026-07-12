"""
Traffic type classification helper functions for web analytics.

These wrap the HogQL classification functions, usable anywhere HogQL runs:
- SQL editor: ad-hoc analysis (e.g. SELECT isLikelyBot(properties.$raw_user_agent))
- HogQLQuery / Trends: filter or group by traffic type
- Web analytics query runners

Each helper takes the user agent expression and an optional client IP expression; the IP
signal catches crawlers that send real browser user agents from operator-published IP
ranges (e.g. Google's mobile rendering service).

The legacy __preview_* names still resolve as deprecated aliases.
"""

from posthog.hogql import ast
from posthog.hogql.functions.traffic_type import (
    get_bot_name as _get_bot_name,
    get_bot_type as _get_bot_type,
    get_traffic_category as _get_traffic_category,
    get_traffic_type as _get_traffic_type,
    is_bot as _is_bot,
)

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS

__all__ = [
    "BOT_DEFINITIONS",
    "get_traffic_type_expr",
    "get_traffic_category_expr",
    "is_bot_expr",
    "get_bot_type_expr",
    "get_bot_name_expr",
]


def _args(user_agent_expr: ast.Expr, ip_expr: ast.Expr | None) -> list[ast.Expr]:
    return [user_agent_expr] if ip_expr is None else [user_agent_expr, ip_expr]


def get_traffic_type_expr(user_agent_expr: ast.Expr, ip_expr: ast.Expr | None = None) -> ast.Expr:
    """
    Classifies user agent (and optionally client IP) into traffic type.

    Returns an expression that evaluates to one of:
    - "AI Agent" - AI crawlers, search, and assistants (GPTBot, ClaudeBot, ChatGPT-User, etc.)
    - "Bot" - Search engines, SEO tools, social crawlers, monitoring
    - "Automation" - HTTP clients, headless browsers, empty UA
    - "Regular" - Default for unmatched user agents
    """
    return _get_traffic_type(node=ast.Call(name="getTrafficType", args=[]), args=_args(user_agent_expr, ip_expr))


def get_traffic_category_expr(user_agent_expr: ast.Expr, ip_expr: ast.Expr | None = None) -> ast.Expr:
    """
    Returns subcategory expression for more granular classification.

    Categories: ai_crawler, ai_search, ai_assistant, search_crawler, seo_crawler,
    social_crawler, monitoring, http_client, headless_browser, no_user_agent, regular
    """
    return _get_traffic_category(
        node=ast.Call(name="getTrafficCategory", args=[]), args=_args(user_agent_expr, ip_expr)
    )


def is_bot_expr(user_agent_expr: ast.Expr, ip_expr: ast.Expr | None = None) -> ast.Expr:
    """
    Returns a boolean expression: true if bot/automation, false for regular traffic.
    """
    return _is_bot(node=ast.Call(name="isLikelyBot", args=[]), args=_args(user_agent_expr, ip_expr))


def get_bot_type_expr(user_agent_expr: ast.Expr, ip_expr: ast.Expr | None = None) -> ast.Expr:
    """
    Returns the bot category or empty string for regular traffic.

    Categories: ai_crawler, ai_search, ai_assistant, search_crawler, seo_crawler,
    social_crawler, monitoring, http_client, headless_browser, no_user_agent, "" (regular)
    """
    return _get_bot_type(node=ast.Call(name="getBotType", args=[]), args=_args(user_agent_expr, ip_expr))


def get_bot_name_expr(user_agent_expr: ast.Expr, ip_expr: ast.Expr | None = None) -> ast.Expr:
    """
    Returns the bot name or empty string for regular traffic.

    Examples: "Googlebot", "ChatGPT", "Claude", "curl", ""
    """
    return _get_bot_name(node=ast.Call(name="getBotName", args=[]), args=_args(user_agent_expr, ip_expr))
