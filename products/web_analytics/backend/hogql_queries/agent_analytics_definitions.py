from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from products.web_analytics.backend.hogql_queries.web_bots import BOT_ANALYTICS_EVENTS

AGENT_HTTP_EVENT = "$http_log"
AGENT_NAVIGATION_EVENTS = ("$pageview", "$screen")
AGENT_EVENTS = BOT_ANALYTICS_EVENTS

AGENT_CATEGORIES = ("ai_assistant", "ai_search")
AGENT_CATEGORIES_WITH_CRAWLERS = (*AGENT_CATEGORIES, "ai_crawler")

NAVIGATION_WINDOW_SECONDS = 30 * 60
INACTIVITY_WINDOW_SECONDS = 30 * 60
CONVERSION_WINDOW_SECONDS = 24 * 60 * 60
DEFAULT_RESULT_LIMIT = 100
MAX_JOURNEY_STEPS = 200


def static_asset_expr() -> ast.Expr:
    return parse_expr(
        r"""
match(properties.$pathname, '(?i)(\\.(ico|png|jpe?g|gif|svg|webp|css|js|map)$|\\.woff|/apple-touch-icon)')
    OR properties.$pathname IN ('/robots.txt', '/sitemap.xml')
"""
    )


def malformed_path_expr() -> ast.Expr:
    return parse_expr(
        """
properties.$pathname ILIKE '%/null/%'
    OR properties.$pathname ILIKE '%/undefined/%'
    OR endsWith(properties.$pathname, '/null')
    OR endsWith(properties.$pathname, '/undefined')
"""
    )


def normalized_path_expr() -> ast.Expr:
    return parse_expr(
        r"""
replaceRegexpAll(
    replaceRegexpAll(
        replaceRegexpAll(properties.$pathname, '\\.(md|html?|json|txt|xml|ya?ml)$', ''),
        '[-/]v?[0-9]+\\.[0-9]+(\\.[0-9]+)?',
        ''
    ),
    '/+$',
    ''
)
"""
    )


def markdown_path_expr() -> ast.Expr:
    return parse_expr("properties.$pathname ILIKE '%.md'")


def page_identity_expr() -> ast.Expr:
    return parse_expr(
        r"concat(coalesce(properties.$host, ''), replaceRegexpAll(properties.$pathname, '(?i)\\.md$', ''))"
    )


def referrer_expr() -> ast.Expr:
    return parse_expr(
        "coalesce(nullIf(toString(properties.$referrer), ''), nullIf(toString(properties.proxy_referer), ''), '')"
    )


def response_status_code_expr() -> ast.Expr:
    return parse_expr("toInt(coalesce(nullIf(toString(properties.proxy_status_code), ''), '0'))")


def content_gap_expr() -> ast.Expr:
    return parse_expr(
        "{status} = 404 AND NOT ({malformed})",
        placeholders={"status": response_status_code_expr(), "malformed": malformed_path_expr()},
    )
