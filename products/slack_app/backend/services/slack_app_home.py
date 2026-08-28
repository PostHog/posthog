"""App Home tab + edit modal renderers for the PostHog Slack app.

The Home tab is the user-facing control panel for the integration. For this
first iteration it carries one card — the AI preferences picker that feeds
Slack-triggered task runs — but the layout leaves room for additional cards
(notifications, account linking, activity feed) as they come online. Each card
follows the same pattern: a one-line "effective" summary, an admin-aware edit
control, and an optional explainer of where the effective value came from.

All Block Kit payloads (views, modals) are built as plain dicts here so they
can be unit-tested without any Slack client. The event/interactivity handlers
in `products/slack_app/backend/api.py` are the ones that actually call
`views.publish` / `views.open` / `views.update`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse

import structlog

from posthog.models.integration import SLACK_INTEGRATION_KINDS, Integration, SlackIntegration
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.user_permissions import UserPermissions

from products.slack_app.backend.feature_flags import (
    is_slack_app_home_enabled,
    is_slack_app_oauth_enabled,
    is_slack_app_untagged_thread_followups_enabled,
)
from products.slack_app.backend.models import SlackSettings, SlackUserProfileCache, UntaggedFollowupMode
from products.slack_app.backend.services.integration_resolver import load_integrations
from products.slack_app.backend.services.model_catalogue import (
    REASONING_EFFORT_DISPLAY_NAMES,
    RUNTIME_ADAPTER_DISPLAY_NAMES,
    available_model_choices,
    describe_run_model,
    format_model_id,
    group_by_runtime,
    label_for,
)
from products.slack_app.backend.services.run_preferences import SLACK_DEFAULT_MODEL
from products.slack_app.backend.services.slack_app_home_stats import (
    DEFAULT_STATS_WINDOW_DAYS,
    OUTCOME_CANCELLED,
    OUTCOME_DONE,
    OUTCOME_FAILED,
    OUTCOME_RUNNING,
    STATS_MAX_TASKS,
    STATS_WINDOW_OPTIONS,
    ModelUsage,
    StatsState,
    build_stats_state,
    coerce_window_days,
)
from products.slack_app.backend.services.slack_settings import (
    AIPreferences,
    build_ai_preferences_payload,
    resolve_ai_preferences,
    resolve_untagged_followup_mode,
    validate_ai_preferences,
)
from products.slack_app.backend.services.slack_user_info import is_slack_workspace_admin
from products.slack_app.backend.services.slack_user_oauth import build_invite_url, find_linked_posthog_user

logger = structlog.get_logger(__name__)

# Block / action / callback identifiers. Centralised so the interactivity
# handler in api.py and the renderers here cannot drift apart.
HOME_CALLBACK_ID = "slack_app_home"

ACTION_EDIT_PERSONAL = "slack_app_home:edit_personal"
ACTION_RESET_PERSONAL = "slack_app_home:reset_personal"
ACTION_UNLINK_ACCOUNT = "slack_app_home:unlink_account"
ACTION_SET_PROJECT_PERSONAL = "slack_app_home:set_project_personal"
ACTION_SET_PROJECT_WORKSPACE = "slack_app_home:set_project_workspace"
ACTION_RESET_PROJECT_PERSONAL = "slack_app_home:reset_project_personal"
ACTION_TASKS_FILTER_REPO = "slack_app_home:tasks_filter_repo"
ACTION_TASKS_FILTER_STATUS = "slack_app_home:tasks_filter_status"
ACTION_TASKS_REFRESH = "slack_app_home:tasks_refresh"
# Slack requires every action_id to be unique within a view, so Prev/Next
# can't share one id — they both carry the target page as `value`.
ACTION_TASKS_PAGE_PREV = "slack_app_home:tasks_page_prev"
ACTION_TASKS_PAGE_NEXT = "slack_app_home:tasks_page_next"
ACTION_STATS_WINDOW = "slack_app_home:stats_window"
ACTION_STATS_REFRESH = "slack_app_home:stats_refresh"
ACTION_SET_UNTAGGED_FOLLOWUP_MODE = "slack_app_home:set_untagged_followup_mode"

# Every control the Home tab renders, in one place. The interactivity endpoint reads
# this to claim region ownership and to dispatch, so a control that isn't listed here
# renders as a button that silently does nothing. Adding an action id above without
# adding it here is the failure this set exists to prevent.
HOME_ACTION_IDS: frozenset[str] = frozenset(
    {
        ACTION_EDIT_PERSONAL,
        ACTION_RESET_PERSONAL,
        ACTION_UNLINK_ACCOUNT,
        ACTION_SET_PROJECT_PERSONAL,
        ACTION_SET_PROJECT_WORKSPACE,
        ACTION_RESET_PROJECT_PERSONAL,
        ACTION_TASKS_FILTER_REPO,
        ACTION_TASKS_FILTER_STATUS,
        ACTION_TASKS_REFRESH,
        ACTION_TASKS_PAGE_PREV,
        ACTION_TASKS_PAGE_NEXT,
        ACTION_STATS_WINDOW,
        ACTION_STATS_REFRESH,
        ACTION_SET_UNTAGGED_FOLLOWUP_MODE,
    }
)

# Single block_id for the whole controls row. Block Kit only persists
# state in `view.state.values` under blocks that carry a `block_id`, so
# both the repo and the status dropdowns live under the same key here and
# the handler can read them back on each pick.
BLOCK_TASKS_CONTROLS = "block_tasks_controls"
BLOCK_STATS_CONTROLS = "block_stats_controls"

# Sentinel value the "All …" options carry — Slack rejects empty `value`
# strings, so the resolver treats this as "no filter".
TASKS_FILTER_ALL = "all"

# Status keys the filter picker exposes — superset of `TaskRun.Status` values
# we surface on the card. Kept here so the renderer and resolver stay in sync.
TASKS_STATUS_OPTIONS: tuple[tuple[str, str], ...] = (
    (TASKS_FILTER_ALL, "All statuses"),
    ("in_progress", "🔄 in progress"),
    ("completed", "🦔 done"),
    ("failed", "❌ failed"),
    ("cancelled", "🚫 cancelled"),
    ("queued", "⏳ queued"),
    ("not_started", "🕒 not started"),
)

EDIT_MODAL_PERSONAL_CALLBACK_ID = "slack_app_ai_prefs:personal"

MODAL_ACTION_RUNTIME_ADAPTER = "ai_prefs:runtime_adapter"
MODAL_ACTION_MODEL = "ai_prefs:model"
MODAL_ACTION_REASONING_EFFORT = "ai_prefs:reasoning_effort"

MODAL_BLOCK_RUNTIME_ADAPTER = "block_runtime_adapter"
# Prefixes, not literal block ids: Slack carries a block's state across `views.update`
# whenever the `block_id` is unchanged, which is how a model picked under the previous
# runtime used to survive a runtime switch and get submitted. Suffixing each dependent
# block with what it depends on makes the re-rendered block a new one to Slack, so the
# stale pick is dropped instead of hiding behind the fresh options. See `_scoped_block_id`.
MODAL_BLOCK_MODEL = "block_model"
MODAL_BLOCK_REASONING_EFFORT = "block_reasoning_effort"


@dataclass(frozen=True)
class PickerEffort:
    value: str
    label: str


@dataclass(frozen=True)
class PickerModel:
    value: str
    label: str
    supported_efforts: tuple[PickerEffort, ...]


@dataclass(frozen=True)
class PickerAdapter:
    value: str
    label: str
    models: tuple[PickerModel, ...]


def get_picker_choices() -> tuple[PickerAdapter, ...]:
    """Dress the catalogue's runtime → model tree in the effort labels the modal's linked
    dropdowns render. Adapters with no available models are omitted entirely."""
    return tuple(
        PickerAdapter(
            value=group.runtime_adapter,
            label=group.label,
            models=tuple(
                PickerModel(
                    value=choice.model,
                    label=choice.label,
                    supported_efforts=tuple(
                        PickerEffort(value=e, label=label_for(e, REASONING_EFFORT_DISPLAY_NAMES))
                        for e in choice.supported_efforts
                    ),
                )
                for choice in group.choices
            ),
        )
        for group in group_by_runtime(available_model_choices())
    )


def _models_for(runtime_adapter: str) -> tuple[tuple[str, str], ...]:
    """Return `(value, label)` pairs for the modal's model dropdown."""
    for adapter in get_picker_choices():
        if adapter.value == runtime_adapter:
            return tuple((m.value, m.label) for m in adapter.models)
    return ()


def _runtime_adapter_options() -> tuple[tuple[str, str], ...]:
    """Return `(value, label)` pairs for the modal's runtime dropdown."""
    return tuple((a.value, a.label) for a in get_picker_choices())


@dataclass(frozen=True)
class PreferenceSource:
    """Whether the user's own row contributed the effective `(runtime_adapter,
    model)` pair.

    Used to render the "Source: …" line on the active-model card so it's clear
    at a glance whether the running model is a personal pick.
    """

    label: str

    @classmethod
    def personal(cls) -> PreferenceSource:
        return cls(label="Your personal override")

    @classmethod
    def unset(cls) -> PreferenceSource:
        return cls(label="System default")


def resolve_source(user_row: SlackSettings | None) -> PreferenceSource:
    """Return where the effective pair came from.

    Mirrors the same atomic-pair rule the resolver uses: a row only "sources"
    the pair when both halves are set on it.
    """
    if user_row and user_row.runtime_adapter and user_row.model:
        return PreferenceSource.personal()
    return PreferenceSource.unset()


@dataclass(frozen=True)
class ProjectChoice:
    """One PostHog project the user can route their @PostHog mentions to."""

    team_id: int
    label: str


@dataclass(frozen=True)
class ProjectState:
    """Inputs the renderer needs to draw the project-routing card.

    ``candidates`` is the accessible subset the user can pick from; the
    workspace default is resolved against the full workspace integration
    list so it surfaces even when the user can't access that project.
    """

    candidates: tuple[ProjectChoice, ...] = ()
    personal_team_id: int | None = None
    workspace_team_id: int | None = None
    workspace_team_label: str | None = None

    @property
    def has_anything_to_show(self) -> bool:
        return bool(self.candidates) or self.workspace_team_label is not None


@dataclass(frozen=True)
class TaskItem:
    """One row on the Tasks card."""

    title: str
    # Both task links are `None` for a viewer without PostHog Code access, matching the
    # reply footer: a task page they can't open is as much a dead end as the desktop app.
    # Stated at every construction rather than defaulted, so a row can't lose its links
    # by omission and render as plain text.
    posthog_url: str | None
    desktop_url: str | None
    status: str | None  # TaskRun.Status value or None when there's no run yet
    repository: str | None
    pr_url: str | None
    thread_url: str | None
    updated_at_label: str
    error_message: str | None = None  # surfaced on row 2 in place of the normal meta line


@dataclass(frozen=True)
class TasksState:
    """Inputs the renderer needs to draw the Tasks card.

    ``items`` is already paginated to a single page. ``available_repos``
    is computed against the unfiltered set so picking a repo doesn't make
    the others disappear from the dropdown.
    """

    items: tuple[TaskItem, ...] = ()
    available_repos: tuple[str, ...] = ()
    selected_repo: str | None = None
    selected_status: str | None = None
    has_any_tasks: bool = False
    page: int = 0
    total_pages: int = 0
    total_filtered: int = 0
    refreshed_at_epoch: int = 0  # Unix seconds; 0 hides the "Last refreshed" line

    @property
    def has_prev(self) -> bool:
        return self.page > 0

    @property
    def has_next(self) -> bool:
        return self.page + 1 < self.total_pages


@dataclass(frozen=True)
class HomeViewState:
    """The Home tab's control settings, as they stood when the user clicked.

    Slack holds no server-side state for a published Home tab; each `block_actions`
    payload instead carries the whole view's inputs. Reading them into one object means
    an action on any card republishes the others exactly as they were, instead of
    resetting them to their defaults.
    """

    selected_repo: str | None = None
    selected_status: str | None = None
    tasks_page: int = 0
    stats_window_days: int = DEFAULT_STATS_WINDOW_DAYS
    stats_force_refresh: bool = False

    @classmethod
    def from_payload(cls, payload: dict) -> HomeViewState:
        # Block Kit only persists state under blocks carrying a `block_id`, so each
        # card's controls row shares one key. Absent blocks (a card the viewer doesn't
        # get) simply fall back to defaults.
        values = (payload.get("view") or {}).get("state", {}).get("values", {}) or {}
        return cls(
            selected_repo=_selected_value(values, BLOCK_TASKS_CONTROLS, ACTION_TASKS_FILTER_REPO),
            selected_status=_selected_value(values, BLOCK_TASKS_CONTROLS, ACTION_TASKS_FILTER_STATUS),
            stats_window_days=coerce_window_days(_selected_value(values, BLOCK_STATS_CONTROLS, ACTION_STATS_WINDOW)),
        )


@dataclass(frozen=True)
class AccountState:
    """Inputs the renderer needs to draw the optional account-link card.

    Carries no business logic — the handler computes whether the flag is on
    and whether the Slack user is currently linked, and hands the result
    here so the renderer stays a pure function.
    """

    enabled: bool = False
    linked_email: str | None = None
    link_url: str | None = None


@dataclass(frozen=True)
class GitHubAccount:
    """One personal GitHub App installation the user has connected."""

    installation_id: str
    login: str | None = None
    account_name: str | None = None

    @property
    def label(self) -> str:
        """`login` is the GitHub user who authorized; `account_name` is the org
        or user the App is installed on. Show both when they differ."""
        if self.login and self.account_name and self.login != self.account_name:
            return f"`{self.login}` on *{self.account_name}*"
        return f"`{self.login or self.account_name or self.installation_id}`"


@dataclass(frozen=True)
class GitHubState:
    """Inputs the renderer needs to draw the GitHub half of the accounts card.

    ``user_resolved`` is False when we couldn't tell which PostHog user is
    behind this Slack identity — the card then asks them to link PostHog first
    instead of claiming they have no GitHub connection.

    ``credentials_usable`` carries the same judgment the task flow gates on,
    so a row whose tokens have gone stale reads as needing a reconnect rather
    than as a working connection.
    """

    user_resolved: bool = False
    accounts: tuple[GitHubAccount, ...] = ()
    credentials_usable: bool = False
    settings_url: str | None = None


def render_home_view(
    *,
    effective: AIPreferences,
    user_row: SlackSettings | None,
    is_admin: bool,
    account_state: AccountState | None = None,
    github_state: GitHubState | None = None,
    project_state: ProjectState | None = None,
    tasks_state: TasksState | None = None,
    stats_state: StatsState | None = None,
    untagged_followup_mode: UntaggedFollowupMode | None = None,
    has_project_access: bool = True,
) -> dict:
    """Render the Block Kit payload for `views.publish` on the App Home tab."""

    source = resolve_source(user_row)
    blocks: list[dict] = []

    blocks.extend(_header_blocks())

    # Nothing below the fold means anything to someone who can't reach a project: the
    # cards are scoped to one, and mentioning @PostHog won't work either. Say so once
    # and stop, rather than drawing empty cards that read as "you have no tasks yet".
    if not has_project_access:
        blocks.append({"type": "divider"})
        blocks.extend(_no_project_access_blocks())
        return {"type": "home", "callback_id": HOME_CALLBACK_ID, "blocks": blocks}

    # Section 1 — workspace activity: aggregates across everyone's Slack-started work,
    # rather than the calling user's own. Admin-only, and first because it's the reason
    # an admin opens the tab at all — the settings below are set once and rarely revisited.
    if stats_state is not None:
        blocks.append({"type": "divider"})
        blocks.extend(_stats_section_blocks(stats_state))

    # Section 2 — project routing. Personal pick on top; admins get an
    # editable workspace default below, others see it as read-only context.
    if project_state and project_state.has_anything_to_show:
        blocks.append({"type": "divider"})
        blocks.extend(_project_section_blocks(project_state, is_admin=is_admin))

    # Section 3 — AI model settings: which model handles those mentions.
    # Headline shows the effective triple (and its source), with the personal
    # picker underneath. Purely a per-user preference — there's no workspace-wide
    # model default to inherit from.
    blocks.append({"type": "divider"})
    blocks.extend(_active_model_blocks(effective, source))
    blocks.extend(_personal_section_blocks(user_row))

    # Section 4 — thread follow-ups: whether replies other people leave in the
    # threads you started reach PostHog on their own. Absent when the workspace
    # hasn't been opted into untagged follow-ups at all.
    if untagged_followup_mode is not None:
        blocks.append({"type": "divider"})
        blocks.extend(_untagged_followups_section_blocks(untagged_followup_mode))

    # Section 5 — linked accounts: PostHog and GitHub side by side, shown
    # before Tasks so the connect prompts are visible while the Tasks list
    # is still empty. The PostHog half is flag-gated.
    if (account_state and account_state.enabled) or github_state is not None:
        blocks.append({"type": "divider"})
        blocks.extend(_linked_accounts_section_blocks(account_state, github_state))

    # Section 6 — your tasks: a quiet list of tasks the calling user
    # started via @PostHog mentions, so they can see status without
    # the bot pinging the activity feed for every transition.
    if tasks_state is not None:
        blocks.append({"type": "divider"})
        blocks.extend(_tasks_section_blocks(tasks_state))

    blocks.append({"type": "divider"})
    blocks.extend(_footer_blocks())

    return {"type": "home", "callback_id": HOME_CALLBACK_ID, "blocks": blocks}


def _section_title(title: str, subtitle: str | None = None) -> dict:
    text = f"*{title}*"
    if subtitle:
        text += f"\n{subtitle}"
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _subsection_label(text: str) -> dict:
    """Bold mrkdwn line in a `context` block — smaller than a section title."""
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": f"*{text}*"}]}


def _refreshed_at_blocks(epoch: int) -> list[dict]:
    """ "Last refreshed" line, rendered in the viewer's own timezone by Slack.

    Empty when the card has never been resolved, so callers can `extend` unconditionally.
    """
    if not epoch:
        return []
    return [
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"_Last refreshed <!date^{epoch}^{{date_short_pretty}} at {{time}}|just now>_",
                }
            ],
        }
    ]


def _static_select(
    *,
    action_id: str,
    placeholder: str,
    pairs: Iterable[tuple[str, str]],
    selected: str | None = None,
) -> dict[str, Any]:
    """A `static_select` built from `(value, label)` pairs.

    `selected` is honoured only when it matches one of the pairs, so a stale value from a
    cached view can't produce an `initial_option` Slack rejects.
    """
    options = [{"text": {"type": "plain_text", "text": label, "emoji": True}, "value": value} for value, label in pairs]
    element: dict[str, Any] = {
        "type": "static_select",
        "action_id": action_id,
        "placeholder": {"type": "plain_text", "text": placeholder},
        "options": options,
    }
    initial = next((o for o in options if o["value"] == selected), None)
    if initial:
        element["initial_option"] = initial
    return element


def _header_blocks() -> list[dict]:
    return [
        _section_title(
            "Welcome to PostHog! 👋",
            "Tune how @PostHog mentions get routed and answered from this Slack workspace.",
        ),
    ]


def _no_project_access_blocks() -> list[dict]:
    """Shown when the viewer can't reach any PostHog project connected to this workspace.

    Covers both halves of the same dead end — no project is connected yet, or one is but
    the viewer isn't a member of its organization — because from Slack the two are
    indistinguishable and the next step is the same page either way.
    """
    site_url = (settings.SITE_URL or "").rstrip("/")
    blocks: list[dict] = [
        _section_title(
            "🔒 No project to show yet",
            "This Slack workspace isn't connected to a PostHog project you can see, "
            "so there's nothing to set up here and @PostHog mentions won't run.",
        ),
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ("Connect a project in PostHog, or ask an admin to add you to one that's already connected."),
            },
        },
    ]
    if site_url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "url": f"{site_url}/settings/project-integrations",
                        "text": {"type": "plain_text", "text": "Connect PostHog to Slack", "emoji": True},
                        "style": "primary",
                    }
                ],
            }
        )
    return blocks


def _active_model_blocks(effective: AIPreferences, source: PreferenceSource) -> list[dict]:
    """Headline that shows which model is actually running, and why.

    With nothing set the run falls back to the Slack default, named here from the
    same constant the run resolves against so the card can't drift from it.
    """
    header = _section_title(
        "🤖 AI model",
        "Which Claude / Codex configuration handles your @PostHog mentions.",
    )
    source_blurb = {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Source: {source.label}"}]}

    if effective.is_empty:
        return [
            header,
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"Defaulting to {format_model_id(SLACK_DEFAULT_MODEL)}. Pick your own settings to override."
                    ),
                },
            },
            source_blurb,
        ]

    runtime_label = label_for(effective.runtime_adapter, RUNTIME_ADAPTER_DISPLAY_NAMES)
    return [
        header,
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                # Same phrasing as the notice a mention override posts, so the card and
                # the thread describe a run the same way.
                "text": (
                    f"Currently running "
                    f"{describe_run_model(effective.model, effective.reasoning_effort)} · {runtime_label}"
                ),
            },
        },
        source_blurb,
    ]


def _project_section_blocks(state: ProjectState, *, is_admin: bool) -> list[dict]:
    """Render the project-routing card.

    Personal dropdown for the calling user; workspace dropdown for admins.
    Each `static_select` dispatches its own action_id so a single change
    triggers a single block_actions roundtrip and an immediate republish.
    """
    options = [
        {"text": {"type": "plain_text", "text": c.label, "emoji": True}, "value": str(c.team_id)}
        for c in state.candidates
    ]

    blocks: list[dict] = [
        _section_title(
            "🧭 Project routing",
            "Which PostHog project @PostHog mentions land in. Personal picks override the workspace default.",
        ),
    ]

    if options:
        blocks.append(_subsection_label("Your default"))
        personal_select: dict[str, Any] = {
            "type": "static_select",
            "action_id": ACTION_SET_PROJECT_PERSONAL,
            "placeholder": {"type": "plain_text", "text": "Inherit workspace default"},
            "options": options,
        }
        personal_elements: list[dict[str, Any]] = [personal_select]
        if state.personal_team_id is not None and any(c.team_id == state.personal_team_id for c in state.candidates):
            personal_select["initial_option"] = next(o for o in options if o["value"] == str(state.personal_team_id))
            personal_elements.append(
                {
                    "type": "button",
                    "action_id": ACTION_RESET_PROJECT_PERSONAL,
                    "text": {"type": "plain_text", "text": "Reset to workspace default", "emoji": True},
                }
            )
        blocks.append({"type": "actions", "elements": personal_elements})

    if is_admin and options:
        blocks.append(_subsection_label("Workspace default"))
        workspace_select: dict[str, Any] = {
            "type": "static_select",
            "action_id": ACTION_SET_PROJECT_WORKSPACE,
            "placeholder": {"type": "plain_text", "text": "No workspace default"},
            "options": options,
        }
        if state.workspace_team_id is not None and any(c.team_id == state.workspace_team_id for c in state.candidates):
            workspace_select["initial_option"] = next(o for o in options if o["value"] == str(state.workspace_team_id))
        blocks.append({"type": "actions", "elements": [workspace_select]})
        # Footnote when the default points at a project the admin can't access:
        # the picker can't surface it via `initial_option` since it isn't in `options`.
        if state.workspace_team_label and not any(c.team_id == state.workspace_team_id for c in state.candidates):
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"Currently set to _{state.workspace_team_label}_ (no access)"}
                    ],
                }
            )
    elif state.workspace_team_label:
        blocks.append(_subsection_label("Workspace default"))
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"_{state.workspace_team_label}_"}})

    return blocks


def _linked_accounts_section_blocks(
    account_state: AccountState | None,
    github_state: GitHubState | None,
) -> list[dict]:
    """Render the linked-accounts card: one row per account.

    A row is a section carrying that account's status, with its button as the
    right-aligned `accessory`. Block Kit allows at most one accessory per
    section and renders `actions` blocks full width, so a row apiece is the
    only layout that keeps each button next to the account it acts on.
    The PostHog row only appears when `is_slack_app_oauth_enabled` returned
    True; the GitHub row is independent of that flag.
    """
    rows: list[dict] = []

    if account_state and account_state.enabled:
        rows.append(_account_row(_posthog_account_text(account_state), _posthog_account_button(account_state)))

    if github_state is not None:
        rows.append(_account_row(_github_account_text(github_state), _github_account_button(github_state)))

    if not rows:
        return []

    return [
        _section_title(
            "🔗 Linked accounts",
            "Who @PostHog acts as: your PostHog user, and the GitHub account it opens pull requests with.",
        ),
        *rows,
    ]


def _account_row(text: str, button: dict | None) -> dict:
    row: dict[str, Any] = {"type": "section", "text": {"type": "mrkdwn", "text": text}}
    if button:
        row["accessory"] = button
    return row


def _posthog_account_text(account_state: AccountState) -> str:
    if account_state.linked_email:
        return f"*PostHog*\n✅ Connected as {account_state.linked_email}"
    return "*PostHog*\nNot connected. Link your Slack identity so @PostHog knows it's you without matching on email."


def _posthog_account_button(account_state: AccountState) -> dict | None:
    if account_state.linked_email:
        return {
            "type": "button",
            "action_id": ACTION_UNLINK_ACCOUNT,
            "style": "danger",
            "text": {"type": "plain_text", "text": "Disconnect", "emoji": True},
            "confirm": {
                "title": {"type": "plain_text", "text": "Disconnect your PostHog account?"},
                "text": {
                    "type": "mrkdwn",
                    "text": "@PostHog will fall back to matching your Slack email against PostHog users until you link again.",
                },
                "confirm": {"type": "plain_text", "text": "Disconnect"},
                "deny": {"type": "plain_text", "text": "Cancel"},
            },
        }
    if not account_state.link_url:
        return None
    return {
        "type": "button",
        "url": account_state.link_url,
        "text": {"type": "plain_text", "text": "Connect to PostHog", "emoji": True},
        "style": "primary",
    }


def _github_account_text(github_state: GitHubState) -> str:
    if not github_state.user_resolved:
        return "*GitHub*\nLink your PostHog account first, so we know whose GitHub to look up."
    if not github_state.accounts:
        return "*GitHub*\nNot connected. Connect it so @PostHog opens pull requests as you."
    marker = "✅" if github_state.credentials_usable else "⚠️"
    listed = "\n".join(f"{marker} {account.label}" for account in github_state.accounts)
    if github_state.credentials_usable:
        return f"*GitHub*\n{listed}"
    return f"*GitHub*\n{listed}\nYour access has expired. Reconnect it, or @PostHog can't open pull requests as you."


def _github_account_button(github_state: GitHubState) -> dict | None:
    if not github_state.user_resolved or not github_state.settings_url:
        return None
    if not github_state.accounts:
        label, style = "Connect GitHub", "primary"
    elif not github_state.credentials_usable:
        label, style = "Reconnect GitHub", "primary"
    else:
        label, style = "Manage GitHub", ""
    button: dict[str, Any] = {
        "type": "button",
        "url": github_state.settings_url,
        "text": {"type": "plain_text", "text": label, "emoji": True},
    }
    if style:
        button["style"] = style
    return button


def _personal_section_blocks(user_row: SlackSettings | None) -> list[dict]:
    """Personal AI override sub-card. Always editable by the user themselves."""

    has_override = bool(user_row and user_row.runtime_adapter and user_row.model)
    summary = _row_summary(user_row) if has_override else "_No personal override — using PostHog's default._"

    actions: list[dict] = [
        {
            "type": "button",
            "action_id": ACTION_EDIT_PERSONAL,
            "text": {"type": "plain_text", "text": "Edit my settings", "emoji": True},
        }
    ]
    if has_override:
        actions.append(
            {
                "type": "button",
                "action_id": ACTION_RESET_PERSONAL,
                "style": "danger",
                "text": {"type": "plain_text", "text": "Reset to default", "emoji": True},
                "confirm": {
                    "title": {"type": "plain_text", "text": "Clear your override?"},
                    "text": {
                        "type": "mrkdwn",
                        "text": "You'll go back to PostHog's default until you set new personal preferences.",
                    },
                    "confirm": {"type": "plain_text", "text": "Reset"},
                    "deny": {"type": "plain_text", "text": "Cancel"},
                },
            }
        )

    return [
        _subsection_label("Your override"),
        {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
        {"type": "actions", "elements": actions},
    ]


UNTAGGED_FOLLOWUP_MODE_LABELS: dict[str, str] = {
    UntaggedFollowupMode.AUTO: "Pick them up automatically",
    UntaggedFollowupMode.ASK: "Ask them first",
    UntaggedFollowupMode.NEVER: "Leave them alone",
}


def _untagged_followups_section_blocks(mode: UntaggedFollowupMode) -> list[dict]:
    """Picker for how untagged replies land in the threads you started.

    Off until picked, so the card doubles as the only way to turn the behaviour
    on for your own threads. The choice covers every reply in those threads,
    including the ones you write yourself.
    """
    options = [
        {"text": {"type": "plain_text", "text": label, "emoji": True}, "value": value}
        for value, label in UNTAGGED_FOLLOWUP_MODE_LABELS.items()
    ]
    select: dict[str, Any] = {
        "type": "static_select",
        "action_id": ACTION_SET_UNTAGGED_FOLLOWUP_MODE,
        "options": options,
        "initial_option": next(o for o in options if o["value"] == mode.value),
    }
    return [
        _section_title(
            "💬 Thread follow-ups",
            "What I do with replies in a thread you started, when nobody tags @PostHog.",
        ),
        {"type": "actions", "elements": [select]},
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "Applies to every reply in those threads, yours included."}],
        },
    ]


def _footer_blocks() -> list[dict]:
    return []


_TASK_STATUS_LABELS: dict[str, str] = dict(TASKS_STATUS_OPTIONS)


def _tasks_section_blocks(state: TasksState) -> list[dict]:
    """Render the Tasks card.

    Header carries the filters + Refresh, each task renders as its own
    section block (linked title + muted meta line), and a Prev/Next strip
    paginates across pages.
    """
    blocks: list[dict] = [_section_title("🦔 Tasks", "Tasks you started by mentioning @PostHog.")]

    if state.has_any_tasks:
        blocks.append(_tasks_controls_block(state))
        blocks.extend(_refreshed_at_blocks(state.refreshed_at_epoch))

    if not state.items:
        empty_text = (
            "No tasks match the current filters."
            if state.has_any_tasks
            else "Mention @PostHog in any channel to start a task."
        )
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"_{empty_text}_"}})
        return blocks

    for index, item in enumerate(state.items):
        if index > 0:
            blocks.append({"type": "divider"})
        blocks.extend(_task_item_block(item))

    if state.total_pages > 1:
        blocks.extend(_tasks_pagination_blocks(state))

    return blocks


def _task_item_block(item: TaskItem) -> list[dict]:
    """One task row split across two Block Kit blocks for visual hierarchy.

    The title goes in a `section` (full-size mrkdwn); the optional error
    message and the status · repo · links · PR · updated meta go in a single
    `context` block underneath. Context renders text noticeably smaller and
    dimmer than section, so the supporting detail recedes while the title
    stays scannable.

    The title opens the Slack thread, because that is where the conversation the
    row summarises actually happened and it keeps the reader in Slack. The web
    and desktop views are the alternatives, so they sit in the meta line.

    Failed tasks surface the error and the meta line — error context never
    replaces the surrounding state. Newlines in the upstream error message
    collapse to spaces so a traceback doesn't blow the row open vertically.
    """
    status_label = _TASK_STATUS_LABELS.get(item.status or "", "")
    title_target = item.thread_url or item.posthog_url
    title_line = f"*<{title_target}|{item.title}>*" if title_target else f"*{item.title}*"

    meta_parts: list[str] = []
    if status_label:
        meta_parts.append(status_label)
    if item.repository:
        meta_parts.append(f"`{item.repository}`")
    if item.posthog_url:
        meta_parts.append(f"<{item.posthog_url}|View on web>")
    if item.desktop_url:
        meta_parts.append(f"<{item.desktop_url}|View on desktop>")
    if item.pr_url:
        meta_parts.append(f"<{item.pr_url}|PR>")
    if item.updated_at_label:
        meta_parts.append(f"_Updated {item.updated_at_label}_")

    sub_rows: list[str] = []
    if item.error_message:
        err = " ".join(item.error_message.strip().split())
        sub_rows.append(f"`{err}`")
    if meta_parts:
        sub_rows.append(" · ".join(meta_parts))

    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": title_line}}]
    if sub_rows:
        # Slack caps context elements at 75 chars of plain text but allows
        # much longer mrkdwn — a single mrkdwn element holds the whole stack
        # with a paragraph break between rows.
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "\n\n".join(sub_rows)}]})
    return blocks


def _tasks_pagination_blocks(state: TasksState) -> list[dict]:
    info = {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"Page *{state.page + 1}* of *{state.total_pages}* · {state.total_filtered} tasks",
            }
        ],
    }
    elements: list[dict[str, Any]] = []
    if state.has_prev:
        elements.append(
            {
                "type": "button",
                "action_id": ACTION_TASKS_PAGE_PREV,
                "value": str(state.page - 1),
                "text": {"type": "plain_text", "text": "← Previous", "emoji": True},
            }
        )
    if state.has_next:
        elements.append(
            {
                "type": "button",
                "action_id": ACTION_TASKS_PAGE_NEXT,
                "value": str(state.page + 1),
                "text": {"type": "plain_text", "text": "Next →", "emoji": True},
            }
        )
    if not elements:
        return [info]
    return [info, {"type": "actions", "elements": elements}]


def _tasks_controls_block(state: TasksState) -> dict:
    elements: list[dict[str, Any]] = []

    if state.available_repos:
        repo_options = [
            {"text": {"type": "plain_text", "text": "All repos", "emoji": True}, "value": TASKS_FILTER_ALL},
            *(
                {"text": {"type": "plain_text", "text": repo, "emoji": True}, "value": repo}
                for repo in state.available_repos
            ),
        ]
        repo_select: dict[str, Any] = {
            "type": "static_select",
            "action_id": ACTION_TASKS_FILTER_REPO,
            "placeholder": {"type": "plain_text", "text": "All repos"},
            "options": repo_options,
        }
        if state.selected_repo and any(o["value"] == state.selected_repo for o in repo_options):
            repo_select["initial_option"] = next(o for o in repo_options if o["value"] == state.selected_repo)
        elements.append(repo_select)

    status_options = [
        {"text": {"type": "plain_text", "text": label, "emoji": True}, "value": value}
        for value, label in TASKS_STATUS_OPTIONS
    ]
    status_select: dict[str, Any] = {
        "type": "static_select",
        "action_id": ACTION_TASKS_FILTER_STATUS,
        "placeholder": {"type": "plain_text", "text": "All statuses"},
        "options": status_options,
    }
    if state.selected_status and any(o["value"] == state.selected_status for o in status_options):
        status_select["initial_option"] = next(o for o in status_options if o["value"] == state.selected_status)
    elements.append(status_select)

    elements.append(
        {
            "type": "button",
            "action_id": ACTION_TASKS_REFRESH,
            "value": str(state.page),
            "text": {"type": "plain_text", "text": "Refresh", "emoji": True},
        }
    )

    return {"type": "actions", "block_id": BLOCK_TASKS_CONTROLS, "elements": elements}


# Display caps for the stats card. These live with the renderer rather than the resolver
# because they describe what gets drawn, not what the workspace did.
#
# Charts are drawn as text. Block Kit does have a native `data_visualization` block, but
# `views.publish` rejects it on the App Home surface with "Unsupported block type" — note
# that `blocks.validate` accepts it, so the schema check is not proof a surface takes it.
_STATS_MAX_BREAKDOWN_ROWS = 6
# Breakdown labels and bars share a half-width column, so both are tighter than the
# full-width sparkline row above them.
_STATS_COLUMN_LABEL_CHARS = 14
_STATS_BAR_WIDTH = 8
# Slack renders `section.fields` in two columns and rejects more than 10 cells.
_STATS_MAX_FIELDS = 10

# Eight levels of block-fill, so a sparkline reads as a shape rather than a row of dots.
_SPARK_LEVELS = "▁▂▃▄▅▆▇█"

_OUTCOME_EMOJI: dict[str, str] = {
    OUTCOME_DONE: "🦔",
    OUTCOME_FAILED: "❌",
    OUTCOME_CANCELLED: "🚫",
    OUTCOME_RUNNING: "🔄",
}


def _stats_section_blocks(state: StatsState) -> list[dict]:
    """Render the workspace-activity card: a KPI grid, two text charts, a leaderboard."""
    blocks: list[dict] = [
        _section_title(
            "📊 Workspace activity",
            "What your team shipped with @PostHog. Only workspace admins see this.",
        ),
        _stats_controls_block(state),
    ]

    if not state.has_data:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_Nobody has started a task from Slack in this window._"},
            }
        )
        return blocks

    blocks.append(_stats_headline_block(state))
    blocks.extend(
        block
        for block in (
            _stats_outcomes_block(state),
            _stats_trend_block(state),
            _stats_breakdowns_block(state),
        )
        if block
    )
    blocks.extend(_stats_footnote_blocks(state))
    return blocks


def _stats_controls_block(state: StatsState) -> dict:
    return {
        "type": "actions",
        "block_id": BLOCK_STATS_CONTROLS,
        "elements": [
            _static_select(
                action_id=ACTION_STATS_WINDOW,
                placeholder="Pick a window",
                pairs=((str(days), label) for days, label in STATS_WINDOW_OPTIONS),
                selected=str(state.window_days),
            ),
            {
                "type": "button",
                "action_id": ACTION_STATS_REFRESH,
                "value": str(state.window_days),
                "text": {"type": "plain_text", "text": "Refresh", "emoji": True},
            },
        ],
    }


def _stats_headline_block(state: StatsState) -> dict:
    merge_rate = state.merge_rate_percent
    cells = [
        ("Tasks", str(state.tasks_started)),
        ("Opened a PR", str(state.tasks_with_pr)),
        ("Merged", str(state.tasks_merged)),
        ("Merge rate", "—" if merge_rate is None else f"{merge_rate}%"),
        ("Median run", _format_duration(state.median_cycle_seconds)),
        ("People", str(state.active_people)),
    ]
    # `fields` lays out in two columns, so six KPIs cost three rows instead of the six
    # lines a stack of sections would take. Slack caps this at 10 cells.
    return {
        "type": "section",
        "fields": [{"type": "mrkdwn", "text": f"*{label}*\n{value}"} for label, value in cells[:_STATS_MAX_FIELDS]],
    }


def _format_duration(seconds: int | None) -> str:
    """Compact wall-clock label — `45s`, `12m`, `2h 5m`, `3d`."""
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours, mins = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    return f"{hours // 24}d"


def _stats_outcomes_block(state: StatsState) -> dict | None:
    """Outcome split as a muted text line — it's the least interesting of the four
    breakdowns, and giving up its chart keeps the card inside Slack's per-surface
    data-visualization budget."""
    if not state.outcomes:
        return None
    parts = [f"{_OUTCOME_EMOJI.get(s.label, '')} {s.value} {s.label.lower()}".strip() for s in state.outcomes]
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(parts)}]}


def _stats_trend_block(state: StatsState) -> dict | None:
    """PRs opened vs merged per bucket, as two sparklines on one line.

    Skipped when the window produced no PRs — a flat line of minima is noise.
    """
    buckets = state.trend
    if not buckets or not state.tasks_with_pr:
        return None

    # One shared peak so the two lines are read against each other, not each rescaled.
    peak = max(max(b.opened, b.merged) for b in buckets)
    opened = _sparkline([b.opened for b in buckets], peak)
    merged = _sparkline([b.merged for b in buckets], peak)
    span = f"{buckets[0].label} → {buckets[-1].label}"
    return {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"*PRs* `{opened}` opened · `{merged}` merged   _{span}_",
            }
        ],
    }


def _stats_breakdowns_block(state: StatsState) -> dict | None:
    """Models and people side by side.

    `section.fields` is Block Kit's only two-column layout, so the two breakdowns share
    one block instead of stacking. Each column is fenced: the counts only line up under a
    monospace font, and proportional text leaves them ragged.
    """
    columns = [column for column in (_stats_models_column(state), _stats_people_column(state)) if column]
    if not columns:
        return None
    return {"type": "section", "fields": [{"type": "mrkdwn", "text": column} for column in columns]}


def _stats_models_column(state: StatsState) -> str | None:
    """Share of runs per model, with the long tail folded into "Other"."""
    if not state.models:
        return None

    fits = len(state.models) <= _STATS_MAX_BREAKDOWN_ROWS
    head = state.models if fits else state.models[: _STATS_MAX_BREAKDOWN_ROWS - 1]
    tail = () if fits else state.models[_STATS_MAX_BREAKDOWN_ROWS - 1 :]

    rows = [(_stats_model_label(usage), usage.value) for usage in head if usage.value > 0]
    other = sum(usage.value for usage in tail)
    if other > 0:
        rows.append(("Other", other))
    if not rows:
        return None

    peak = max(value for _, value in rows)
    width = max(len(label) for label, _ in rows)
    lines = "\n".join(f"{label:<{width}} {_bar(value, peak)} {value:>3}" for label, value in rows)
    return f"*Models*\n```\n{lines}\n```"


def _stats_people_column(state: StatsState) -> str | None:
    """Leaderboard as text: who started how many, and how many of those merged."""
    people = state.people[:_STATS_MAX_BREAKDOWN_ROWS]
    if not people:
        return None

    names = [_truncate(person.name, _STATS_COLUMN_LABEL_CHARS) for person in people]
    width = max(len(name) for name in names)
    lines = "\n".join(f"{name:<{width}} {person.tasks:>3} {person.merged:>4}" for name, person in zip(names, people))
    return f"*Most active* _tasks · merged_\n```\n{lines}\n```"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _sparkline(values: list[int], peak: int) -> str:
    """Render counts as block-fill characters, scaled against `peak`."""
    if peak <= 0:
        return _SPARK_LEVELS[0] * len(values)
    top = len(_SPARK_LEVELS) - 1
    return "".join(_SPARK_LEVELS[min(top, value * top // peak)] for value in values)


def _bar(value: int, peak: int, width: int = _STATS_BAR_WIDTH) -> str:
    """Fixed-width bar. Any non-zero value keeps at least one filled cell, so a small
    count reads as present rather than absent."""
    if peak <= 0 or value <= 0:
        return "░" * width
    filled = min(width, max(1, round(value * width / peak)))
    return "█" * filled + "░" * (width - filled)


def _stats_model_label(usage: ModelUsage) -> str:
    """Display label for a model, truncated so the bar column stays aligned."""
    label = format_model_id(usage.model)
    return _truncate(label, _STATS_COLUMN_LABEL_CHARS)


def _stats_footnote_blocks(state: StatsState) -> list[dict]:
    blocks: list[dict] = []
    if state.truncated:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"_Counting the {STATS_MAX_TASKS} most recent tasks — "
                            "older activity in this window is excluded._"
                        ),
                    }
                ],
            }
        )
    blocks.extend(_refreshed_at_blocks(state.refreshed_at_epoch))
    return blocks


def _row_summary(row: SlackSettings | None) -> str:
    if not row or not row.runtime_adapter or not row.model:
        return "_(none)_"
    parts = [
        f"*Model:* {format_model_id(row.model)}",
        f"*Runtime:* {label_for(row.runtime_adapter, RUNTIME_ADAPTER_DISPLAY_NAMES)}",
    ]
    if row.reasoning_effort:
        parts.append(f"*Reasoning:* {label_for(row.reasoning_effort, REASONING_EFFORT_DISPLAY_NAMES)}")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Edit modal
# ---------------------------------------------------------------------------


def render_edit_modal(
    *,
    current: AIPreferences,
    supported_efforts: list[str] | None = None,
) -> dict:
    """Build the Block Kit modal payload for editing your personal preferences.

    `supported_efforts` lets the caller pre-compute which efforts are valid for
    the currently selected model (using
    `products.tasks.backend.temporal.process_task.utils.get_supported_reasoning_efforts`).
    When `None`, the effort block is omitted entirely; the modal re-renders via
    `block_actions` on runtime_adapter / model change to fill it in.
    """

    runtime_pairs = _runtime_adapter_options()
    runtime_options = [
        {
            "text": {"type": "plain_text", "text": label, "emoji": True},
            "value": value,
        }
        for value, label in runtime_pairs
    ]
    runtime_element: dict[str, Any] = {
        "type": "static_select",
        "action_id": MODAL_ACTION_RUNTIME_ADAPTER,
        "placeholder": {"type": "plain_text", "text": "Pick a runtime"},
        "options": runtime_options,
    }
    if current.runtime_adapter and any(v == current.runtime_adapter for v, _ in runtime_pairs):
        runtime_element["initial_option"] = next(o for o in runtime_options if o["value"] == current.runtime_adapter)
    runtime_block: dict[str, Any] = {
        "type": "input",
        "block_id": MODAL_BLOCK_RUNTIME_ADAPTER,
        "label": {"type": "plain_text", "text": "Runtime"},
        "dispatch_action": True,
        "element": runtime_element,
    }

    model_block: dict[str, Any] | None = None
    if current.runtime_adapter:
        model_options = [
            {
                "text": {"type": "plain_text", "text": label, "emoji": True},
                "value": value,
            }
            for value, label in _models_for(current.runtime_adapter)
        ]
        if model_options:
            model_element: dict[str, Any] = {
                "type": "static_select",
                "action_id": MODAL_ACTION_MODEL,
                "placeholder": {"type": "plain_text", "text": "Pick a model"},
                "options": model_options,
            }
            if current.model and any(o["value"] == current.model for o in model_options):
                model_element["initial_option"] = next(o for o in model_options if o["value"] == current.model)
            model_block = {
                "type": "input",
                "block_id": _scoped_block_id(MODAL_BLOCK_MODEL, current.runtime_adapter),
                "label": {"type": "plain_text", "text": "Model"},
                "dispatch_action": True,
                "element": model_element,
            }

    effort_block: dict[str, Any] | None = None
    if supported_efforts:
        effort_options = [
            {
                "text": {"type": "plain_text", "text": label_for(v, REASONING_EFFORT_DISPLAY_NAMES), "emoji": True},
                "value": v,
            }
            for v in supported_efforts
        ]
        effort_element: dict[str, Any] = {
            "type": "static_select",
            "action_id": MODAL_ACTION_REASONING_EFFORT,
            "placeholder": {"type": "plain_text", "text": "Pick an effort (optional)"},
            "options": effort_options,
        }
        if current.reasoning_effort and current.reasoning_effort in supported_efforts:
            effort_element["initial_option"] = next(o for o in effort_options if o["value"] == current.reasoning_effort)
        effort_block = {
            "type": "input",
            "block_id": _scoped_block_id(MODAL_BLOCK_REASONING_EFFORT, current.model),
            "label": {"type": "plain_text", "text": "Reasoning effort"},
            "optional": True,
            "element": effort_element,
        }

    blocks = [
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Pick the runtime and model that should handle PostHog Slack requests for you.",
                }
            ],
        },
        runtime_block,
    ]
    if model_block:
        blocks.append(model_block)
    if effort_block:
        blocks.append(effort_block)

    return {
        "type": "modal",
        "callback_id": EDIT_MODAL_PERSONAL_CALLBACK_ID,
        # Slack caps modal titles at 24 characters; longer ones get rejected
        # with `invalid_arguments` on `views.open`.
        "title": {"type": "plain_text", "text": "Personal AI preferences", "emoji": True},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def _scoped_block_id(prefix: str, depends_on: str | None) -> str:
    """Block id for an input whose options are derived from another input's value."""
    return f"{prefix}:{depends_on}" if depends_on else prefix


def parse_modal_submission(view: dict) -> tuple[str | None, str | None, str | None]:
    """Pull `(runtime_adapter, model, reasoning_effort)` out of a Slack view_submission payload.

    Returns `(None, None, None)` for any block the user didn't fill in. The
    caller validates the triple via `validate_ai_preferences`.
    """

    state = view.get("state", {}).get("values", {})

    runtime_adapter = _selected_value(state, MODAL_BLOCK_RUNTIME_ADAPTER, MODAL_ACTION_RUNTIME_ADAPTER)
    model = _selected_value(state, MODAL_BLOCK_MODEL, MODAL_ACTION_MODEL)
    reasoning_effort = _selected_value(state, MODAL_BLOCK_REASONING_EFFORT, MODAL_ACTION_REASONING_EFFORT)
    return runtime_adapter, model, reasoning_effort


def _selected_value(state: dict, block_prefix: str, action_id: str) -> str | None:
    """Read a select's value out of view state, matching the scoped block id it was rendered under."""
    for block_id, actions in state.items():
        if block_id != block_prefix and not block_id.startswith(f"{block_prefix}:"):
            continue
        selected = (actions.get(action_id) or {}).get("selected_option")
        if isinstance(selected, dict):
            return selected.get("value")
    return None


# ---------------------------------------------------------------------------
# Event + interactivity handlers
# ---------------------------------------------------------------------------
#
# Public entry points are re-exported from `api.py` under matching `_handle_*`
# names so the dispatchers there can call them with minimal extra wiring.
#
# Concurrency model: each Slack interactivity request is short-lived (<3s SLA),
# so all writes use plain Django ORM calls inside the request thread. The
# resolver is read at task-creation time inside the Temporal workflow, not
# here.


def handle_app_home_opened(event: dict, slack_team_id: str, *, integration: Integration) -> None:
    """Publish the Home tab for the user who just opened it.

    The caller resolves the integration through the shared region gate, so this
    region owns the workspace by the time we get here.

    Gated by the slack-app-home flag — when off, the publish is skipped so
    installs without the manifest changes (and workspaces that haven't opted
    in) keep getting Slack's default blank Home tab instead of seeing an
    interactive UI for a feature that doesn't fire downstream.
    """

    slack_user_id = event.get("user")
    if not slack_user_id:
        return

    if not is_slack_app_home_enabled(integration):
        logger.info(
            "slack_app_home_publish_skipped",
            reason="flag_off",
            slack_team_id=slack_team_id,
            slack_user_id=slack_user_id,
        )
        return

    effective = resolve_ai_preferences(integration, slack_user_id)
    user_row = _load_user_row(integration, slack_user_id)

    slack = SlackIntegration(integration)
    is_admin = _is_admin(slack, integration, slack_user_id)
    accessible = _accessible_integrations(integration, slack_user_id)
    account_state = _resolve_account_state(integration, slack_user_id)
    github_state = _resolve_github_state(integration, slack_user_id)
    project_state = _resolve_project_state(integration, slack_user_id, accessible=accessible)
    tasks_state = _resolve_tasks_state(integration, slack_user_id, accessible=accessible)
    stats_state = _resolve_stats_state(integration, accessible=accessible, is_admin=is_admin)

    view = render_home_view(
        effective=effective,
        user_row=user_row,
        is_admin=is_admin,
        account_state=account_state,
        github_state=github_state,
        project_state=project_state,
        tasks_state=tasks_state,
        stats_state=stats_state,
        untagged_followup_mode=_resolve_untagged_followup_mode_for_card(integration, slack_user_id),
        has_project_access=bool(accessible),
    )
    try:
        slack.client.views_publish(user_id=slack_user_id, view=view)
    except Exception:
        logger.exception(
            "slack_app_home_publish_failed",
            slack_user_id=slack_user_id,
            slack_team_id=slack_team_id,
        )
    else:
        logger.info(
            "slack_app_home_published",
            slack_user_id=slack_user_id,
            slack_team_id=slack_team_id,
        )


def handle_ai_preferences_block_action(payload: dict, action: dict) -> HttpResponse:
    """Dispatch a `block_actions` payload originating from the Home tab or modal."""

    action_id = action.get("action_id")
    slack_team_id = (payload.get("team") or {}).get("id", "")
    slack_user_id = (payload.get("user") or {}).get("id", "")
    trigger_id = payload.get("trigger_id")

    integration = _resolve_interaction_integration(slack_team_id, slack_user_id)
    if integration is None:
        return HttpResponse(status=200)

    # The flag is the kill-switch for the whole feature — writes and modal
    # opens must respect it too, otherwise a flipped-off flag silently
    # accumulates rows that the resolver will ignore.
    if not is_slack_app_home_enabled(integration):
        return HttpResponse(status=200)

    # The Home tab keeps no server-side view state — every payload carries the whole
    # view's inputs instead. Read them all back once so any action republishes with the
    # controls the user had dialled in, rather than resetting its neighbours' cards.
    view_state = HomeViewState.from_payload(payload)

    def republish(state: HomeViewState = view_state) -> None:
        _republish_home(integration, slack_user_id, view_state=state)

    if action_id == ACTION_EDIT_PERSONAL and trigger_id:
        _open_edit_modal(integration, slack_user_id, trigger_id=trigger_id)
        return HttpResponse(status=200)

    if action_id == ACTION_RESET_PERSONAL:
        _clear_personal_override(integration, slack_user_id)
        republish()
        return HttpResponse(status=200)

    if action_id == ACTION_SET_PROJECT_PERSONAL:
        _apply_project_pick(integration, slack_user_id=slack_user_id, action=action, scope="personal")
        republish()
        return HttpResponse(status=200)

    if action_id == ACTION_RESET_PROJECT_PERSONAL:
        _clear_project_personal(integration, slack_user_id)
        republish()
        return HttpResponse(status=200)

    if action_id == ACTION_SET_PROJECT_WORKSPACE:
        slack = SlackIntegration(integration)
        if not _is_admin(slack, integration, slack_user_id):
            _post_ephemeral_admin_only(slack, payload)
            return HttpResponse(status=200)
        _apply_project_pick(integration, slack_user_id=None, action=action, scope="workspace")
        republish()
        return HttpResponse(status=200)

    if action_id == ACTION_SET_UNTAGGED_FOLLOWUP_MODE:
        # Same gate the card is rendered behind, so a stale view can't write a
        # setting for a workspace that has since been switched off.
        if is_slack_app_untagged_thread_followups_enabled(integration, integration.integration_id):
            _apply_untagged_followup_mode_pick(integration, slack_user_id, action)
        republish()
        return HttpResponse(status=200)

    if action_id == ACTION_UNLINK_ACCOUNT:
        # Only act when the OAuth-link feature is on for this workspace —
        # otherwise the button shouldn't have been rendered, and a stale
        # cached view shouldn't be allowed to drive deletes.
        if is_slack_app_oauth_enabled(integration, integration.integration_id):
            _unlink_user_account(integration, slack_user_id)
        republish()
        return HttpResponse(status=200)

    if action_id in (
        ACTION_TASKS_FILTER_REPO,
        ACTION_TASKS_FILTER_STATUS,
        ACTION_TASKS_REFRESH,
        ACTION_TASKS_PAGE_PREV,
        ACTION_TASKS_PAGE_NEXT,
    ):
        # Filter changes snap back to page 0; Refresh / Prev / Next carry the
        # target page as the button value so the Home tab stays stateless.
        if action_id in (ACTION_TASKS_REFRESH, ACTION_TASKS_PAGE_PREV, ACTION_TASKS_PAGE_NEXT):
            try:
                page = max(0, int(action.get("value") or "0"))
            except (TypeError, ValueError):
                page = 0
        else:
            page = 0
        republish(replace(view_state, tasks_page=page))
        return HttpResponse(status=200)

    if action_id in (ACTION_STATS_WINDOW, ACTION_STATS_REFRESH):
        # The window pick already rode in on the view state; only Refresh additionally
        # needs to bypass the aggregate cache.
        republish(replace(view_state, stats_force_refresh=action_id == ACTION_STATS_REFRESH))
        return HttpResponse(status=200)

    if action_id in (MODAL_ACTION_RUNTIME_ADAPTER, MODAL_ACTION_MODEL):
        # Modal re-render: a runtime / model change updates which downstream
        # blocks (model list, effort options) are valid. Push an updated view.
        return _update_modal_after_input_change(payload, integration)

    return HttpResponse(status=200)


def handle_app_home_view_submission(payload: dict) -> HttpResponse | JsonResponse:
    """Handle the Save click on the personal edit modal."""

    view = payload.get("view", {})
    if view.get("callback_id") != EDIT_MODAL_PERSONAL_CALLBACK_ID:
        return HttpResponse(status=200)

    slack_team_id = (payload.get("team") or {}).get("id", "")
    slack_user_id = (payload.get("user") or {}).get("id", "")

    integration = _resolve_interaction_integration(slack_team_id, slack_user_id)
    if integration is None:
        return _modal_error_response("This Slack workspace is no longer connected to PostHog.")

    if not is_slack_app_home_enabled(integration):
        return _modal_error_response("AI preferences are not available for this workspace right now.")

    runtime_adapter, model, reasoning_effort = parse_modal_submission(view)

    try:
        validate_ai_preferences(runtime_adapter, model, reasoning_effort)
    except ValidationError as exc:
        return _modal_error_response(_first_validation_message(exc))

    _write_row(
        integration,
        slack_user_id=slack_user_id,
        runtime_adapter=runtime_adapter,
        model=model,
        reasoning_effort=reasoning_effort,
    )

    _republish_home(integration, slack_user_id)
    return JsonResponse({"response_action": "clear"})


# ---------------------------------------------------------------------------
# Handler internals
# ---------------------------------------------------------------------------


def _resolve_interaction_integration(slack_team_id: str, slack_user_id: str) -> Integration | None:
    """The integration the viewer's Home tab is rendered against.

    Same resolver the publish path runs, so a click is answered for the project the viewer
    was looking at. Any row of the workspace would do for fetching a bot token, but the
    rollout flag is scoped to an organization and the task list to a team, so answering
    against an arbitrary one makes the tab disagree with itself.
    """
    if not slack_team_id:
        return None
    result = load_integrations(
        slack_team_id=slack_team_id,
        kinds=list(SLACK_INTEGRATION_KINDS),
        slack_user_id=slack_user_id,
    )
    return result.resolved_or_first()


def _load_user_row(integration: Integration, slack_user_id: str) -> SlackSettings | None:
    return SlackSettings.objects.filter(
        slack_workspace_id=integration.integration_id,
        slack_user_id=slack_user_id,
    ).first()


def _row_to_settings(row: SlackSettings | None) -> AIPreferences:
    if row is None:
        return AIPreferences()
    return AIPreferences(
        runtime_adapter=row.runtime_adapter,
        model=row.model,
        reasoning_effort=row.reasoning_effort,
    )


def _is_admin(slack: SlackIntegration, integration: Integration, slack_user_id: str) -> bool:
    try:
        return is_slack_workspace_admin(slack, integration, slack_user_id)
    except Exception:
        logger.exception(
            "slack_app_home_is_admin_check_failed",
            slack_user_id=slack_user_id,
            integration_id=integration.id,
        )
        return False


def _open_edit_modal(integration: Integration, slack_user_id: str, *, trigger_id: str) -> None:
    current = _row_to_settings(_load_user_row(integration, slack_user_id))
    supported = _supported_efforts(current.runtime_adapter, current.model)
    slack = SlackIntegration(integration)

    # No models available (gateway down / misconfigured) — opening a modal
    # with an empty dropdown crashes Slack's validation. Show an info modal
    # instead so the user gets a clear message and doesn't see a silent
    # no-op click.
    if not _runtime_adapter_options():
        view = _render_unavailable_modal()
    else:
        view = render_edit_modal(current=current, supported_efforts=supported)

    try:
        slack.client.views_open(trigger_id=trigger_id, view=view)
    except Exception:
        logger.exception("slack_app_home_open_modal_failed", slack_user_id=slack_user_id)


def _render_unavailable_modal() -> dict:
    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "AI preferences", "emoji": True},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Couldn't load the model list right now. Try again in a minute — if it keeps failing, ping the team.",
                },
            }
        ],
    }


def _update_modal_after_input_change(payload: dict, integration: Integration) -> HttpResponse:
    """Re-render the modal in response to a runtime_adapter or model change.

    Reads the in-flight state from `payload["view"]`, drops whatever the change
    invalidated, derives the efforts the surviving model supports, and pushes the
    updated view via `views.update`. Nothing is persisted here — the user still has
    to Save to commit.
    """

    view = payload.get("view", {})
    if view.get("callback_id") != EDIT_MODAL_PERSONAL_CALLBACK_ID:
        return HttpResponse(status=200)

    current = _drop_invalidated_selections(*parse_modal_submission(view))
    supported = _supported_efforts(current.runtime_adapter, current.model)

    updated_view = render_edit_modal(current=current, supported_efforts=supported)

    slack = SlackIntegration(integration)
    try:
        slack.client.views_update(view_id=view.get("id"), hash=view.get("hash"), view=updated_view)
    except Exception:
        logger.exception("slack_app_home_modal_update_failed")
    return HttpResponse(status=200)


def _drop_invalidated_selections(
    runtime_adapter: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> AIPreferences:
    """Keep only the parts of an in-flight selection the current runtime still allows.

    Switching runtime orphans the model picked under the old one, and that orphans the
    effort. The scoped block ids stop Slack handing those back on the next interaction;
    this stops the view we render from the same payload showing them in the meantime.
    """
    if model and model not in {value for value, _ in _models_for(runtime_adapter or "")}:
        model = None
    if reasoning_effort and reasoning_effort not in (_supported_efforts(runtime_adapter, model) or ()):
        reasoning_effort = None
    return AIPreferences(runtime_adapter=runtime_adapter, model=model, reasoning_effort=reasoning_effort)


def _supported_efforts(runtime_adapter: str | None, model: str | None) -> list[str] | None:
    if not runtime_adapter or not model:
        return None
    from products.tasks.backend.facade.run_config import get_supported_reasoning_efforts

    return [e.value for e in get_supported_reasoning_efforts(runtime_adapter, model)] or None


def _write_row(
    integration: Integration,
    *,
    slack_user_id: str,
    runtime_adapter: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> None:
    """Upsert a SlackSettings row with the given AI preferences.

    `default_integration` is left untouched on existing rows so saving AI
    preferences doesn't accidentally overwrite the user's routing pick.
    """

    payload = build_ai_preferences_payload(runtime_adapter, model, reasoning_effort)
    SlackSettings.objects.update_or_create(
        slack_workspace_id=integration.integration_id,
        slack_user_id=slack_user_id,
        defaults={"ai_preferences": payload or None},
    )


def _resolve_untagged_followup_mode_for_card(
    integration: Integration, slack_user_id: str
) -> UntaggedFollowupMode | None:
    """The picker's current value, or ``None`` to leave the card out entirely.

    The setting only means anything where untagged follow-ups run at all, so the
    card lives behind the same flag as the behaviour it configures.
    """
    if not is_slack_app_untagged_thread_followups_enabled(integration, integration.integration_id):
        return None
    return resolve_untagged_followup_mode(integration, slack_user_id)


def _apply_untagged_followup_mode_pick(integration: Integration, slack_user_id: str, action: dict) -> None:
    """Persist the picked mode. An unrecognised value is ignored rather than stored."""

    picked = (action.get("selected_option") or {}).get("value")
    if picked not in UntaggedFollowupMode.values:
        return
    SlackSettings.objects.update_or_create(
        slack_workspace_id=integration.integration_id,
        slack_user_id=slack_user_id,
        defaults={"untagged_followup_mode": picked},
    )


def _clear_personal_override(integration: Integration, slack_user_id: str) -> None:
    """Clear just the AI fields on the user's row. Leaves routing alone."""

    SlackSettings.objects.filter(
        slack_workspace_id=integration.integration_id,
        slack_user_id=slack_user_id,
    ).update(ai_preferences=None)


def _clear_project_personal(integration: Integration, slack_user_id: str) -> None:
    """Clear the personal routing override; drop the row once it holds nothing else."""

    row = SlackSettings.objects.filter(
        slack_workspace_id=integration.integration_id,
        slack_user_id=slack_user_id,
    ).first()
    if row is None:
        return
    if not row.ai_preferences and not row.untagged_followup_mode:
        row.delete()
        return
    row.default_integration = None
    row.save(update_fields=["default_integration", "updated_at"])


def _republish_home(
    integration: Integration,
    slack_user_id: str,
    *,
    view_state: HomeViewState | None = None,
) -> None:
    view_state = view_state or HomeViewState()
    user_row = _load_user_row(integration, slack_user_id)
    effective = resolve_ai_preferences(integration, slack_user_id)
    slack = SlackIntegration(integration)
    is_admin = _is_admin(slack, integration, slack_user_id)
    accessible = _accessible_integrations(integration, slack_user_id)
    account_state = _resolve_account_state(integration, slack_user_id)
    github_state = _resolve_github_state(integration, slack_user_id)
    project_state = _resolve_project_state(integration, slack_user_id, accessible=accessible)
    tasks_state = _resolve_tasks_state(
        integration,
        slack_user_id,
        accessible=accessible,
        selected_repo=view_state.selected_repo,
        selected_status=view_state.selected_status,
        page=view_state.tasks_page,
    )
    stats_state = _resolve_stats_state(
        integration,
        accessible=accessible,
        is_admin=is_admin,
        window_days=view_state.stats_window_days,
        force_refresh=view_state.stats_force_refresh,
    )
    view = render_home_view(
        effective=effective,
        user_row=user_row,
        is_admin=is_admin,
        account_state=account_state,
        github_state=github_state,
        project_state=project_state,
        tasks_state=tasks_state,
        stats_state=stats_state,
        untagged_followup_mode=_resolve_untagged_followup_mode_for_card(integration, slack_user_id),
        has_project_access=bool(accessible),
    )
    try:
        slack.client.views_publish(user_id=slack_user_id, view=view)
    except Exception:
        logger.exception("slack_app_home_republish_failed")
        return
    # Carries the controls the click resolved to, so a report of "the filter does
    # nothing" can be told apart from a click that never reached us at all.
    logger.info(
        "slack_app_home_republished",
        slack_user_id=slack_user_id,
        slack_team_id=integration.integration_id,
        slack_app_home_tasks_page=tasks_state.page,
        slack_app_home_tasks_total_pages=tasks_state.total_pages,
        slack_app_home_tasks_shown=len(tasks_state.items),
        slack_app_home_selected_repo=view_state.selected_repo,
        slack_app_home_selected_status=view_state.selected_status,
        slack_app_home_stats_window_days=view_state.stats_window_days,
    )


_TASKS_PAGE_SIZE = 10
_TASKS_MAX_TOTAL = 100
# Tasks fall off the Home tab once their Slack thread has been quiet for two
# weeks. Keeps the list tight and avoids dragging in stale work that the user
# already moved past in the PostHog UI.
_TASKS_RECENT_WINDOW = timedelta(days=14)


def _resolve_tasks_state(
    integration: Integration,
    slack_user_id: str,
    *,
    accessible: list[Integration],
    selected_repo: str | None = None,
    selected_status: str | None = None,
    page: int = 0,
) -> TasksState:
    """List tasks the calling Slack user started via @PostHog mentions.

    Scoped to teams the user can access in the workspace. The `Task` ORM
    query lives here rather than behind a new facade method because the
    slack-specific authorization model (mentioning_slack_user_id +
    accessible-team scoping) does not generalise.
    """

    from django.utils import timezone as django_timezone

    from products.slack_app.backend.models import SlackThreadTaskMapping
    from products.slack_app.backend.services.slack_messages import viewer_has_code_access
    from products.tasks.backend.facade import api as tasks_facade

    slack_team_id = integration.integration_id
    # `-updated_at` advances on each thread reply, so "latest activity"
    # surfaces first. We don't expose a sort control today.
    recent_cutoff = django_timezone.now() - _TASKS_RECENT_WINDOW
    mappings = list(
        SlackThreadTaskMapping.objects.filter(
            slack_workspace_id=slack_team_id,
            mentioning_slack_user_id=slack_user_id,
            updated_at__gte=recent_cutoff,
        )
        .order_by("-updated_at")
        .values("task_id", "team_id", "channel", "thread_ts", "updated_at")[:_TASKS_MAX_TOTAL]
    )
    if not mappings:
        return TasksState()

    accessible_team_ids = {c.team_id for c in accessible}
    if not accessible_team_ids:
        return TasksState()

    task_ids_ordered = [m["task_id"] for m in mappings]
    tasks = tasks_facade.get_tasks_by_ids(task_ids_ordered, accessible_team_ids)
    if not tasks:
        return TasksState()

    runs_by_task = tasks_facade.get_latest_run_by_task([t.id for t in tasks])
    pr_urls_by_task = tasks_facade.get_latest_pr_url_by_task([t.id for t in tasks])
    tasks_by_id = {str(t.id): t for t in tasks}
    mapping_by_task = {str(m["task_id"]): m for m in mappings}

    site_url = (settings.SITE_URL or "").rstrip("/")
    # Both task links answer to the reader, the same check the reply footer's links use.
    # The desktop one goes through the `/code/task` web bridge, which opens the app when
    # installed and offers a download when not, so it rides alongside the web one.
    can_open_code_links = viewer_has_code_access(integration, slack_user_id)
    now = django_timezone.now()
    all_items: list[TaskItem] = []
    repos_seen: list[str] = []
    seen_repo_set: set[str] = set()
    for task_id in task_ids_ordered:
        t = tasks_by_id.get(str(task_id))
        if t is None:
            continue
        run = runs_by_task.get(str(t.id))
        mapping: Mapping[str, Any] = mapping_by_task.get(str(t.id), {})
        posthog_url = desktop_url = None
        if can_open_code_links:
            posthog_url = f"{site_url}/project/{t.team_id}/tasks/{t.id}"
            desktop_url = f"{site_url}/code/task/{t.id}"
        all_items.append(
            TaskItem(
                title=t.title,
                posthog_url=posthog_url,
                desktop_url=desktop_url,
                status=run.status if run else None,
                repository=t.repository,
                pr_url=pr_urls_by_task.get(str(t.id)),
                thread_url=_slack_thread_permalink(mapping.get("channel", ""), mapping.get("thread_ts", "")),
                updated_at_label=_format_relative(mapping.get("updated_at"), now=now),
                error_message=run.error_message if run else None,
            )
        )
        if t.repository and t.repository not in seen_repo_set:
            repos_seen.append(t.repository)
            seen_repo_set.add(t.repository)

    # `selected_*` is None when the user has never picked, and `TASKS_FILTER_ALL`
    # when they explicitly reset back to "All …". Either is a no-op filter.
    effective_repo = selected_repo if selected_repo and selected_repo != TASKS_FILTER_ALL else None
    effective_status = selected_status if selected_status and selected_status != TASKS_FILTER_ALL else None
    filtered = [
        item
        for item in all_items
        if (effective_repo is None or item.repository == effective_repo)
        and (effective_status is None or item.status == effective_status)
    ]

    total_filtered = len(filtered)
    total_pages = max(1, (total_filtered + _TASKS_PAGE_SIZE - 1) // _TASKS_PAGE_SIZE) if total_filtered else 0
    safe_page = max(0, min(page, total_pages - 1)) if total_pages else 0
    start = safe_page * _TASKS_PAGE_SIZE
    end = start + _TASKS_PAGE_SIZE
    page_items = filtered[start:end]

    return TasksState(
        items=tuple(page_items),
        available_repos=tuple(repos_seen),
        selected_repo=selected_repo,
        selected_status=selected_status,
        has_any_tasks=True,
        page=safe_page,
        total_pages=total_pages,
        total_filtered=total_filtered,
        refreshed_at_epoch=int(now.timestamp()),
    )


def _slack_thread_permalink(channel: str, thread_ts: str) -> str | None:
    """Build the Slack web URL for a thread root.

    Format is the canonical `https://slack.com/archives/{channel}/p{ts_no_dot}`
    Slack rewrites server-side to land the viewer in the right workspace.
    """
    if not channel or not thread_ts:
        return None
    return f"https://slack.com/archives/{channel}/p{thread_ts.replace('.', '')}"


def _format_relative(when: datetime | None, *, now: datetime) -> str:
    """Render a `datetime` as a compact relative label (`5m ago`, `Jun 20`).

    `when` is None-tolerant so a missing mapping field never crashes the
    Home tab; the column just shows an em-dash via the table's empty fallback.
    """
    if when is None:
        return ""
    delta = now - when
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    if seconds < 7 * 86400:
        return f"{seconds // 86400}d ago"
    return when.strftime("%b %d")


def _resolve_account_state(integration: Integration, slack_user_id: str) -> AccountState:
    slack_team_id = integration.integration_id
    if not is_slack_app_oauth_enabled(integration, slack_team_id):
        return AccountState(enabled=False)

    candidate_org_ids = _workspace_org_ids(slack_team_id)
    linked_user = find_linked_posthog_user(
        slack_user_id=slack_user_id,
        slack_team_id=slack_team_id,
        candidate_org_ids=candidate_org_ids,
    )
    if linked_user is not None:
        return AccountState(enabled=True, linked_email=linked_user.email)

    try:
        link_url = build_invite_url(
            slack_user_id=slack_user_id,
            slack_team_id=slack_team_id,
            posthog_team_id=integration.team_id,
            channel=None,
            thread_ts=None,
        )
    except Exception:
        logger.exception(
            "slack_app_home_build_invite_url_failed",
            slack_user_id=slack_user_id,
            slack_team_id=slack_team_id,
        )
        link_url = None
    return AccountState(enabled=True, linked_email=None, link_url=link_url)


def _resolve_home_user(integration: Integration, slack_user_id: str) -> User | None:
    """Identify the PostHog user behind this Slack identity.

    Mirrors the event-path cascade in `resolve_posthog_user_from_event`: the
    OAuth link wins, otherwise we match the cached Slack profile email against
    members of the organizations connected to this workspace. Deactivated
    users count as no match on both paths, so an offboarded account can't be
    reached through a Slack identity that still maps to it. Reading the
    profile cache instead of calling `users.info` keeps the Home render free
    of a Slack API roundtrip.
    """
    slack_team_id = integration.integration_id
    candidate_org_ids = _workspace_org_ids(slack_team_id)
    if not candidate_org_ids:
        return None

    if is_slack_app_oauth_enabled(integration, slack_team_id):
        linked_user = find_linked_posthog_user(
            slack_user_id=slack_user_id,
            slack_team_id=slack_team_id,
            candidate_org_ids=candidate_org_ids,
        )
        if linked_user is not None:
            return linked_user if linked_user.is_active else None

    profile = SlackUserProfileCache.objects.filter(integration_id=integration.id, slack_user_id=slack_user_id).first()
    if profile is None or not profile.email:
        return None
    membership = (
        OrganizationMembership.objects.filter(
            organization_id__in=candidate_org_ids,
            user__email__iexact=profile.email,
            user__is_active=True,
        )
        .select_related("user")
        .first()
    )
    return membership.user if membership else None


def _resolve_github_state(integration: Integration, slack_user_id: str) -> GitHubState:
    """List the personal GitHub installations of the user opening the Home tab.

    Usability comes from the tasks facade, the same judgment
    `should_block_task_for_missing_user_github` gates on, so the card and the
    task flow never disagree about whether a connection works.

    Connecting GitHub needs an authenticated PostHog session, so the button
    deep-links to Personal integrations settings — the same target the
    in-thread "Connect GitHub" prompt uses.
    """
    from products.slack_app.backend.services.slack_messages import personal_integrations_url
    from products.tasks.backend.facade import api as tasks_facade

    settings_url = personal_integrations_url(integration.team_id)
    try:
        user = _resolve_home_user(integration, slack_user_id)
        if user is None:
            return GitHubState(user_resolved=False, settings_url=settings_url)
        rows = UserIntegration.objects.filter(
            user=user,
            kind=UserIntegration.IntegrationKind.GITHUB,
        ).order_by("created_at")
        accounts = tuple(_github_account_from_row(row) for row in rows)
        credentials_usable = bool(accounts) and tasks_facade.user_has_usable_personal_github(user.id)
    except Exception:
        logger.exception(
            "slack_app_home_resolve_github_state_failed",
            slack_user_id=slack_user_id,
            integration_id=integration.id,
        )
        return GitHubState(user_resolved=False, settings_url=settings_url)
    return GitHubState(
        user_resolved=True,
        accounts=accounts,
        credentials_usable=credentials_usable,
        settings_url=settings_url,
    )


def _github_account_from_row(row: UserIntegration) -> GitHubAccount:
    config = row.config or {}
    github_user = config.get("github_user")
    account = config.get("account")
    return GitHubAccount(
        installation_id=row.integration_id,
        login=github_user.get("login") if isinstance(github_user, dict) else None,
        account_name=account.get("name") if isinstance(account, dict) else None,
    )


def _workspace_integrations(slack_team_id: str) -> list[Integration]:
    """Every PostHog project this Slack workspace is connected to."""
    return list(
        Integration.objects.filter(kind="slack", integration_id=slack_team_id)
        .select_related("team", "team__organization")
        .order_by("id")
    )


def _accessible_integrations(integration: Integration, slack_user_id: str) -> list[Integration]:
    """The workspace's projects this Slack user can actually reach in PostHog.

    Resolved once per publish and handed to every card: it costs a `UserPermissions`
    build plus three queries, and all three cards want the same answer. It is also the
    authorization boundary for the whole tab, so it should have exactly one definition.
    """
    return _filter_accessible_integrations(
        integration, slack_user_id, _workspace_integrations(integration.integration_id)
    )


def _resolve_stats_state(
    integration: Integration,
    *,
    accessible: list[Integration],
    is_admin: bool,
    window_days: int = DEFAULT_STATS_WINDOW_DAYS,
    force_refresh: bool = False,
) -> StatsState | None:
    """Workspace activity aggregates, or None when the card shouldn't render at all.

    Admin-only, and rides the same `slack-app-home` gate as the rest of the tab — the
    callers already returned early when that flag is off.

    Scoped to the projects this admin can already reach: being a Slack workspace admin
    says nothing about PostHog org membership, so the card must never widen what its
    viewer could otherwise see.
    """
    if not is_admin:
        return None

    accessible_team_ids = {c.team_id for c in accessible}
    if not accessible_team_ids:
        return None

    try:
        return build_stats_state(
            slack_workspace_id=integration.integration_id,
            accessible_team_ids=accessible_team_ids,
            window_days=window_days,
            force_refresh=force_refresh,
        )
    except Exception:
        # The card is supplementary — a failed aggregate shouldn't cost the user their
        # settings and task list too.
        logger.exception("slack_app_home_stats_resolve_failed", integration_id=integration.id)
        return None


def _resolve_project_state(
    integration: Integration, slack_user_id: str, *, accessible: list[Integration]
) -> ProjectState:
    candidates = _workspace_integrations(integration.integration_id)
    if not candidates:
        return ProjectState()

    user_row = (
        SlackSettings.objects.filter(
            slack_workspace_id=integration.integration_id,
            slack_user_id=slack_user_id,
        )
        .select_related("default_integration")
        .first()
    )
    workspace_row = (
        SlackSettings.objects.filter(
            slack_workspace_id=integration.integration_id,
            slack_user_id__isnull=True,
        )
        .select_related("default_integration")
        .first()
    )

    def project_label(c: Integration) -> str:
        return f"{c.team.organization.name} · {c.team.name}"

    # Look up the workspace default's label against the full candidate list,
    # not `accessible`, so a default pointing at an inaccessible project still
    # surfaces in the UI.
    # Guard on the FK object (not the *_id field) so mypy narrows
    # `default_integration` from `Integration | None` to `Integration`.
    workspace_team_id = (
        workspace_row.default_integration.team_id if workspace_row and workspace_row.default_integration else None
    )
    workspace_team_label: str | None = None
    if workspace_team_id is not None:
        workspace_team_label = next((project_label(c) for c in candidates if c.team_id == workspace_team_id), None)

    return ProjectState(
        candidates=tuple(ProjectChoice(team_id=c.team_id, label=project_label(c)) for c in accessible),
        personal_team_id=(user_row.default_integration.team_id if user_row and user_row.default_integration else None),
        workspace_team_id=workspace_team_id,
        workspace_team_label=workspace_team_label,
    )


def _filter_accessible_integrations(
    integration: Integration, slack_user_id: str, candidates: list[Integration]
) -> list[Integration]:
    # Falls back to the full candidate list when we can't identify the user —
    # hiding the picker would mean an unidentified user has no way to change
    # their routing at all.
    profile = SlackUserProfileCache.objects.filter(integration_id=integration.id, slack_user_id=slack_user_id).first()
    if profile is None or not profile.email:
        return candidates
    membership = (
        OrganizationMembership.objects.filter(
            user__email=profile.email,
            organization_id__in={c.team.organization_id for c in candidates},
        )
        .select_related("user")
        .first()
    )
    if membership is None:
        return candidates
    permissions = UserPermissions(user=membership.user)
    return [c for c in candidates if permissions.team(c.team).effective_membership_level is not None]


def _apply_project_pick(
    integration: Integration,
    *,
    slack_user_id: str | None,
    action: dict,
    scope: str,
) -> None:
    selected = (action.get("selected_option") or {}).get("value")
    if not selected:
        return
    try:
        team_id = int(selected)
    except (TypeError, ValueError):
        return
    target = (
        Integration.objects.filter(kind="slack", integration_id=integration.integration_id, team_id=team_id)
        .select_related("team", "team__organization")
        .first()
    )
    if target is None:
        return
    # Personal-scope picks are user-driven, so re-check that the picker
    # actually had this team in its accessible set. The renderer hides
    # inaccessible options but a hand-crafted block_actions can still arrive
    # with any team_id in the workspace.
    if scope == "personal" and slack_user_id:
        accessible = _filter_accessible_integrations(integration, slack_user_id, [target] if target else [])
        if not accessible:
            return
    SlackSettings.objects.update_or_create(
        slack_workspace_id=integration.integration_id,
        slack_user_id=slack_user_id,
        defaults={"default_integration": target},
    )
    logger.info(
        "slack_app_home_project_default_set",
        slack_workspace_id=integration.integration_id,
        slack_user_id=slack_user_id,
        scope=scope,
        team_id=team_id,
    )


def _unlink_user_account(integration: Integration, slack_user_id: str) -> None:
    # Scope across every org connected to this Slack workspace, not just the
    # one for the integration the click happened to land on — for multi-org
    # workspaces, the linked row may live in any of them.
    slack_team_id = integration.integration_id
    candidate_user_ids = set(
        OrganizationMembership.objects.filter(
            organization_id__in=_workspace_org_ids(slack_team_id),
        ).values_list("user_id", flat=True)
    )
    if not candidate_user_ids:
        return
    UserIntegration.objects.filter(
        kind=UserIntegration.IntegrationKind.SLACK,
        integration_id=slack_user_id,
        config__slack_team_id=slack_team_id,
        user_id__in=candidate_user_ids,
    ).delete()


def _workspace_org_ids(slack_team_id: str) -> set:
    return set(
        Integration.objects.filter(kind="slack", integration_id=slack_team_id).values_list(
            "team__organization_id", flat=True
        )
    )


def _modal_error_response(message: str) -> JsonResponse:
    """Slack-format response: keep the modal open and surface an error.

    Slack expects `response_action=errors` with a `block_id`-keyed errors map.
    We attach the error to the runtime block so it's visible without scrolling.
    """

    return JsonResponse(
        {
            "response_action": "errors",
            "errors": {MODAL_BLOCK_RUNTIME_ADAPTER: message[:200]},
        }
    )


def _first_validation_message(exc: Exception) -> str:
    messages = getattr(exc, "messages", None)
    if messages:
        return messages[0]
    return "Settings could not be saved."


def _post_ephemeral_admin_only(slack: SlackIntegration, payload: dict) -> None:
    """Tell a non-admin that workspace edits are gated.

    The Home tab Edit button is already rendered admin-only, so reaching this
    path means the user came in via a stale view or a hand-crafted payload.
    App Home block_actions payloads carry no `channel`/`container.channel_id`
    (the Home tab isn't channel-bound), so fall back to a direct message to
    the user — `chat_postMessage(channel=<user id>)` opens the IM if it does
    not already exist.
    """
    slack_user_id = (payload.get("user") or {}).get("id", "")
    if not slack_user_id:
        return
    text = "Only Slack workspace admins can change the PostHog workspace default."
    channel = (payload.get("channel") or {}).get("id") or (payload.get("container") or {}).get("channel_id")
    try:
        if channel:
            slack.client.chat_postEphemeral(channel=channel, user=slack_user_id, text=text)
        else:
            slack.client.chat_postMessage(channel=slack_user_id, text=text)
    except Exception:
        logger.warning("slack_app_home_admin_only_notice_failed")
