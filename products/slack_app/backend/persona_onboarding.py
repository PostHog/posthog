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

from django.http import HttpResponse
from django.utils import timezone

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration, SlackIntegration
from posthog.models.user import User

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.feature_flags import is_persona_onboarding_enabled
from products.slack_app.backend.inbox_channel import (
    INBOX_CHANNEL_REQUIRED_SCOPES,
    ensure_inbox_channel,
    invite_user_to_inbox,
)
from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping
from products.slack_app.backend.onboarding import _public_url
from products.slack_app.backend.services import slack_search
from products.slack_app.backend.services.integration_resolver import load_integrations, resolve_user_for_workspace

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
    connectable_sources: tuple[str, ...]  # ExternalDataSourceType values that would feed it
    gap_line: str  # "works best with …" copy when readiness is False


PERSONA_SCOUT_CATALOG: dict[str, tuple[ScoutSpec, ...]] = {
    PERSONA_CSM: (
        ScoutSpec(
            skill_name="signals-scout-csm-account-pulse",
            title="Account pulse",
            description=(
                "Watches each account's product usage and flags the ones sliding toward churn or "
                "heating up toward expansion, tagging the account owner."
            ),
            readiness_key="account_pulse",
            connectable_sources=("Salesforce", "Hubspot"),
            gap_line="works best with account data — PostHog customer analytics accounts or a synced CRM.",
        ),
        ScoutSpec(
            skill_name="signals-scout-csm-support-watch",
            title="Support watch",
            description=(
                "Watches support tickets for spikes, escalations, and accounts going loud (or silent) "
                "right before renewal."
            ),
            readiness_key="support_watch",
            connectable_sources=("Zendesk", "Intercom", "Linear", "Jira", "Freshdesk"),
            gap_line="works best with a ticketing tool.",
        ),
        ScoutSpec(
            skill_name="signals-scout-csm-revenue-watch",
            title="Renewal & billing watch",
            description=(
                "Watches billing data for failed payments, cancellations, and contraction on the accounts you own."
            ),
            readiness_key="revenue_watch",
            connectable_sources=("Stripe",),
            gap_line="works best with billing data — connect Stripe or PostHog revenue analytics.",
        ),
    ),
}

_TOOL_LABEL_BY_KIND = {tool.source_kind: tool.label for tool in _CONNECTABLE_TOOLS}

_SUPPORT_SOURCE_KINDS = ("Zendesk", "Intercom", "Linear", "Jira", "Freshdesk")
_CRM_SOURCE_KINDS = ("Salesforce", "Hubspot")


@dataclasses.dataclass(frozen=True)
class CsmDataReadiness:
    account_pulse: bool
    support_watch: bool
    revenue_watch: bool
    accounts_count: int

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def _active_source_kinds(team_id: int) -> set[str]:
    from products.warehouse_sources.backend.models.external_data_source import (  # noqa: PLC0415 — keeps the warehouse stack off the slack import path
        ExternalDataSource,
    )

    return set(
        ExternalDataSource.objects.filter(team_id=team_id).exclude(deleted=True).values_list("source_type", flat=True)
    )


def check_csm_data_readiness(team_id: int) -> CsmDataReadiness:
    """Per-scout data probes for the fleet reveal + completion copy. Presentation only —
    a probe failure renders as "no data yet", never blocks onboarding."""
    accounts_count = 0
    try:
        from products.customer_analytics.backend.models.account import (  # noqa: PLC0415 — keeps the customer-analytics stack off the slack import path
            Account,
        )

        accounts_count = Account.objects.for_team(team_id).count()
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

    return CsmDataReadiness(
        account_pulse=accounts_count > 0 or any(kind in source_kinds for kind in _CRM_SOURCE_KINDS),
        support_watch=tickets_exist or any(kind in source_kinds for kind in _SUPPORT_SOURCE_KINDS),
        revenue_watch="Stripe" in source_kinds,
        accounts_count=accounts_count,
    )


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
    button: dict = {"type": "button", "text": {"type": "plain_text", "text": label}, "action_id": action_id}
    if value:
        button["value"] = value
    if style:
        button["style"] = style
    if url:
        button["url"] = url
    return button


def build_kickoff_blocks(display_name: str, candidate: str | None) -> list[dict]:
    hey = f"👋 Hey {display_name}! I'm PostHog's AI co-worker."
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
        intro = f"{hey} Quick question so I can set things up right for you — which best describes what you do?"
        buttons = [
            _button("Engineer", PERSONA_SELECT_ACTION_ID, PERSONA_ENGINEER),
            _button("Customer success (CSM)", PERSONA_SELECT_ACTION_ID, PERSONA_CSM),
            _button("Something else", PERSONA_SELECT_ACTION_ID, PERSONA_OTHER),
            skip,
        ]
    return [_section(intro), {"type": "actions", "elements": buttons}]


def build_fleet_reveal_blocks(team_id: int, readiness: dict, detected_tools: list[str]) -> list[dict]:
    blocks: list[dict] = [
        _section(
            "Great — I'm going to create a few scouts for you. Scouts are little agents that patrol "
            "your data on a schedule and ping you whenever there's something to worry about "
            f"(<{SCOUTS_DOC_URL}|here's how they work>)."
        )
    ]
    for index, spec in enumerate(PERSONA_SCOUT_CATALOG[PERSONA_CSM], start=1):
        blocks.append(_section(f"*{index}. {spec.title}*\n{spec.description}"))
        if readiness.get(spec.readiness_key):
            blocks.append(_context("✅ Ready — I can see the data this needs."))
            continue
        detected_kind = next((kind for kind in detected_tools if kind in spec.connectable_sources), None)
        if detected_kind:
            label = _TOOL_LABEL_BY_KIND.get(detected_kind, detected_kind)
            blocks.append(
                _section(f"⚠️ {spec.title} {spec.gap_line} I see you're using {label} — want to connect it now?")
            )
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        _button(
                            f"Connect {label}",
                            CONNECT_SOURCE_ACTION_ID,
                            detected_kind,
                            url=source_connect_url(team_id, detected_kind),
                        )
                    ],
                }
            )
        else:
            blocks.append(_context(f"⚠️ {spec.gap_line} Connect one any time — this scout picks it up automatically."))
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        _button("Browse sources", CONNECT_SOURCE_ACTION_ID, "catalog", url=sources_catalog_url(team_id))
                    ],
                }
            )
    blocks.append(_context("Don't worry — I'll create these now and they activate themselves as data shows up."))
    return blocks


def build_channel_prompt_blocks(can_create_channel: bool) -> list[dict]:
    elements: list[dict] = [
        {
            "type": "conversations_select",
            "action_id": CHANNEL_SELECT_ACTION_ID,
            "placeholder": {"type": "plain_text", "text": "Pick a channel"},
            # Never offer external-shared channels — these alerts carry account intel.
            "filter": {"include": ["public"], "exclude_external_shared_channels": True, "exclude_bot_users": True},
        }
    ]
    if can_create_channel:
        elements.append(_button("Create #posthog-inbox", CHANNEL_CREATE_ACTION_ID))
    return [
        _section(
            "One more thing: this works best if you add me to a channel where I can post findings. "
            "Pick one, or I can create #posthog-inbox for you."
            if can_create_channel
            else "One more thing: this works best if you add me to a channel where I can post findings. Pick one below."
        ),
        {"type": "actions", "elements": elements},
    ]


def build_invite_needed_blocks(channel_id: str, channel_name: str) -> list[dict]:
    return [
        _section(
            f"I can't post in #{channel_name} yet — I'm not a member. Type `/invite @PostHog` in that "
            "channel, then tap Verify."
        ),
        {"type": "actions", "elements": [_button("Verify", CHANNEL_VERIFY_ACTION_ID, channel_id, style="primary")]},
    ]


def build_locked_in_blocks(
    team_id: int, channel_name: str, readiness: dict, channel_conflict: str | None
) -> list[dict]:
    if channel_conflict:
        first = (
            f"Your scouts are already running for this project and posting to #{channel_conflict} — "
            "I've left that as-is. You're onboarded! 🎉"
        )
    else:
        first = (
            "🎉 You're locked in. I've already sent your scouts on their first patrol — I'll message "
            f"you when a scout finds something, and findings land in #{channel_name} with the account "
            "owner tagged when I can find them."
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
            f"Manage your scouts (pause, cadence, run history) any time from your <{inbox_url(team_id)}|PostHog inbox>."
            "\n\nIn the meantime, do you want to work on anything? You can ask me things like:\n"
            "• _Which of my accounts had the biggest usage drop this month?_\n"
            "• _Summarize what Acme did last week._"
        )
    )
    return blocks


ENGINEER_COMPLETION_TEXT = (
    "Got it — engineer it is. 🛠️ Mention `@PostHog` in a channel or message me here to hand me a "
    "task — I can investigate your data, dig through errors, and open PRs. If you haven't yet, "
    "connect GitHub and pick your sources from the setup message I send when the app is installed."
)
OTHER_COMPLETION_TEXT = (
    "Thanks! Message me here any time — ask about your product data, dashboards, or anything PostHog."
)
SKIP_TEXT = "No problem — skipping setup. Message me whenever; settings live in my Home tab."
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
    return _FlowContext(integration, SlackIntegration(integration), row, workspace_id, slack_user_id, state)


def _display_name(slack: SlackIntegration, slack_user_id: str) -> str:
    try:
        info = slack.client.users_info(user=slack_user_id)
        profile = (info.get("user") or {}).get("profile") or {}
        name = profile.get("display_name") or profile.get("real_name") or ""
        return name.split()[0] if name else "there"
    except Exception:
        return "there"


def _post(ctx: _FlowContext, blocks: list[dict], text: str) -> None:
    ctx.slack.client.chat_postMessage(
        channel=ctx.state.get("dm_channel_id"),
        thread_ts=ctx.state.get("thread_ts"),
        text=text,
        blocks=blocks,
    )


def _save_state(row: SlackSettings, state: dict | None) -> None:
    row.onboarding_state = state
    row.save(update_fields=["onboarding_state", "updated_at"])


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
        "thread_ts": thread_ts,
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
    if isinstance(row.onboarding_state, dict):
        ctx = _FlowContext(
            integration, SlackIntegration(integration), row, workspace_id, slack_user_id, row.onboarding_state
        )
        if entry_point == "first_dm":
            _post_nudge(ctx)
        else:
            _repost_current_step(ctx)
        return True
    start_onboarding_dm(
        integration,
        slack_user_id,
        posthog_user_id=posthog_user_id,
        entry_point=entry_point,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )
    return True


def handle_home_start(payload: dict) -> HttpResponse:
    workspace_id = str((payload.get("team") or {}).get("id") or "")
    slack_user_id = str((payload.get("user") or {}).get("id") or "")
    if not workspace_id or not slack_user_id:
        return HttpResponse(status=200)
    result = load_integrations(slack_team_id=workspace_id, kinds=["slack"], slack_user_id=slack_user_id)
    if not result.candidates:
        return HttpResponse(status=200)
    probe = result.integration if result.integration in result.candidates else result.candidates[0]
    if not is_persona_onboarding_enabled(probe.team):
        return HttpResponse(status=200)
    resolution = resolve_user_for_workspace(
        workspace_result=result, slack_team_id=workspace_id, slack_user_id=slack_user_id
    )
    if resolution.user is None:
        return HttpResponse(status=200)
    target = resolution.integration or (resolution.candidates[0] if resolution.candidates else probe)
    row = get_or_create_settings_row(workspace_id, slack_user_id)
    if is_onboarded(row):
        _republish_home(target, slack_user_id)
        return HttpResponse(status=200)
    start_onboarding_dm(target, slack_user_id, posthog_user_id=resolution.user.id, entry_point="home_button")
    _republish_home(target, slack_user_id)
    return HttpResponse(status=200)


def handle_block_action(payload: dict, action: dict) -> HttpResponse:
    action_id = str(action.get("action_id") or "")
    try:
        if action_id == START_ACTION_ID:
            return handle_home_start(payload)
        if action_id == CONNECT_SOURCE_ACTION_ID:
            _handle_connect_click(payload, action)
        elif action_id == PERSONA_SELECT_ACTION_ID:
            _handle_persona_select(payload, action)
        elif action_id == SKIP_ACTION_ID:
            _handle_skip(payload)
        elif action_id == CHANNEL_SELECT_ACTION_ID:
            _handle_channel_select(payload, action)
        elif action_id == CHANNEL_CREATE_ACTION_ID:
            _handle_channel_create(payload)
        elif action_id == CHANNEL_VERIFY_ACTION_ID:
            _handle_channel_verify(payload, action)
    except Exception:
        logger.exception("persona_onboarding_action_failed", action_id=action_id)
        ctx = _load_context(payload)
        if ctx is not None:
            try:
                _post(ctx, [_section(ERROR_TEXT)], ERROR_TEXT)
            except Exception:
                logger.warning("persona_onboarding_error_post_failed", exc_info=True)
    return HttpResponse(status=200)


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
            blocks = build_invite_needed_blocks(
                pending_channel, ctx.state.get("pending_channel_name") or pending_channel
            )
        else:
            blocks = build_channel_prompt_blocks(_can_create_channel(ctx.slack))
        _post(ctx, blocks, "Pick a channel for scout findings.")
        return
    display_name = _display_name(ctx.slack, ctx.slack_user_id)
    blocks = build_kickoff_blocks(display_name, ctx.state.get("persona_candidate"))
    _post(ctx, blocks, "Quick setup — which best describes what you do?")


def _can_create_channel(slack: SlackIntegration) -> bool:
    try:
        return not slack.missing_scopes(INBOX_CHANNEL_REQUIRED_SCOPES)
    except Exception:
        return False


def _handle_connect_click(payload: dict, action: dict) -> None:
    # URL button — the browser already navigated; just ack + record the click.
    ctx = _load_context(payload)
    if ctx is not None:
        capture_slack_event(
            ctx.integration,
            EVENT_CONNECT_CLICKED,
            slack_user_id=ctx.slack_user_id,
            source_kind=str(action.get("value") or ""),
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
    _freeze_buttons(ctx, payload, f"You picked: {labels[persona]}")
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
        text = ENGINEER_COMPLETION_TEXT if persona == PERSONA_ENGINEER else OTHER_COMPLETION_TEXT
        _post(ctx, [_section(text)], text)
        capture_slack_event(
            ctx.integration, EVENT_COMPLETED, slack_user_id=ctx.slack_user_id, persona=persona, scouts_provisioned=0
        )
        _republish_home(ctx.integration, ctx.slack_user_id)
        return

    # CSM: reveal the fleet (with per-scout readiness + connect offers), then ask for a channel.
    ctx.row.persona = PERSONA_CSM
    readiness = check_csm_data_readiness(ctx.integration.team_id)
    detected_tools = detect_workspace_tools(ctx.slack, ctx.workspace_id, ctx.slack_user_id)
    ctx.state.update(
        {"step": STEP_AWAITING_CHANNEL, "readiness": readiness.as_dict(), "detected_tools": detected_tools}
    )
    ctx.row.onboarding_state = ctx.state
    ctx.row.save(update_fields=["persona", "onboarding_state", "updated_at"])
    _post(
        ctx,
        build_fleet_reveal_blocks(ctx.integration.team_id, readiness.as_dict(), detected_tools),
        "I'm going to create a few scouts for you.",
    )
    _post(ctx, build_channel_prompt_blocks(_can_create_channel(ctx.slack)), "Pick a channel for scout findings.")
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


def _handle_channel_select(payload: dict, action: dict) -> None:
    ctx = _load_context(payload)
    if ctx is None:
        return
    if ctx.state.get("step") != STEP_AWAITING_CHANNEL:
        _repost_current_step(ctx)
        return
    channel_id = str(action.get("selected_conversation") or "")
    if not channel_id:
        return
    channel_name = _channel_name_best_effort(ctx.slack, channel_id)
    _attempt_channel_setup(ctx, channel_id, channel_name, method="selected")


def _handle_channel_create(payload: dict) -> None:
    ctx = _load_context(payload)
    if ctx is None:
        return
    if ctx.state.get("step") != STEP_AWAITING_CHANNEL:
        _repost_current_step(ctx)
        return
    if not _can_create_channel(ctx.slack):
        _post(ctx, build_channel_prompt_blocks(False), "Pick a channel for scout findings.")
        return
    ensured = ensure_inbox_channel(ctx.integration)
    if ensured is None:
        _post(ctx, [_section(ERROR_TEXT)], ERROR_TEXT)
        return
    channel_id, channel_target_name = ensured
    invite_user_to_inbox(ctx.integration, channel_id, ctx.slack_user_id)
    _attempt_channel_setup(ctx, channel_id, channel_target_name.lstrip("#"), method="created")


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
    _attempt_channel_setup(ctx, channel_id, channel_name, method="selected", invite_required=True)


def _attempt_channel_setup(
    ctx: _FlowContext, channel_id: str, channel_name: str, *, method: str, invite_required: bool = False
) -> None:
    # The hello post doubles as the membership probe — the only check that works with the
    # scopes we actually hold (no channels:read / channels:join / chat:write.public).
    try:
        ctx.slack.client.chat_postMessage(
            channel=channel_id,
            text=(
                f"👋 I'll post scout findings here — set up by <@{ctx.slack_user_id}>. "
                "First patrol is already underway."
            ),
        )
    except SlackApiError as exc:
        error = (getattr(exc, "response", None) or {}).get("error", "")
        if error in ("not_in_channel", "channel_not_found", "is_archived", "restricted_action"):
            ctx.state.update({"pending_channel_id": channel_id, "pending_channel_name": channel_name})
            _save_state(ctx.row, ctx.state)
            _post(ctx, build_invite_needed_blocks(channel_id, channel_name), "Invite me to the channel, then verify.")
            return
        raise
    capture_slack_event(
        ctx.integration,
        EVENT_CHANNEL_CONFIGURED,
        slack_user_id=ctx.slack_user_id,
        method=method,
        invite_required=invite_required,
    )
    _provision_and_complete(ctx, channel_id, channel_name)


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
    _post(
        ctx,
        build_locked_in_blocks(ctx.integration.team_id, channel_name, readiness, channel_conflict),
        "You're locked in — your scouts are on their first patrol.",
    )
    ctx.row.persona = PERSONA_CSM
    ctx.row.onboarded_at = timezone.now()
    ctx.row.onboarding_state = None
    ctx.row.save(update_fields=["persona", "onboarded_at", "onboarding_state", "updated_at"])
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
