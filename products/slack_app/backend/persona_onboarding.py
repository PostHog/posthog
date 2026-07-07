"""Persona onboarding for the Slack AI co-worker DM surface.

A deterministic Block Kit conversation: detect (or ask) the user's role, and for CSMs
provision a fleet of customer-success scouts with a Slack delivery channel. Detection is a
ladder — recent workspace messages (Real-time Search API, when available) → Slack profile
title → just ask — and only ever pre-fills the question; the user always confirms with a
button. Message builders and handlers live here; ``api.py`` and ``slack_app_home.py`` carry
only thin wiring.
"""

from __future__ import annotations

import threading
import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from django.core import signing
from django.core.cache import cache
from django.db import close_old_connections
from django.http import HttpResponse
from django.utils import timezone

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration, SlackIntegration
from posthog.models.user import User

from products.mcp_store.backend.facade.api import get_active_installations, list_active_templates
from products.mcp_store.backend.facade.contracts import TemplateInfo

if TYPE_CHECKING:
    from slack_sdk.web import SlackResponse

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.feature_flags import is_persona_onboarding_enabled
from products.slack_app.backend.inbox_channel import (
    INBOX_CHANNEL_REQUIRED_SCOPES,
    ensure_inbox_channel,
    invite_user_to_inbox,
)
from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping
from products.slack_app.backend.onboarding import _github_connect_url, _public_url, is_github_connected
from products.slack_app.backend.services import slack_search
from products.slack_app.backend.services.integration_resolver import load_integrations, resolve_user_for_workspace

logger = structlog.get_logger(__name__)

# Block Kit action ids. Everything in this flow shares the prefix so the interactivity
# dispatcher and region-locality arms can route on it without per-step registration.
ACTION_PREFIX = "persona_onboarding_"
START_ACTION_ID = "persona_onboarding_start"
# URL button on the App Home card that deep-links into the onboarding DM; ack-only.
OPEN_DM_ACTION_ID = "persona_onboarding_open_dm"
PERSONA_SELECT_ACTION_ID = "persona_onboarding_select"  # values: "csm" | "engineer" | "other"
SKIP_ACTION_ID = "persona_onboarding_skip"
CHANNEL_SELECT_ACTION_ID = "persona_onboarding_channel_select"
CHANNEL_CONFIRM_ACTION_ID = "persona_onboarding_channel_confirm"
CHANNEL_CREATE_ACTION_ID = "persona_onboarding_channel_create"
CHANNEL_VERIFY_ACTION_ID = "persona_onboarding_channel_verify"
# The confirm button reads the dropdown's current selection out of payload["state"]["values"],
# which Slack keys by block_id — so the selector's block needs a stable one.
CHANNEL_SELECT_BLOCK_ID = "persona_onboarding_channel_block"
# URL buttons — clicks open the browser but still emit a block_action that must be acked.
CONNECT_SOURCE_ACTION_ID = "persona_onboarding_connect_source"

SCOUTS_DOC_URL = "https://posthog.com/docs/self-driving/scouts"

# Single-flight window for the kickoff post (see `start_onboarding_dm`).
_START_CLAIM_TTL_SECONDS = 60

EVENT_STARTED = "slack_persona_onboarding_started"
EVENT_PERSONA_SELECTED = "slack_persona_onboarding_persona_selected"
EVENT_FLEET_SHOWN = "slack_persona_onboarding_fleet_shown"
EVENT_CONNECT_CLICKED = "slack_persona_onboarding_connect_clicked"
EVENT_MCP_CONNECTED = "slack_persona_onboarding_mcp_connected"
EVENT_GITHUB_CONNECTED = "slack_persona_onboarding_github_connected"
EVENT_CHANNEL_CONFIGURED = "slack_persona_onboarding_channel_configured"
EVENT_COMPLETED = "slack_persona_onboarding_completed"
EVENT_SKIPPED = "slack_persona_onboarding_skipped"
EVENT_GRANDFATHERED = "slack_persona_onboarding_grandfathered"

# Signed state carried by Connect buttons through the MCP OAuth round-trip; long-lived because
# the fleet-reveal message can sit unread in a DM for a while before anyone clicks it.
_CONNECT_STATE_SALT = "slack_app.persona_onboarding.mcp_connect"
CONNECT_STATE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60


def sign_connect_state(workspace_id: str, slack_user_id: str, readiness_key: str, template_name: str) -> str:
    payload = {"w": workspace_id, "u": slack_user_id, "k": readiness_key, "t": template_name}
    return signing.dumps(payload, salt=_CONNECT_STATE_SALT)


def unsign_connect_state(state: str) -> dict:
    """Raises ``django.core.signing.BadSignature`` on tampered or expired state."""
    return signing.loads(state, salt=_CONNECT_STATE_SALT, max_age=CONNECT_STATE_MAX_AGE_SECONDS)


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
    server_name: str  # MCP store template name (also the human-facing label)


# Names must match MCP store template names (case-insensitive) so a detected tool can be
# paired with its Connect button. Four terms keeps the search budget.
_CONNECTABLE_TOOLS: tuple[ConnectableTool, ...] = (
    ConnectableTool(term="linear.app", server_name="Linear"),
    ConnectableTool(term="zendesk", server_name="Zendesk"),
    ConnectableTool(term="intercom", server_name="Intercom"),
    ConnectableTool(term="atlassian.net", server_name="Jira"),
)
_TOOL_HIT_MIN = 3


def detect_workspace_tools(slack: SlackIntegration, workspace_id: str, slack_user_id: str) -> list[str]:
    """MCP server names whose tool shows up in recent public-channel messages. Empty when
    search is unavailable — the fleet reveal then renders generic gap lines."""
    if not slack_search.search_available(slack, workspace_id, slack_user_id):
        return []
    action_token = slack_search.get_cached_action_token(workspace_id, slack_user_id)
    if action_token is None:
        return []
    detected: list[str] = []
    for tool in _CONNECTABLE_TOOLS:
        hits = slack_search.search_messages(slack, action_token=action_token, query=tool.term)
        if len(hits) >= _TOOL_HIT_MIN:
            detected.append(tool.server_name)
    return detected


# ============================================================================
# Deep links into the PostHog app
# ============================================================================


def mcp_connect_url(team_id: int, template_id: str, state: str) -> str:
    """Login-gated browser entry that starts the MCP OAuth connect and returns through Slack."""
    return _public_url(f"/integrations/connect-mcp/{template_id}/?{urlencode({'project_id': team_id, 'state': state})}")


def mcp_store_url(team_id: int, template_id: str | None = None) -> str:
    base = f"/project/{team_id}/settings/mcp-servers"
    return _public_url(f"{base}?{urlencode({'mcp': template_id})}" if template_id else base)


def inbox_url(team_id: int) -> str:
    return _public_url(f"/project/{team_id}/inbox")


def slack_dm_deep_link(workspace_id: str, dm_channel_id: str) -> str:
    """https deep link that opens the Slack client on the DM — works in Block Kit URL buttons
    on every client, unlike the slack:// protocol form."""
    return f"https://slack.com/app_redirect?{urlencode({'team': workspace_id, 'channel': dm_channel_id})}"


def onboarding_dm_deep_link(workspace_id: str, slack_user_id: str) -> str | None:
    """Deep link to the in-flight onboarding conversation, for the App Home card."""
    row = SlackSettings.objects.filter(slack_workspace_id=workspace_id, slack_user_id=slack_user_id).first()
    state = row.onboarding_state if row is not None and isinstance(row.onboarding_state, dict) else None
    dm_channel_id = str(state.get("dm_channel_id") or "") if state else ""
    return slack_dm_deep_link(workspace_id, dm_channel_id) if dm_channel_id else None


# ============================================================================
# Persona scout catalog + data readiness
# ============================================================================

PERSONA_CSM = "csm"
PERSONA_ENGINEER = "engineer"
PERSONA_OTHER = "other"

STEP_AWAITING_PERSONA = "awaiting_persona"
STEP_AWAITING_CHANNEL = "awaiting_channel"


@dataclasses.dataclass(frozen=True)
class ScoutSpec:
    skill_name: str
    title: str
    description: str
    readiness_key: str
    recommended_servers: tuple[str, ...]  # MCP store template names whose data would feed it
    gap_line: str  # "works best with …" copy when readiness is False


PERSONA_SCOUT_CATALOG: dict[str, tuple[ScoutSpec, ...]] = {
    PERSONA_CSM: (
        ScoutSpec(
            skill_name="signals-scout-slack-csm-account-pulse",
            title="Account pulse",
            description=(
                "Watches each account's product usage and flags the ones sliding toward churn or "
                "heating up toward expansion, tagging the account owner."
            ),
            readiness_key="account_pulse",
            recommended_servers=("Salesforce", "HubSpot"),
            gap_line="works best with account data like PostHog customer analytics accounts or a connected CRM.",
        ),
        ScoutSpec(
            skill_name="signals-scout-slack-csm-support-watch",
            title="Support watch",
            description=(
                "Watches support tickets for spikes, escalations, and accounts going loud (or silent) "
                "right before renewal."
            ),
            readiness_key="support_watch",
            recommended_servers=("Zendesk", "Intercom", "Linear", "Jira", "Freshdesk"),
            gap_line="works best with a ticketing tool.",
        ),
        ScoutSpec(
            skill_name="signals-scout-slack-csm-revenue-watch",
            title="Renewal & billing watch",
            description=(
                "Watches billing data for failed payments, cancellations, and contraction on the accounts you own."
            ),
            readiness_key="revenue_watch",
            recommended_servers=("Stripe",),
            gap_line="works best with billing data like Stripe or PostHog revenue analytics.",
        ),
    ),
}

_SUPPORT_SOURCE_KINDS = ("Zendesk", "Intercom", "Linear", "Jira", "Freshdesk")
_CRM_SOURCE_KINDS = ("Salesforce", "Hubspot")


@dataclasses.dataclass(frozen=True)
class CsmDataReadiness:
    account_pulse: bool
    support_watch: bool
    revenue_watch: bool
    accounts_count: int
    # readiness_key -> human phrase for the data source that made the scout ready (e.g. "your
    # PostHog customer analytics accounts"), so the reveal can say what's used by default.
    ready_details: dict[str, str] = dataclasses.field(default_factory=dict)

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def _active_source_kinds(team_id: int) -> set[str]:
    from products.warehouse_sources.backend.models.external_data_source import (  # noqa: PLC0415 — keeps the warehouse stack off the slack import path
        ExternalDataSource,
    )

    return set(
        ExternalDataSource.objects.filter(team_id=team_id).exclude(deleted=True).values_list("source_type", flat=True)
    )


def _connected_mcp_server_names(team_id: int, posthog_user_id: int | None) -> set[str]:
    """Lowercased names of the user's ready MCP store installations (template + display names)."""
    if not posthog_user_id:
        return set()
    names: set[str] = set()
    for installation in get_active_installations(team_id, posthog_user_id):
        for name in (installation.template_name, installation.name):
            if name:
                names.add(name.lower())
    return names


def _first_connected_recommended(spec: ScoutSpec, connected_names: set[str]) -> str | None:
    return next((name for name in spec.recommended_servers if name.lower() in connected_names), None)


def check_csm_data_readiness(team_id: int, posthog_user_id: int | None = None) -> CsmDataReadiness:
    """Per-scout data probes for the fleet reveal + completion copy. Presentation only —
    a probe failure renders as "no data yet", never blocks onboarding."""
    accounts_count = 0
    try:
        from products.customer_analytics.backend.facade.api import (  # noqa: PLC0415 — keeps the customer-analytics stack off the slack import path
            count_accounts,
        )

        accounts_count = count_accounts(team_id)
    except Exception:
        logger.warning("persona_onboarding_accounts_probe_failed", exc_info=True)

    tickets_exist = False
    try:
        from products.conversations.backend.models.ticket import (  # noqa: PLC0415 — keeps the conversations stack off the slack import path
            Ticket,
        )

        tickets_exist = Ticket.objects.filter(team_id=team_id).exists()
    except Exception:
        logger.warning("persona_onboarding_tickets_probe_failed", exc_info=True)

    source_kinds: set[str] = set()
    try:
        source_kinds = _active_source_kinds(team_id)
    except Exception:
        logger.warning("persona_onboarding_sources_probe_failed", exc_info=True)

    mcp_connected: set[str] = set()
    try:
        mcp_connected = _connected_mcp_server_names(team_id, posthog_user_id)
    except Exception:
        logger.warning("persona_onboarding_mcp_probe_failed", exc_info=True)

    specs_by_key = {spec.readiness_key: spec for spec in PERSONA_SCOUT_CATALOG[PERSONA_CSM]}

    def resolve(readiness_key: str, posthog_detail: str | None, source_matches: tuple[str, ...]) -> str | None:
        """First data source that makes the scout ready, as a human phrase — PostHog-native data
        wins so users see they don't need to connect anything."""
        if posthog_detail:
            return posthog_detail
        source_kind = next((kind for kind in source_matches if kind in source_kinds), None)
        if source_kind:
            return f"your {source_kind} data synced into PostHog"
        server_name = _first_connected_recommended(specs_by_key[readiness_key], mcp_connected)
        if server_name:
            return f"your connected {server_name} MCP server"
        return None

    details = {
        "account_pulse": resolve(
            "account_pulse",
            "your PostHog customer analytics accounts" if accounts_count > 0 else None,
            _CRM_SOURCE_KINDS,
        ),
        "support_watch": resolve(
            "support_watch",
            "your PostHog conversations tickets" if tickets_exist else None,
            _SUPPORT_SOURCE_KINDS,
        ),
        "revenue_watch": resolve("revenue_watch", None, ("Stripe",)),
    }
    return CsmDataReadiness(
        account_pulse=details["account_pulse"] is not None,
        support_watch=details["support_watch"] is not None,
        revenue_watch=details["revenue_watch"] is not None,
        accounts_count=accounts_count,
        ready_details={key: detail for key, detail in details.items() if detail},
    )


def check_engineer_github_connected(team_id: int, posthog_user_id: int | None) -> bool:
    """Presentation-only probe for the engineer completion (mirrors the setup DM's GitHub step) —
    a failure renders the connect offer, never blocks onboarding."""
    try:
        return is_github_connected(team_id, posthog_user_id)
    except Exception:
        logger.warning("persona_onboarding_github_probe_failed", exc_info=True)
        return False


# ============================================================================
# Settings-row state helpers
# ============================================================================


def get_or_create_settings_row(workspace_id: str, slack_user_id: str) -> SlackSettings:
    row, _ = SlackSettings.objects.get_or_create(slack_workspace_id=workspace_id, slack_user_id=slack_user_id)
    return row


def is_onboarded(row: SlackSettings | None) -> bool:
    return row is not None and row.onboarded_at is not None


def has_prior_slack_activity(integration_ids: list[int], slack_user_id: str) -> bool:
    if not integration_ids:
        return False
    return SlackThreadTaskMapping.objects.filter(
        integration_id__in=integration_ids, latest_actor_slack_user_id=slack_user_id
    ).exists()


def _grandfather(integration: Integration, row: SlackSettings, slack_user_id: str) -> None:
    row.onboarded_at = timezone.now()
    row.onboarding_state = None
    row.save(update_fields=["onboarded_at", "onboarding_state", "updated_at"])
    capture_slack_event(integration, EVENT_GRANDFATHERED, slack_user_id=slack_user_id)


def compute_home_onboarding_status(integration: Integration, workspace_id: str, slack_user_id: str) -> str:
    """ "hidden" | "start" | "in_progress" — drives the App Home onboarding card."""
    if not is_persona_onboarding_enabled(integration.team):
        return "hidden"
    row = SlackSettings.objects.filter(slack_workspace_id=workspace_id, slack_user_id=slack_user_id).first()
    if is_onboarded(row):
        return "hidden"
    if row is not None and isinstance(row.onboarding_state, dict):
        return "in_progress"
    return "start"


# ============================================================================
# Block builders
# ============================================================================


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _button(label: str, action_id: str, value: str = "", *, style: str | None = None, url: str | None = None) -> dict:
    # Slack rejects a message whose interactive elements share an action_id, so a button's value
    # doubles as an id suffix; `handle_block_action` dispatches on the base id before the ":".
    button: dict = {
        "type": "button",
        "text": {"type": "plain_text", "text": label},
        "action_id": f"{action_id}:{value}" if value else action_id,
    }
    if value:
        button["value"] = value
    if style:
        button["style"] = style
    if url:
        button["url"] = url
    return button


def build_kickoff_blocks(display_name: str, candidate: str | None) -> list[dict]:
    hey = f"🦔 Hey {display_name}! I'm PostHog's Slack agent. I can dig into data, ship code, and help get things done."
    skip = _button("Skip setup", SKIP_ACTION_ID)
    if candidate == PERSONA_CSM:
        intro = f"{hey} Before we get going, let me set things up right for you.\n\nIt looks like you're a CSM — is that right?"
        buttons = [
            _button("Yes — set me up as a CSM", PERSONA_SELECT_ACTION_ID, PERSONA_CSM, style="primary"),
            _button("I'm an engineer", PERSONA_SELECT_ACTION_ID, PERSONA_ENGINEER),
            _button("Something else", PERSONA_SELECT_ACTION_ID, PERSONA_OTHER),
            skip,
        ]
    elif candidate == PERSONA_ENGINEER:
        intro = (
            f"{hey} Before we get going, let me set things up right for you.\n\nLooks like you're an engineer — right?"
        )
        buttons = [
            _button("Yep, engineer", PERSONA_SELECT_ACTION_ID, PERSONA_ENGINEER, style="primary"),
            _button("I'm in customer success", PERSONA_SELECT_ACTION_ID, PERSONA_CSM),
            _button("Something else", PERSONA_SELECT_ACTION_ID, PERSONA_OTHER),
            skip,
        ]
    else:
        intro = f"{hey}\n\nQuick question so I can set things up right for you — which best describes what you do?"
        buttons = [
            _button("Engineer", PERSONA_SELECT_ACTION_ID, PERSONA_ENGINEER),
            _button("Customer success (CSM)", PERSONA_SELECT_ACTION_ID, PERSONA_CSM),
            _button("Something else", PERSONA_SELECT_ACTION_ID, PERSONA_OTHER),
            skip,
        ]
    return [_section(intro), {"type": "actions", "elements": buttons}]


_MAX_CONNECT_BUTTONS_PER_SCOUT = 3


def _connect_button(
    team_id: int, spec: ScoutSpec, template: TemplateInfo, workspace_id: str, slack_user_id: str
) -> dict:
    # OAuth templates connect straight from the browser and return through Slack; API-key
    # templates need the store UI, so their button deep-links to the detail panel instead.
    if template.connect_via_redirect:
        state = sign_connect_state(workspace_id, slack_user_id, spec.readiness_key, template.name)
        url = mcp_connect_url(team_id, template.id, state)
    else:
        url = mcp_store_url(team_id, template.id)
    # Button values are "<readiness_key>:<server|store>": sibling connect buttons must not
    # collide on value (it doubles as the action_id suffix), and telemetry gets the scout.
    return _button(
        f"Connect {template.name}", CONNECT_SOURCE_ACTION_ID, f"{spec.readiness_key}:{template.name}", url=url
    )


def build_fleet_reveal_blocks(
    team_id: int,
    readiness: dict,
    detected_tools: list[str],
    templates: list[TemplateInfo],
    workspace_id: str,
    slack_user_id: str,
) -> list[dict]:
    templates_by_name = {template.name.lower(): template for template in templates}
    ready_details = readiness.get("ready_details") or {}
    blocks: list[dict] = [
        _section(
            "Great, I'm going to create a few scouts for you. Scouts are little agents that patrol "
            "your data on a schedule and ping you whenever there's something to worry about "
            f"(<{SCOUTS_DOC_URL}|here's how they work>)."
        )
    ]
    if any(not readiness.get(spec.readiness_key) for spec in PERSONA_SCOUT_CATALOG[PERSONA_CSM]):
        blocks.append(
            _context(
                "Scouts use your PostHog data by default. Connecting a tool below is optional; "
                "it just gives them more signal."
            )
        )
    for index, spec in enumerate(PERSONA_SCOUT_CATALOG[PERSONA_CSM], start=1):
        blocks.append(_section(f"*{index}. {spec.title}*\n{spec.description}"))
        if readiness.get(spec.readiness_key):
            detail = ready_details.get(spec.readiness_key)
            blocks.append(
                _context(f"✅ Ready — I'll use {detail}." if detail else "✅ Ready — I can see the data this needs.")
            )
            continue
        candidates = [
            templates_by_name[name.lower()] for name in spec.recommended_servers if name.lower() in templates_by_name
        ]
        detected = next(
            (template for name in detected_tools for template in candidates if template.name.lower() == name.lower()),
            None,
        )
        if detected is not None:
            candidates = [detected, *[template for template in candidates if template is not detected]]
            blocks.append(
                _section(f"⚠️ {spec.title} {spec.gap_line} I see you're using {detected.name} — want to connect it now?")
            )
        else:
            blocks.append(_context(f"⚠️ {spec.gap_line} Connect one any time — this scout picks it up automatically."))
        if candidates:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        _connect_button(team_id, spec, template, workspace_id, slack_user_id)
                        for template in candidates[:_MAX_CONNECT_BUTTONS_PER_SCOUT]
                    ],
                }
            )
        else:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        _button(
                            "Browse the MCP store",
                            CONNECT_SOURCE_ACTION_ID,
                            f"{spec.readiness_key}:store",
                            url=mcp_store_url(team_id),
                        )
                    ],
                }
            )
    return blocks


def build_channel_prompt_blocks(can_create_channel: bool) -> list[dict]:
    # Picking from the dropdown is easy to fat-finger, so it does nothing on its own —
    # the explicit Add PostHog button next to it is what commits the choice.
    select_row: list[dict] = [
        {
            "type": "conversations_select",
            "action_id": CHANNEL_SELECT_ACTION_ID,
            "placeholder": {"type": "plain_text", "text": "Pick a channel"},
            # Never offer external-shared channels — these alerts carry account intel.
            "filter": {"include": ["public"], "exclude_external_shared_channels": True, "exclude_bot_users": True},
        },
        _button("Add PostHog", CHANNEL_CONFIRM_ACTION_ID, style="primary"),
    ]
    secondary_row: list[dict] = []
    if can_create_channel:
        secondary_row.append(_button("Create #posthog-inbox", CHANNEL_CREATE_ACTION_ID))
    # Skip is a bail-out at every step: without it a CSM who can't (or won't) pick a channel
    # is wedged, since the DM intercept hijacks every message while onboarding_state is set.
    secondary_row.append(_button("Skip for now", SKIP_ACTION_ID))
    return [
        _section(
            "One more thing: this works best if you add me to a channel where I can post findings. "
            "Pick one and tap Add PostHog, or I can create #posthog-inbox for you."
            if can_create_channel
            else "One more thing: this works best if you add me to a channel where I can post findings. "
            "Pick one below and tap Add PostHog."
        ),
        {"type": "actions", "block_id": CHANNEL_SELECT_BLOCK_ID, "elements": select_row},
        {"type": "actions", "elements": secondary_row},
    ]


def build_invite_needed_blocks(channel_id: str, channel_name: str) -> list[dict]:
    return [
        _section(
            f"I can't post in #{channel_name} yet — I'm not a member. Type `/invite @PostHog` there "
            "(or mention @PostHog in the channel and Slack will offer to add me), then tap Verify. "
            "Or pick a different channel above."
        ),
        {
            "type": "actions",
            "elements": [
                _button("Verify", CHANNEL_VERIFY_ACTION_ID, channel_id, style="primary"),
                _button("Skip for now", SKIP_ACTION_ID),
            ],
        },
    ]


def build_locked_in_blocks(
    team_name: str, channel_name: str, readiness: dict, channel_conflict: str | None, team_id: int
) -> list[dict]:
    # Name the project: a Slack workspace can map to several PostHog projects and the fleet lands
    # in the one that resolved for this user, so say which so a multi-project CSM isn't guessing.
    if channel_conflict:
        first = (
            f"Your scouts are already running for *{team_name}* and posting to #{channel_conflict} — "
            "I've left that as-is. You're onboarded! 🎉"
        )
    else:
        first = (
            f"🎉 You're locked in for *{team_name}*. I've already sent your scouts on their first "
            f"patrol — I'll message you when a scout finds something, and findings land in "
            f"#{channel_name} with the account owner tagged when I can find them."
        )
    blocks = [_section(first)]
    gap_titles = [spec.title for spec in PERSONA_SCOUT_CATALOG[PERSONA_CSM] if not readiness.get(spec.readiness_key)]
    if gap_titles:
        names = ", ".join(gap_titles)
        verb = "is" if len(gap_titles) == 1 else "are"
        blocks.append(
            _context(
                f"Heads-up: {names} {verb} waiting on data — connect a source from the list above and "
                "they wake up on their own."
            )
        )
    blocks.append(
        _section(
            f"Manage your scouts (pause, cadence, run history) any time from your <{inbox_url(team_id)}|PostHog inbox>, or ask me to do it for you."
            "\n\nIn the meantime, do you want to work on anything? You can ask me things like:\n\n"
            "• _Which of my accounts had the biggest usage drop this month?_\n"
            "• _Summarize what Acme did last week._"
        )
    )
    return blocks


FLEET_REVEAL_TEXT = "I'm going to create a few scouts for you."
ENGINEER_COMPLETION_TEXT = "Got it, engineer it is."
ENGINEER_GITHUB_CONNECTED_TEXT = (
    f"{ENGINEER_COMPLETION_TEXT}\n\nGitHub is already connected, so I can start shipping code when you're ready."
)
ENGINEER_GITHUB_NEEDED_TEXT = f"{ENGINEER_COMPLETION_TEXT}\n\nOne thing first: connect your GitHub so I can open PRs and help you ship code.\n\nMention `@PostHog` in a channel or message me here to hand me a task."
GITHUB_CONNECTED_NOTE = "✅ GitHub connected."
GITHUB_CONNECTED_FOLLOWUP_TEXT = (
    "🎉 GitHub is connected, you're all set! Mention `@PostHog` in a channel or message me here to hand me a task."
)


def build_engineer_completion_blocks(team_id: int, github_connected: bool) -> list[dict]:
    if github_connected:
        return [_section(ENGINEER_GITHUB_CONNECTED_TEXT)]
    # Same OAuth entry as the setup DM's Connect GitHub button — one flow connects the team
    # install and the user's personal GitHub, then returns to Slack.
    return [
        _section(ENGINEER_GITHUB_NEEDED_TEXT),
        {
            "type": "actions",
            "elements": [
                _button(
                    "Connect GitHub",
                    CONNECT_SOURCE_ACTION_ID,
                    "github",
                    style="primary",
                    url=_github_connect_url(team_id),
                )
            ],
        },
    ]


OTHER_COMPLETION_TEXT = (
    "Thanks! Message me here any time — ask about your product data, dashboards, or anything PostHog."
)
SKIP_TEXT = "No problem — skipping setup. Message me whenever; settings live in my Home tab."
PICK_CHANNEL_FIRST_TEXT = "Pick a channel from the dropdown first, then tap Add PostHog."
NUDGE_PERSONA_TEXT = "One quick thing first — tap one of the buttons above (or Skip) and then I'm all yours."
NUDGE_CHANNEL_TEXT = (
    "Almost there — pick a channel for account alerts above (or Skip), then send me that message again."
)
ERROR_TEXT = "Something went wrong on my end — tap the button again, or skip setup and message me anytime."


# ============================================================================
# Flow entry points (called from api.py) + interactivity handlers
# ============================================================================


@dataclasses.dataclass
class _FlowContext:
    integration: Integration
    slack: SlackIntegration
    row: SlackSettings
    workspace_id: str
    slack_user_id: str
    state: dict


def _load_context(payload: dict) -> _FlowContext | None:
    workspace_id = str((payload.get("team") or {}).get("id") or "")
    slack_user_id = str((payload.get("user") or {}).get("id") or "")
    if not workspace_id or not slack_user_id:
        return None
    row = SlackSettings.objects.filter(slack_workspace_id=workspace_id, slack_user_id=slack_user_id).first()
    if row is None or not isinstance(row.onboarding_state, dict):
        return None
    state = row.onboarding_state
    integration = Integration.objects.filter(id=state.get("integration_id"), kind="slack").first()
    # Defensive: the stored integration must still belong to the clicking workspace.
    if integration is None or integration.integration_id != workspace_id:
        return None
    ctx = _FlowContext(integration, SlackIntegration(integration), row, workspace_id, slack_user_id, state)
    _retarget_to_click(ctx, payload)
    return ctx


def _retarget_to_click(ctx: _FlowContext, payload: dict) -> None:
    """Point follow-up posts at the thread hosting the clicked button. In the assistant surface
    every top-level DM message roots its own conversation, so replying anywhere else opens a
    brand-new History entry instead of continuing inline."""
    channel_id = (payload.get("channel") or {}).get("id")
    message = payload.get("message") or {}
    anchor = message.get("thread_ts") or message.get("ts")
    if not channel_id or not anchor:
        return
    if channel_id != ctx.state.get("dm_channel_id") or anchor != ctx.state.get("thread_ts"):
        ctx.state["dm_channel_id"] = channel_id
        ctx.state["thread_ts"] = anchor
        _save_state(ctx.row, ctx.state)


def _display_name(slack: SlackIntegration, slack_user_id: str) -> str:
    try:
        info = slack.client.users_info(user=slack_user_id)
        profile = (info.get("user") or {}).get("profile") or {}
        name = profile.get("display_name") or profile.get("real_name") or ""
        return name.split()[0] if name else "there"
    except Exception:
        return "there"


def _post(ctx: _FlowContext, blocks: list[dict], text: str) -> SlackResponse:
    return ctx.slack.client.chat_postMessage(
        channel=ctx.state.get("dm_channel_id"),
        thread_ts=ctx.state.get("thread_ts"),
        text=text,
        blocks=blocks,
    )


def _save_state(row: SlackSettings, state: dict | None) -> None:
    row.onboarding_state = state
    row.save(update_fields=["onboarding_state", "updated_at"])


def _remember_message_ts(ctx: _FlowContext, key: str, posted: SlackResponse) -> None:
    """Track a posted message so a later step can rewrite it in place (e.g. flip the channel
    prompt to a done note once the channel is configured)."""
    ts = posted.get("ts")
    if ts:
        ctx.state[key] = ts
        _save_state(ctx.row, ctx.state)


def _freeze_buttons(ctx: _FlowContext, payload: dict, note: str) -> None:
    """Replace the clicked message's action blocks with a note, so stale buttons can't
    double-fire. Best-effort — a failure here never blocks the step itself."""
    channel_id = (payload.get("channel") or {}).get("id")
    message = payload.get("message") or {}
    ts = message.get("ts")
    if not channel_id or not ts:
        return
    blocks = [block for block in (message.get("blocks") or []) if block.get("type") != "actions"]
    blocks.append(_context(note))
    try:
        ctx.slack.client.chat_update(channel=channel_id, ts=ts, text=note, blocks=blocks)
    except Exception:
        logger.warning("persona_onboarding_freeze_buttons_failed", exc_info=True)


def _republish_home(integration: Integration, slack_user_id: str) -> None:
    # Deferred: slack_app_home imports this module for the onboarding card, so a module-level
    # import here would be a true circular import.
    from products.slack_app.backend.services.slack_app_home import republish_home_for_user  # noqa: PLC0415

    try:
        republish_home_for_user(integration, slack_user_id)
    except Exception:
        logger.warning("persona_onboarding_home_republish_failed", exc_info=True)


def _publish_starting_home(integration: Integration, slack_user_id: str) -> None:
    # Deferred: slack_app_home imports this module for the onboarding card, so a module-level
    # import here would be a true circular import.
    from products.slack_app.backend.services.slack_app_home import publish_onboarding_starting_home  # noqa: PLC0415

    # Swallow like _republish_home: feedback is best-effort, the kickoff must still run.
    try:
        publish_onboarding_starting_home(integration, slack_user_id)
    except Exception:
        logger.warning("persona_onboarding_home_republish_failed", exc_info=True)


def start_onboarding_dm(
    integration: Integration,
    slack_user_id: str,
    *,
    posthog_user_id: int,
    entry_point: str,
    channel_id: str | None = None,
    thread_ts: str | None = None,
) -> None:
    """Open (or reuse) the DM and post the kickoff question; idempotent — an in-flight
    onboarding reposts its current step instead of resetting."""
    slack = SlackIntegration(integration)
    workspace_id = integration.integration_id
    row = get_or_create_settings_row(workspace_id, slack_user_id)
    if isinstance(row.onboarding_state, dict):
        ctx = _FlowContext(integration, slack, row, workspace_id, slack_user_id, row.onboarding_state)
        _repost_current_step(ctx)
        return
    # Kickoff runs off the request thread, so a double-click on Start (or a redelivered DM
    # event) can race here before state is saved — the claim makes the kickoff single-flight.
    claim_key = f"slack_persona_onboarding_start:{workspace_id}:{slack_user_id}"
    if not cache.add(claim_key, "1", timeout=_START_CLAIM_TTL_SECONDS):
        return
    try:
        row.refresh_from_db(fields=["onboarding_state"])
        if isinstance(row.onboarding_state, dict):
            return
        _post_kickoff(integration, slack, row, slack_user_id, entry_point, channel_id, thread_ts, posthog_user_id)
    finally:
        # By now state is saved (or the kickoff failed and may be retried) — the claim has done its job.
        cache.delete(claim_key)


def _post_kickoff(
    integration: Integration,
    slack: SlackIntegration,
    row: SlackSettings,
    slack_user_id: str,
    entry_point: str,
    channel_id: str | None,
    thread_ts: str | None,
    posthog_user_id: int,
) -> None:
    workspace_id = integration.integration_id
    candidate, source = detect_persona(slack, workspace_id, slack_user_id)
    display_name = _display_name(slack, slack_user_id)
    if channel_id is None:
        opened = slack.client.conversations_open(users=slack_user_id)
        channel_id = (opened.get("channel") or {}).get("id")
        if not channel_id:
            logger.warning("persona_onboarding_dm_open_failed", slack_user_id=slack_user_id)
            return
    blocks = build_kickoff_blocks(display_name, candidate)
    posted = slack.client.chat_postMessage(
        channel=channel_id, thread_ts=thread_ts, text="Quick setup — which best describes what you do?", blocks=blocks
    )
    row.onboarding_state = {
        "step": STEP_AWAITING_PERSONA,
        "persona_candidate": candidate,
        "detection_source": source,
        "team_id": integration.team_id,
        "integration_id": integration.id,
        "posthog_user_id": posthog_user_id,
        "dm_channel_id": channel_id,
        # A top-level kickoff roots its own conversation in the assistant surface — anchor
        # follow-ups under it so the whole flow stays in that one thread.
        "thread_ts": thread_ts or posted.get("ts"),
        "kickoff_ts": posted.get("ts"),
        "started_at": timezone.now().isoformat(),
    }
    row.save(update_fields=["onboarding_state", "updated_at"])
    capture_slack_event(
        integration,
        EVENT_STARTED,
        slack_user_id=slack_user_id,
        entry_point=entry_point,
        persona_candidate=candidate,
        detection_source=source or "none",
        search_available=slack_search.search_available(slack, workspace_id, slack_user_id),
    )


def maybe_intercept_assistant_surface(
    integration: Integration,
    *,
    posthog_user_id: int,
    workspace_id: str,
    slack_user_id: str,
    channel_id: str,
    thread_ts: str | None,
    accessible_integration_ids: list[int],
    entry_point: str,
) -> bool:
    """The DM / assistant-container gate. Returns True when the event was consumed by
    onboarding (caller must not start an agent task or post the default welcome)."""
    if not is_persona_onboarding_enabled(integration.team):
        return False
    row = get_or_create_settings_row(workspace_id, slack_user_id)
    if is_onboarded(row):
        return False
    if has_prior_slack_activity(accessible_integration_ids, slack_user_id):
        # An established user predating this flow — never ambush them with onboarding.
        _grandfather(integration, row, slack_user_id)
        return False
    # The consume/pass-through decision must be made inline, but everything past it talks to
    # Slack (detection searches, posts) — run it off the event-request thread so the events API
    # gets its ack inside Slack's 3s window (late acks trigger redelivery, i.e. duplicate posts).
    if isinstance(row.onboarding_state, dict):
        ctx = _FlowContext(
            integration, SlackIntegration(integration), row, workspace_id, slack_user_id, row.onboarding_state
        )
        if entry_point == "first_dm":
            _run_in_background(lambda: _post_nudge(ctx), task="nudge")
        else:
            # A re-opened assistant container is a fresh thread — retarget the stored pointer so the
            # repost lands where the user is looking, not in the (now hidden) original thread.
            if channel_id and (channel_id != ctx.state.get("dm_channel_id") or thread_ts != ctx.state.get("thread_ts")):
                ctx.state["dm_channel_id"] = channel_id
                ctx.state["thread_ts"] = thread_ts
                _save_state(ctx.row, ctx.state)
            _run_in_background(lambda: _repost_current_step(ctx), task="repost_step")
        return True
    _run_in_background(
        lambda: start_onboarding_dm(
            integration,
            slack_user_id,
            posthog_user_id=posthog_user_id,
            entry_point=entry_point,
            channel_id=channel_id,
            thread_ts=thread_ts,
        ),
        task="start_onboarding",
    )
    return True


def _run_in_background(fn: Callable[[], None], *, task: str) -> None:
    """Run best-effort work off the interactivity request thread. Slack voids a block action
    after 3s and shows a warning on the clicked button; the kickoff path makes far too many
    Slack API calls to fit, and every step of it is idempotent + user-retryable."""

    def runner() -> None:
        try:
            fn()
        except Exception:
            logger.exception("persona_onboarding_background_task_failed", task=task)
        finally:
            close_old_connections()

    threading.Thread(target=runner, name=f"persona-onboarding-{task}", daemon=True).start()


def handle_home_start(payload: dict) -> HttpResponse:
    workspace_id = str((payload.get("team") or {}).get("id") or "")
    slack_user_id = str((payload.get("user") or {}).get("id") or "")
    if workspace_id and slack_user_id:
        _run_in_background(lambda: _run_home_start(workspace_id, slack_user_id), task="home_start")
    return HttpResponse(status=200)


def _run_home_start(workspace_id: str, slack_user_id: str) -> None:
    result = load_integrations(slack_team_id=workspace_id, kinds=["slack"], slack_user_id=slack_user_id)
    if not result.candidates:
        return
    probe = result.integration if result.integration in result.candidates else result.candidates[0]
    if not is_persona_onboarding_enabled(probe.team):
        return
    resolution = resolve_user_for_workspace(
        workspace_result=result, slack_team_id=workspace_id, slack_user_id=slack_user_id
    )
    if resolution.user is None:
        return
    target = resolution.integration or (resolution.candidates[0] if resolution.candidates else probe)
    row = get_or_create_settings_row(workspace_id, slack_user_id)
    if is_onboarded(row):
        _republish_home(target, slack_user_id)
        return
    # Flip the Home card before the kickoff's Slack round-trips so the click gets instant
    # feedback, then converge to the truthful state however the kickoff ends — without the
    # finally, an exception mid-kickoff leaves the stale Start card up until the next open.
    _publish_starting_home(target, slack_user_id)
    try:
        start_onboarding_dm(target, slack_user_id, posthog_user_id=resolution.user.id, entry_point="home_button")
    finally:
        _republish_home(target, slack_user_id)


def handle_block_action(payload: dict, action: dict) -> HttpResponse:
    # Valued buttons carry their value as an ":<value>" action_id suffix (see `_button`);
    # routing happens on the base id. Every handler that talks to Slack or the DB runs off
    # the request thread: Slack voids a block action after 3s and paints a warning on the
    # clicked button, so the ack must never wait on our work.
    action_id = str(action.get("action_id") or "").split(":", 1)[0]
    if action_id == START_ACTION_ID:
        return handle_home_start(payload)
    if action_id in (OPEN_DM_ACTION_ID, CHANNEL_SELECT_ACTION_ID):
        # Open-DM is a URL button (the client navigates on its own); picking from the
        # dropdown is inert — Add PostHog commits the choice. Ack only.
        return HttpResponse(status=200)
    handlers: dict[str, Callable[[], None]] = {
        CONNECT_SOURCE_ACTION_ID: lambda: _handle_connect_click(payload, action),
        PERSONA_SELECT_ACTION_ID: lambda: _handle_persona_select(payload, action),
        SKIP_ACTION_ID: lambda: _handle_skip(payload),
        CHANNEL_CONFIRM_ACTION_ID: lambda: _handle_channel_confirm(payload),
        CHANNEL_CREATE_ACTION_ID: lambda: _handle_channel_create(payload),
        CHANNEL_VERIFY_ACTION_ID: lambda: _handle_channel_verify(payload, action),
    }
    handler = handlers.get(action_id)
    if handler is not None:
        _run_in_background(lambda: _run_action(handler, payload, action_id), task=action_id)
    return HttpResponse(status=200)


def _run_action(handler: Callable[[], None], payload: dict, action_id: str) -> None:
    try:
        handler()
    except Exception:
        logger.exception("persona_onboarding_action_failed", action_id=action_id)
        ctx = _load_context(payload)
        if ctx is not None:
            try:
                _post(ctx, [_section(ERROR_TEXT)], ERROR_TEXT)
            except Exception:
                logger.warning("persona_onboarding_error_post_failed", exc_info=True)


def _post_nudge(ctx: _FlowContext) -> None:
    step = ctx.state.get("step")
    text = NUDGE_CHANNEL_TEXT if step == STEP_AWAITING_CHANNEL else NUDGE_PERSONA_TEXT
    _post(ctx, [_section(text)], text)
    _repost_current_step(ctx)


def _repost_current_step(ctx: _FlowContext) -> None:
    step = ctx.state.get("step")
    if step == STEP_AWAITING_CHANNEL:
        pending_channel = ctx.state.get("pending_channel_id")
        if pending_channel:
            _post_invite_needed(ctx, pending_channel, ctx.state.get("pending_channel_name") or pending_channel)
        else:
            _post_channel_prompt(ctx)
        return
    display_name = _display_name(ctx.slack, ctx.slack_user_id)
    blocks = build_kickoff_blocks(display_name, ctx.state.get("persona_candidate"))
    _post(ctx, blocks, "Quick setup — which best describes what you do?")


def _post_channel_prompt(ctx: _FlowContext, can_create: bool | None = None) -> None:
    if can_create is None:
        can_create = _can_create_channel(ctx.slack)
    posted = _post(ctx, build_channel_prompt_blocks(can_create), "Pick a channel for scout findings.")
    _remember_message_ts(ctx, "channel_prompt_ts", posted)


def _post_invite_needed(ctx: _FlowContext, channel_id: str, channel_name: str) -> None:
    posted = _post(ctx, build_invite_needed_blocks(channel_id, channel_name), "Invite me to the channel, then verify.")
    _remember_message_ts(ctx, "invite_message_ts", posted)


def _can_create_channel(slack: SlackIntegration) -> bool:
    try:
        return not slack.missing_scopes(INBOX_CHANNEL_REQUIRED_SCOPES)
    except Exception:
        return False


def _handle_connect_click(payload: dict, action: dict) -> None:
    # URL button — the browser already navigated; just ack + record the click.
    ctx = _load_context(payload)
    if ctx is not None:
        scout_key, _, server_name = str(action.get("value") or "").rpartition(":")
        capture_slack_event(
            ctx.integration,
            EVENT_CONNECT_CLICKED,
            slack_user_id=ctx.slack_user_id,
            server_name=server_name,
            scout_readiness_key=scout_key or None,
        )


def handle_mcp_connect_return(
    *,
    workspace_id: str,
    slack_user_id: str,
    readiness_key: str,
    template_name: str,
    success: bool,
    error: str = "",
) -> str:
    """Post-OAuth landing for a Connect button: refresh the fleet-reveal message with fresh
    readiness and return the Slack deep link that sends the user back to the conversation."""
    row = SlackSettings.objects.filter(slack_workspace_id=workspace_id, slack_user_id=slack_user_id).first()
    state = row.onboarding_state if row is not None and isinstance(row.onboarding_state, dict) else None
    integration = None
    if state is not None:
        integration = Integration.objects.filter(id=state.get("integration_id"), kind="slack").first()
        if integration is not None and integration.integration_id != workspace_id:
            integration = None
    if integration is not None:
        capture_slack_event(
            integration,
            EVENT_MCP_CONNECTED,
            slack_user_id=slack_user_id,
            server_name=template_name,
            scout_readiness_key=readiness_key,
            success=success,
            error=error or None,
        )
        if row is not None and state is not None and success:
            _refresh_fleet_reveal(integration, row, state, workspace_id, slack_user_id)
    dm_channel_id = str(state.get("dm_channel_id") or "") if state else ""
    if dm_channel_id:
        return f"slack://channel?team={workspace_id}&id={dm_channel_id}"
    return f"slack://open?team={workspace_id}"


def _refresh_fleet_reveal(
    integration: Integration, row: SlackSettings, state: dict, workspace_id: str, slack_user_id: str
) -> None:
    readiness = check_csm_data_readiness(integration.team_id, state.get("posthog_user_id"))
    state["readiness"] = readiness.as_dict()
    _save_state(row, state)
    fleet_ts = state.get("fleet_message_ts")
    channel_id = state.get("dm_channel_id")
    if not fleet_ts or not channel_id:
        return
    blocks = build_fleet_reveal_blocks(
        integration.team_id,
        readiness.as_dict(),
        state.get("detected_tools") or [],
        list_active_templates(),
        workspace_id,
        slack_user_id,
    )
    try:
        SlackIntegration(integration).client.chat_update(
            channel=channel_id, ts=fleet_ts, text=FLEET_REVEAL_TEXT, blocks=blocks
        )
    except Exception:
        logger.warning("persona_onboarding_fleet_refresh_failed", exc_info=True)


def _remember_github_followup(ctx: _FlowContext, posted: SlackResponse) -> None:
    """Track the completion message whose Connect GitHub offer is open, so the post-OAuth signal
    (see ``resolve_github_connect_followups``) can flip it to ✅ and confirm in the thread."""
    ts = posted.get("ts")
    if not ts:
        return
    ctx.row.github_connect_followup = {
        "integration_id": ctx.integration.id,
        "team_id": ctx.integration.team_id,
        "posthog_user_id": ctx.state.get("posthog_user_id"),
        "channel_id": ctx.state.get("dm_channel_id"),
        "message_ts": ts,
        "thread_ts": ctx.state.get("thread_ts"),
    }
    ctx.row.save(update_fields=["github_connect_followup", "updated_at"])


def resolve_github_connect_followups(*, posthog_user_id: int | None = None, team_id: int | None = None) -> None:
    """GitHub-connected return leg. There is no browser callback into Slack here (the GitHub
    OAuth ends on a generic web page), so signal receivers call this when a GitHub integration
    row appears: every completion message still offering a connect that the new row could
    satisfy gets flipped to ✅ plus a confirmation reply. Idempotent — a compare-and-clear on
    the pointer makes each message resolve exactly once, even when the team install and the
    personal link land in separate requests."""
    if posthog_user_id is None and team_id is None:
        return
    rows = SlackSettings.objects.filter(github_connect_followup__isnull=False)
    if posthog_user_id is not None:
        rows = rows.filter(github_connect_followup__posthog_user_id=posthog_user_id)
    if team_id is not None:
        rows = rows.filter(github_connect_followup__team_id=team_id)
    for row in rows:
        followup = row.github_connect_followup or {}
        if not is_github_connected(followup.get("team_id"), followup.get("posthog_user_id")):
            continue  # the other half (team install or personal link) hasn't arrived yet
        claimed = SlackSettings.objects.filter(pk=row.pk, github_connect_followup=followup).update(
            github_connect_followup=None, updated_at=timezone.now()
        )
        if not claimed:
            continue
        integration = Integration.objects.filter(id=followup.get("integration_id"), kind="slack").first()
        if integration is None or integration.integration_id != row.slack_workspace_id:
            continue
        _post_github_connected_followup(integration, row, followup)


def _post_github_connected_followup(integration: Integration, row: SlackSettings, followup: dict) -> None:
    """Rewrite the connect offer to its ✅ note and confirm in the thread. Best-effort per
    message — the pointer is already claimed, so failures log and drop rather than retry."""
    client = SlackIntegration(integration).client
    channel_id = str(followup.get("channel_id") or "")
    message_ts = str(followup.get("message_ts") or "")
    if channel_id and message_ts:
        note_text = f"{ENGINEER_COMPLETION_TEXT} {GITHUB_CONNECTED_NOTE}"
        blocks = [_section(ENGINEER_COMPLETION_TEXT), _context(GITHUB_CONNECTED_NOTE)]
        try:
            client.chat_update(channel=channel_id, ts=message_ts, text=note_text, blocks=blocks)
        except Exception:
            logger.warning("persona_onboarding_github_followup_update_failed", exc_info=True)
    if channel_id:
        try:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=followup.get("thread_ts"),
                text=GITHUB_CONNECTED_FOLLOWUP_TEXT,
                blocks=[_section(GITHUB_CONNECTED_FOLLOWUP_TEXT)],
            )
        except Exception:
            logger.warning("persona_onboarding_github_followup_post_failed", exc_info=True)
    capture_slack_event(
        integration,
        EVENT_GITHUB_CONNECTED,
        slack_user_id=row.slack_user_id,
        persona=row.persona,
        posthog_user_id=followup.get("posthog_user_id"),
    )


def _handle_persona_select(payload: dict, action: dict) -> None:
    ctx = _load_context(payload)
    if ctx is None:
        return
    if ctx.state.get("step") != STEP_AWAITING_PERSONA:
        _repost_current_step(ctx)
        return
    persona = str(action.get("value") or "")
    if persona not in (PERSONA_CSM, PERSONA_ENGINEER, PERSONA_OTHER):
        return
    labels = {PERSONA_CSM: "Customer success (CSM)", PERSONA_ENGINEER: "Engineer", PERSONA_OTHER: "Something else"}
    # The CSM branch probes data readiness + workspace tools before its next post lands —
    # the freeze note doubles as a "working on it" so those seconds don't read as a hang.
    note = f"You picked: {labels[persona]}"
    if persona == PERSONA_CSM:
        note += " — one sec while I look at what data you have…"
    _freeze_buttons(ctx, payload, note)
    capture_slack_event(
        ctx.integration,
        EVENT_PERSONA_SELECTED,
        slack_user_id=ctx.slack_user_id,
        persona=persona,
        persona_candidate=ctx.state.get("persona_candidate"),
        matched_detection=persona == ctx.state.get("persona_candidate"),
    )

    if persona in (PERSONA_ENGINEER, PERSONA_OTHER):
        ctx.row.persona = persona
        ctx.row.onboarded_at = timezone.now()
        ctx.row.onboarding_state = None
        ctx.row.save(update_fields=["persona", "onboarded_at", "onboarding_state", "updated_at"])
        completion_props: dict[str, object] = {}
        github_connected = True
        if persona == PERSONA_ENGINEER:
            github_connected = check_engineer_github_connected(
                ctx.integration.team_id, ctx.state.get("posthog_user_id")
            )
            completion_props["github_connected"] = github_connected
            text = ENGINEER_GITHUB_CONNECTED_TEXT if github_connected else ENGINEER_GITHUB_NEEDED_TEXT
            blocks = build_engineer_completion_blocks(ctx.integration.team_id, github_connected)
        else:
            text = OTHER_COMPLETION_TEXT
            blocks = [_section(text)]
        posted = _post(ctx, blocks, text)
        if not github_connected:
            _remember_github_followup(ctx, posted)
        capture_slack_event(
            ctx.integration,
            EVENT_COMPLETED,
            slack_user_id=ctx.slack_user_id,
            persona=persona,
            scouts_provisioned=0,
            **completion_props,
        )
        _republish_home(ctx.integration, ctx.slack_user_id)
        return

    # CSM: reveal the fleet (with per-scout readiness + connect offers), then ask for a channel.
    ctx.row.persona = PERSONA_CSM
    readiness = check_csm_data_readiness(ctx.integration.team_id, ctx.state.get("posthog_user_id"))
    detected_tools = detect_workspace_tools(ctx.slack, ctx.workspace_id, ctx.slack_user_id)
    ctx.state.update(
        {"step": STEP_AWAITING_CHANNEL, "readiness": readiness.as_dict(), "detected_tools": detected_tools}
    )
    ctx.row.onboarding_state = ctx.state
    ctx.row.save(update_fields=["persona", "onboarding_state", "updated_at"])
    posted = _post(
        ctx,
        build_fleet_reveal_blocks(
            ctx.integration.team_id,
            readiness.as_dict(),
            detected_tools,
            list_active_templates(),
            ctx.workspace_id,
            ctx.slack_user_id,
        ),
        FLEET_REVEAL_TEXT,
    )
    # Remember the reveal message so the post-OAuth return leg can flip its ⚠️ lines to ✅.
    if posted and posted.get("ts"):
        ctx.state["fleet_message_ts"] = posted.get("ts")
        _save_state(ctx.row, ctx.state)
    _post_channel_prompt(ctx)
    capture_slack_event(
        ctx.integration,
        EVENT_FLEET_SHOWN,
        slack_user_id=ctx.slack_user_id,
        detected_tools=detected_tools,
        **readiness.as_dict(),
    )


def _handle_skip(payload: dict) -> None:
    ctx = _load_context(payload)
    if ctx is None:
        return
    step = ctx.state.get("step")
    _freeze_buttons(ctx, payload, "Setup skipped.")
    ctx.row.onboarded_at = timezone.now()
    ctx.row.onboarding_state = None
    ctx.row.save(update_fields=["onboarded_at", "onboarding_state", "updated_at"])
    _post(ctx, [_section(SKIP_TEXT)], SKIP_TEXT)
    capture_slack_event(ctx.integration, EVENT_SKIPPED, slack_user_id=ctx.slack_user_id, step=step)
    _republish_home(ctx.integration, ctx.slack_user_id)


def _channel_name_best_effort(slack: SlackIntegration, channel_id: str) -> str:
    try:
        info = slack.client.conversations_info(channel=channel_id)
        return (info.get("channel") or {}).get("name") or channel_id
    except Exception:
        return channel_id


def _handle_channel_confirm(payload: dict) -> None:
    ctx = _load_context(payload)
    if ctx is None:
        return
    if ctx.state.get("step") != STEP_AWAITING_CHANNEL:
        _repost_current_step(ctx)
        return
    values = (payload.get("state") or {}).get("values") or {}
    select_state = (values.get(CHANNEL_SELECT_BLOCK_ID) or {}).get(CHANNEL_SELECT_ACTION_ID) or {}
    channel_id = str(select_state.get("selected_conversation") or "")
    if not channel_id:
        _post(ctx, [_section(PICK_CHANNEL_FIRST_TEXT)], PICK_CHANNEL_FIRST_TEXT)
        return
    channel_name = _channel_name_best_effort(ctx.slack, channel_id)
    # Instant feedback + double-click protection: the whole setup runs off the ack thread and
    # takes seconds (hello post, provisioning, first runs), so the clicked controls must react now.
    _freeze_buttons(ctx, payload, f"⏳ Setting up #{channel_name} — sending your scouts on their first patrol…")
    _attempt_channel_setup(ctx, channel_id, channel_name, method="selected", repost_picker_on_invite=True)


def _handle_channel_create(payload: dict) -> None:
    ctx = _load_context(payload)
    if ctx is None:
        return
    if ctx.state.get("step") != STEP_AWAITING_CHANNEL:
        _repost_current_step(ctx)
        return
    if not _can_create_channel(ctx.slack):
        _post_channel_prompt(ctx, can_create=False)
        return
    _freeze_buttons(ctx, payload, "⏳ Creating #posthog-inbox and sending your scouts on their first patrol…")
    ensured = ensure_inbox_channel(ctx.integration)
    if ensured is None:
        _post_channel_prompt(ctx)
        _post(ctx, [_section(ERROR_TEXT)], ERROR_TEXT)
        return
    channel_id, channel_target_name = ensured
    invite_user_to_inbox(ctx.integration, channel_id, ctx.slack_user_id)
    _attempt_channel_setup(
        ctx, channel_id, channel_target_name.lstrip("#"), method="created", repost_picker_on_invite=True
    )


def _handle_channel_verify(payload: dict, action: dict) -> None:
    ctx = _load_context(payload)
    if ctx is None:
        return
    if ctx.state.get("step") != STEP_AWAITING_CHANNEL:
        _repost_current_step(ctx)
        return
    channel_id = str(action.get("value") or ctx.state.get("pending_channel_id") or "")
    if not channel_id:
        return
    channel_name = ctx.state.get("pending_channel_name") or _channel_name_best_effort(ctx.slack, channel_id)
    _freeze_buttons(ctx, payload, f"⏳ Checking #{channel_name}…")
    _attempt_channel_setup(ctx, channel_id, channel_name, method="selected", invite_required=True)


# Membership-shaped hello failures that the /invite-then-Verify flow can recover from.
_INVITE_FALLBACK_ERRORS = ("not_in_channel", "channel_not_found", "is_archived", "restricted_action")


def _post_channel_hello(ctx: _FlowContext, channel_id: str) -> str | None:
    """Post the channel hello; it doubles as the membership probe. Returns the Slack error
    string for membership-shaped failures, None on success; anything else raises."""
    try:
        ctx.slack.client.chat_postMessage(
            channel=channel_id,
            text=(
                f"👋 I'll post scout findings here — set up by <@{ctx.slack_user_id}>. "
                "First patrol is already underway."
            ),
        )
        return None
    except SlackApiError as exc:
        error = str((getattr(exc, "response", None) or {}).get("error", ""))
        if error in _INVITE_FALLBACK_ERRORS:
            return error
        raise


def _try_join_channel(slack: SlackIntegration, channel_id: str) -> bool:
    try:
        slack.client.conversations_join(channel=channel_id)
        return True
    except SlackApiError as exc:
        logger.warning(
            "persona_onboarding_channel_join_failed",
            channel_id=channel_id,
            error=(getattr(exc, "response", None) or {}).get("error"),
        )
        return False


def _attempt_channel_setup(
    ctx: _FlowContext,
    channel_id: str,
    channel_name: str,
    *,
    method: str,
    invite_required: bool = False,
    repost_picker_on_invite: bool = False,
) -> None:
    error = _post_channel_hello(ctx, channel_id)
    if error == "not_in_channel" and _try_join_channel(ctx.slack, channel_id):
        # Public channel and we hold channels:join — add ourselves instead of asking for /invite.
        error = _post_channel_hello(ctx, channel_id)
    if error is not None:
        ctx.state.update({"pending_channel_id": channel_id, "pending_channel_name": channel_name})
        _save_state(ctx.row, ctx.state)
        if repost_picker_on_invite:
            # The clicked picker was frozen for feedback — put a fresh one back so choosing a
            # different channel stays possible alongside the /invite path.
            _post_channel_prompt(ctx)
        _post_invite_needed(ctx, channel_id, channel_name)
        return
    capture_slack_event(
        ctx.integration,
        EVENT_CHANNEL_CONFIGURED,
        slack_user_id=ctx.slack_user_id,
        method=method,
        invite_required=invite_required,
    )
    _provision_and_complete(ctx, channel_id, channel_name)


def _resolve_channel_prompts(ctx: _FlowContext, channel_name: str) -> None:
    """Rewrite the now-stale channel-setup messages (prompt with the picker, invite-then-verify
    ask) to a done note so their controls don't linger after the channel is configured.
    Best-effort — a failure here never blocks completion."""
    note = f"✅ Channel set — I'll post scout findings to #{channel_name}."
    dm_channel_id = ctx.state.get("dm_channel_id")
    if not dm_channel_id:
        return
    # Deduped: both keys can point at the same message (e.g. after a repost), and one
    # rewrite per message is enough.
    for ts in dict.fromkeys(ctx.state.get(key) for key in ("channel_prompt_ts", "invite_message_ts")):
        if not ts:
            continue
        try:
            ctx.slack.client.chat_update(channel=dm_channel_id, ts=ts, text=note, blocks=[_section(note)])
        except Exception:
            logger.warning("persona_onboarding_channel_prompt_update_failed", exc_info=True)


def _provision_and_complete(ctx: _FlowContext, channel_id: str, channel_name: str) -> None:
    from products.signals.backend.facade.api import (  # noqa: PLC0415 — keeps the signals stack off the slack import path
        provision_persona_scouts,
    )

    user = User.objects.filter(id=ctx.state.get("posthog_user_id")).first()
    if user is None:
        _post(ctx, [_section(ERROR_TEXT)], ERROR_TEXT)
        return
    try:
        results = provision_persona_scouts(
            team=ctx.integration.team,
            created_by=user,
            slack_integration_id=ctx.integration.id,
            channel_id=channel_id,
            channel_name=channel_name,
            skill_names=[spec.skill_name for spec in PERSONA_SCOUT_CATALOG[PERSONA_CSM]],
        )
    except Exception:
        logger.exception("persona_onboarding_provisioning_failed", team_id=ctx.integration.team_id)
        _post(ctx, [_section(ERROR_TEXT)], ERROR_TEXT)
        return

    readiness = ctx.state.get("readiness") or {}
    channel_conflict = next((result.channel_conflict for result in results if result.channel_conflict), None)
    # Mark onboarded BEFORE the celebratory post: provisioning + first runs already happened, so a
    # transient post failure must not leave the user un-onboarded with live scouts (which would
    # re-fire all three first runs and re-post the channel hello on the next retry).
    ctx.row.persona = PERSONA_CSM
    ctx.row.onboarded_at = timezone.now()
    ctx.row.onboarding_state = None
    ctx.row.save(update_fields=["persona", "onboarded_at", "onboarding_state", "updated_at"])
    _resolve_channel_prompts(ctx, channel_name)
    _post(
        ctx,
        build_locked_in_blocks(
            ctx.integration.team.name, channel_name, readiness, channel_conflict, ctx.integration.team_id
        ),
        "You're locked in — your scouts are on their first patrol.",
    )
    capture_slack_event(
        ctx.integration,
        EVENT_COMPLETED,
        slack_user_id=ctx.slack_user_id,
        persona=PERSONA_CSM,
        scouts_provisioned=len([result for result in results if result.config_id]),
        first_runs_fired=len([result for result in results if result.first_run_started]),
        channel_conflict=bool(channel_conflict),
        **readiness,
    )
    _republish_home(ctx.integration, ctx.slack_user_id)
    _start_first_patrol_digest(ctx, results, channel_name)


def _start_first_patrol_digest(ctx: _FlowContext, results: list, channel_name: str) -> None:
    """Kick the delayed first-patrol digest workflow — best-effort, never user-visible on failure."""
    config_ids = [result.config_id for result in results if result.config_id and not result.channel_conflict]
    if not config_ids:
        return
    try:
        from products.slack_app.backend.first_patrol import (  # noqa: PLC0415 — keeps the temporal graph off the slack import path
            start_first_patrol_digest_workflow,
        )

        start_first_patrol_digest_workflow(
            team_id=ctx.integration.team_id,
            integration_id=ctx.integration.id,
            slack_user_id=ctx.slack_user_id,
            dm_channel_id=str(ctx.state.get("dm_channel_id") or ""),
            thread_ts=ctx.state.get("thread_ts"),
            channel_name=channel_name,
            scout_config_ids=config_ids,
            provisioned_at_iso=timezone.now().isoformat(),
        )
    except Exception:
        logger.warning("persona_onboarding_digest_dispatch_failed", exc_info=True)
