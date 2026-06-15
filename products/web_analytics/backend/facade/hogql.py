"""Shared HogQL tables of the web_analytics facade.

Core's HogQL layer reaches into web_analytics for bot-traffic definitions (the
`traffic_type` function) and the pre-aggregated property maps (the
preaggregated-table transform). These are plain data, so re-export them here
rather than from `queries` — that keeps the heavy runner imports off the path
of consumers that only need the tables.
"""

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS
from products.web_analytics.backend.hogql_queries.bot_ua_fixtures import BOT_USER_AGENTS, CATEGORY_TO_TRAFFIC_CATEGORY
from products.web_analytics.backend.hogql_queries.pre_aggregated.properties import (
    EVENT_PROPERTY_TO_FIELD,
    SESSION_PROPERTY_TO_FIELD,
)

__all__ = [
    "BOT_DEFINITIONS",
    "BOT_USER_AGENTS",
    "CATEGORY_TO_TRAFFIC_CATEGORY",
    "EVENT_PROPERTY_TO_FIELD",
    "SESSION_PROPERTY_TO_FIELD",
]
