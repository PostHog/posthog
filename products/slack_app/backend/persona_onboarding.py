"""Persona onboarding for the Slack AI co-worker DM surface.

A deterministic Block Kit conversation: detect (or ask) the user's role, and for CSMs
provision a fleet of customer-success scouts with a Slack delivery channel. Detection is a
ladder — recent workspace messages (Real-time Search API, when available) → Slack profile
title → just ask — and only ever pre-fills the question; the user always confirms with a
button. Message builders and handlers live here; ``api.py`` and ``slack_app_home.py`` carry
only thin wiring.
"""

from __future__ import annotations

import dataclasses

import structlog

from posthog.models.integration import SlackIntegration

from products.slack_app.backend.onboarding import _public_url
from products.slack_app.backend.services import slack_search

logger = structlog.get_logger(__name__)

# Block Kit action ids. Everything in this flow shares the prefix so the interactivity
# dispatcher and region-locality arms can route on it without per-step registration.
ACTION_PREFIX = "persona_onboarding_"
START_ACTION_ID = "persona_onboarding_start"
PERSONA_SELECT_ACTION_ID = "persona_onboarding_select"  # values: "csm" | "engineer" | "other"
SKIP_ACTION_ID = "persona_onboarding_skip"
CHANNEL_SELECT_ACTION_ID = "persona_onboarding_channel_select"
CHANNEL_CREATE_ACTION_ID = "persona_onboarding_channel_create"
CHANNEL_VERIFY_ACTION_ID = "persona_onboarding_channel_verify"
# URL buttons — clicks open the browser but still emit a block_action that must be acked.
CONNECT_SOURCE_ACTION_ID = "persona_onboarding_connect_source"

SCOUTS_DOC_URL = "https://posthog.com/docs/self-driving/scouts"

EVENT_STARTED = "slack_persona_onboarding_started"
EVENT_PERSONA_SELECTED = "slack_persona_onboarding_persona_selected"
EVENT_FLEET_SHOWN = "slack_persona_onboarding_fleet_shown"
EVENT_CONNECT_CLICKED = "slack_persona_onboarding_connect_clicked"
EVENT_CHANNEL_CONFIGURED = "slack_persona_onboarding_channel_configured"
EVENT_COMPLETED = "slack_persona_onboarding_completed"
EVENT_SKIPPED = "slack_persona_onboarding_skipped"
EVENT_GRANDFATHERED = "slack_persona_onboarding_grandfathered"

# ============================================================================
# Persona detection ladder: workspace messages → profile title → (caller asks)
# ============================================================================

_CSM_TITLE_KEYWORDS = (
    "customer success",
    "csm",
    "account manager",
    "account management",
    "customer experience",
    "relationship manager",
    "customer onboarding",
    "implementation manager",
    "cs ops",
)
_ENGINEER_TITLE_KEYWORDS = (
    "engineer",
    "developer",
    "swe",
    "sre",
    "devops",
    "software",
    "tech lead",
    "cto",
    "programmer",
    "platform",
    "infrastructure",
)

# One search per bucket keeps the whole flow (2 persona + 4 tool queries) inside Slack's
# ~10 req/min search budget.
_CSM_MESSAGE_QUERY = "renewal QBR churn risk customer health score"
_ENGINEER_MESSAGE_QUERY = "pull request deploy stack trace code review"
# A bucket wins outright only with a clear margin; anything murkier falls to the next rung.
_MESSAGE_SCORE_MIN = 3
_MESSAGE_SCORE_RATIO = 2

DETECTION_SOURCE_MESSAGES = "messages"
DETECTION_SOURCE_TITLE = "title"


def _authored_count(messages: list[dict], slack_user_id: str) -> int:
    # `from:`-style modifiers aren't documented for assistant.search.context, so authorship is
    # filtered client-side — only this user's own messages say anything about their role.
    return sum(1 for message in messages if message.get("user") == slack_user_id)


def _detect_persona_from_messages(slack: SlackIntegration, workspace_id: str, slack_user_id: str) -> str | None:
    action_token = slack_search.get_cached_action_token(workspace_id, slack_user_id)
    if action_token is None:
        return None
    csm_score = _authored_count(
        slack_search.search_messages(slack, action_token=action_token, query=_CSM_MESSAGE_QUERY),
        slack_user_id,
    )
    engineer_score = _authored_count(
        slack_search.search_messages(slack, action_token=action_token, query=_ENGINEER_MESSAGE_QUERY),
        slack_user_id,
    )
    if csm_score >= _MESSAGE_SCORE_MIN and csm_score >= _MESSAGE_SCORE_RATIO * engineer_score:
        return "csm"
    if engineer_score >= _MESSAGE_SCORE_MIN and engineer_score >= _MESSAGE_SCORE_RATIO * csm_score:
        return "engineer"
    return None


def _detect_persona_from_title(slack: SlackIntegration, slack_user_id: str) -> str | None:
    try:
        info = slack.client.users_info(user=slack_user_id)
        title = str(((info.get("user") or {}).get("profile") or {}).get("title") or "").lower()
    except Exception:
        logger.warning("persona_onboarding_title_fetch_failed", exc_info=True)
        return None
    if not title:
        return None
    if any(keyword in title for keyword in _CSM_TITLE_KEYWORDS):
        return "csm"
    if any(keyword in title for keyword in _ENGINEER_TITLE_KEYWORDS):
        return "engineer"
    return None


def detect_persona(slack: SlackIntegration, workspace_id: str, slack_user_id: str) -> tuple[str | None, str | None]:
    """Returns ``(candidate, source)`` — candidate in {"csm", "engineer", None}, source in
    {"messages", "title", None}. Best-effort at every rung; never raises."""
    if slack_search.search_available(slack, workspace_id, slack_user_id):
        candidate = _detect_persona_from_messages(slack, workspace_id, slack_user_id)
        if candidate is not None:
            return candidate, DETECTION_SOURCE_MESSAGES
    candidate = _detect_persona_from_title(slack, slack_user_id)
    if candidate is not None:
        return candidate, DETECTION_SOURCE_TITLE
    return None, None


# ============================================================================
# Workspace tool detection (feeds the fleet reveal's "connect X" offers)
# ============================================================================


@dataclasses.dataclass(frozen=True)
class ConnectableTool:
    term: str  # what to search workspace messages for
    source_kind: str  # ExternalDataSourceType value, doubles as the ?kind= preselect
    label: str  # human-facing name


# Kinds must be exact ExternalDataSourceType values (products/warehouse_sources/backend/types.py)
# so the connect deep link preselects the right connector. Four terms keeps the search budget.
_CONNECTABLE_TOOLS: tuple[ConnectableTool, ...] = (
    ConnectableTool(term="linear.app", source_kind="Linear", label="Linear"),
    ConnectableTool(term="zendesk", source_kind="Zendesk", label="Zendesk"),
    ConnectableTool(term="intercom", source_kind="Intercom", label="Intercom"),
    ConnectableTool(term="atlassian.net", source_kind="Jira", label="Jira"),
)
_TOOL_HIT_MIN = 3


def detect_workspace_tools(slack: SlackIntegration, workspace_id: str, slack_user_id: str) -> list[str]:
    """Source kinds (ExternalDataSourceType values) whose tool shows up in recent public-channel
    messages. Empty when search is unavailable — the fleet reveal then renders generic gap lines."""
    if not slack_search.search_available(slack, workspace_id, slack_user_id):
        return []
    action_token = slack_search.get_cached_action_token(workspace_id, slack_user_id)
    if action_token is None:
        return []
    detected: list[str] = []
    for tool in _CONNECTABLE_TOOLS:
        hits = slack_search.search_messages(slack, action_token=action_token, query=tool.term)
        if len(hits) >= _TOOL_HIT_MIN:
            detected.append(tool.source_kind)
    return detected


def connectable_tool_for_kind(source_kind: str) -> ConnectableTool | None:
    return next((tool for tool in _CONNECTABLE_TOOLS if tool.source_kind == source_kind), None)


# ============================================================================
# Deep links into the PostHog app
# ============================================================================


def source_connect_url(team_id: int, source_kind: str) -> str:
    return _public_url(f"/project/{team_id}/data-warehouse/new-source?kind={source_kind}")


def sources_catalog_url(team_id: int) -> str:
    return _public_url(f"/project/{team_id}/data-management/sources")


def inbox_url(team_id: int) -> str:
    return _public_url(f"/project/{team_id}/inbox")
