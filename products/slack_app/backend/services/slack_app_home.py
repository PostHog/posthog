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

from dataclasses import dataclass
from typing import Any, Literal

from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse

import structlog

from posthog.models.integration import Integration, SlackIntegration
from posthog.models.organization import OrganizationMembership
from posthog.models.user_integration import UserIntegration
from posthog.user_permissions import UserPermissions

from products.slack_app.backend.feature_flags import is_slack_app_home_enabled, slack_oauth_link_enabled
from products.slack_app.backend.models import SlackSettings, SlackUserProfileCache
from products.slack_app.backend.services.slack_settings import (
    AIPreferences,
    build_ai_preferences_payload,
    resolve_ai_preferences,
    validate_ai_preferences,
)
from products.slack_app.backend.services.slack_user_info import is_slack_workspace_admin
from products.slack_app.backend.services.slack_user_oauth import build_invite_url, find_linked_posthog_user

logger = structlog.get_logger(__name__)

# Block / action / callback identifiers. Centralised so the interactivity
# handler in api.py and the renderers here cannot drift apart.
HOME_CALLBACK_ID = "slack_app_home"

ACTION_EDIT_PERSONAL = "slack_app_home:edit_personal"
ACTION_EDIT_WORKSPACE = "slack_app_home:edit_workspace"
ACTION_RESET_PERSONAL = "slack_app_home:reset_personal"
ACTION_UNLINK_ACCOUNT = "slack_app_home:unlink_account"
ACTION_SET_PROJECT_PERSONAL = "slack_app_home:set_project_personal"
ACTION_SET_PROJECT_WORKSPACE = "slack_app_home:set_project_workspace"
ACTION_RESET_PROJECT_PERSONAL = "slack_app_home:reset_project_personal"

EDIT_MODAL_PERSONAL_CALLBACK_ID = "slack_app_ai_prefs:personal"
EDIT_MODAL_WORKSPACE_CALLBACK_ID = "slack_app_ai_prefs:workspace"

MODAL_ACTION_RUNTIME_ADAPTER = "ai_prefs:runtime_adapter"
MODAL_ACTION_MODEL = "ai_prefs:model"
MODAL_ACTION_REASONING_EFFORT = "ai_prefs:reasoning_effort"

MODAL_BLOCK_RUNTIME_ADAPTER = "block_runtime_adapter"
MODAL_BLOCK_MODEL = "block_model"
MODAL_BLOCK_REASONING_EFFORT = "block_reasoning_effort"

EditScope = Literal["personal", "workspace"]

# Runtime + effort labels are UI strings with no tasks-product equivalent.
# Model display labels are computed from the model id on the fly via
# `_format_model_id` so we never have to hand-maintain a model→label map.
RUNTIME_ADAPTER_DISPLAY_NAMES: dict[str, str] = {
    "claude": "Claude (Anthropic)",
    "codex": "Codex (OpenAI)",
}

REASONING_EFFORT_DISPLAY_NAMES: dict[str, str] = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "xhigh": "Extra high",
    "max": "Max",
}

# Gateway `owned_by` → tasks RuntimeAdapter value. Other providers
# (bedrock, vertex…) get dropped from the picker.
_PROVIDER_TO_RUNTIME_ADAPTER: dict[str, str] = {
    "anthropic": "claude",
    "openai": "codex",
}

_PROVIDER_PREFIXES = ("anthropic/", "openai/")


def _format_model_id(model_id: str, *, owned_by: str) -> str:
    """OpenAI ids stay lowercase; Claude ids become `Claude Opus 4.8` etc."""
    clean = model_id
    for prefix in _PROVIDER_PREFIXES:
        if clean.startswith(prefix):
            clean = clean[len(prefix) :]
            break
    if owned_by == "openai":
        return clean.lower()
    import re as _re

    # Collapse `4-8` into `4.8` so version components survive the dash split.
    clean = _re.sub(r"(\d)-(\d)", r"\1.\2", clean)
    return " ".join(
        word if _re.fullmatch(r"[0-9.]+", word) else word[:1].upper() + word[1:].lower()
        for word in _re.split(r"[-_]", clean)
    )


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
    """Build the picker tree from the live LLM-gateway model list.

    Models come from `slack_app` product on the gateway (cached). Per-model
    effort support and adapter grouping come from the tasks facade. Display
    labels are local UI strings.

    Adapters with no available models are omitted entirely.
    """
    from products.slack_app.backend.services.llm_models import list_slack_app_models
    from products.tasks.backend.facade.run_config import get_supported_reasoning_efforts

    gateway_models = list_slack_app_models()

    by_adapter: dict[str, list[PickerModel]] = {}
    for gm in gateway_models:
        adapter_value = _PROVIDER_TO_RUNTIME_ADAPTER.get(gm.owned_by)
        if adapter_value is None:
            continue
        efforts = tuple(
            PickerEffort(value=e.value, label=REASONING_EFFORT_DISPLAY_NAMES.get(e.value) or e.value)
            for e in get_supported_reasoning_efforts(adapter_value, gm.id)
        )
        by_adapter.setdefault(adapter_value, []).append(
            PickerModel(value=gm.id, label=_format_model_id(gm.id, owned_by=gm.owned_by), supported_efforts=efforts)
        )

    return tuple(
        PickerAdapter(
            value=adapter_value,
            label=RUNTIME_ADAPTER_DISPLAY_NAMES.get(adapter_value) or adapter_value,
            models=tuple(models),
        )
        for adapter_value, models in by_adapter.items()
    )


def _label(value: str | None, mapping: dict[str, str]) -> str:
    if not value:
        return "—"
    return mapping.get(value, value)


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
    """Which row contributed the effective `(runtime_adapter, model)` pair.

    Used to render the "Source: …" line on the active-model card so the
    precedence (personal → workspace → unset) is visible at a glance.
    """

    label: str

    @classmethod
    def personal(cls) -> PreferenceSource:
        return cls(label="Your personal override")

    @classmethod
    def workspace(cls) -> PreferenceSource:
        return cls(label="Workspace default")

    @classmethod
    def unset(cls) -> PreferenceSource:
        return cls(label="System default")


def resolve_source(
    user_row: SlackSettings | None,
    workspace_row: SlackSettings | None,
) -> PreferenceSource:
    """Return where the effective pair came from.

    Mirrors the same atomic-pair rule the resolver uses: a row only "sources"
    the pair when both halves are set on it.
    """
    if user_row and user_row.runtime_adapter and user_row.model:
        return PreferenceSource.personal()
    if workspace_row and workspace_row.runtime_adapter and workspace_row.model:
        return PreferenceSource.workspace()
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
class AccountState:
    """Inputs the renderer needs to draw the optional account-link card.

    Carries no business logic — the handler computes whether the flag is on
    and whether the Slack user is currently linked, and hands the result
    here so the renderer stays a pure function.
    """

    enabled: bool = False
    linked_email: str | None = None
    link_url: str | None = None


def render_home_view(
    *,
    effective: AIPreferences,
    user_row: SlackSettings | None,
    workspace_row: SlackSettings | None,
    is_admin: bool,
    account_state: AccountState | None = None,
    project_state: ProjectState | None = None,
) -> dict:
    """Render the Block Kit payload for `views.publish` on the App Home tab."""

    source = resolve_source(user_row, workspace_row)
    blocks: list[dict] = []

    blocks.extend(_header_blocks())

    # Section 1 — project routing. Personal pick on top; admins get an
    # editable workspace default below, others see it as read-only context.
    if project_state and project_state.has_anything_to_show:
        blocks.append({"type": "divider"})
        blocks.extend(_project_section_blocks(project_state, is_admin=is_admin))

    # Section 2 — AI model settings: which model handles those mentions.
    # Headline shows the effective triple (and its source); personal /
    # workspace controls underneath mirror the project routing layout.
    blocks.append({"type": "divider"})
    blocks.extend(_active_model_blocks(effective, source))
    blocks.extend(_personal_section_blocks(user_row))
    blocks.extend(_workspace_section_blocks(workspace_row, is_admin=is_admin))

    # Section 3 — account linking: tucked at the end because it's a setup
    # step you do once, not a knob you tune. Flag-gated.
    if account_state and account_state.enabled:
        blocks.append({"type": "divider"})
        blocks.extend(_account_section_blocks(account_state))

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


def _header_blocks() -> list[dict]:
    return [
        _section_title(
            "Welcome to PostHog! 👋",
            "Tune how @PostHog mentions get routed and answered from this Slack workspace.",
        ),
    ]


def _active_model_blocks(effective: AIPreferences, source: PreferenceSource) -> list[dict]:
    """Headline that shows which model is actually running, and why.

    When nothing is set the agent-server picks its own default — we don't
    know which one, so don't lie. Just say so and let the user override.
    """
    header = _section_title(
        "AI model",
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
                    "text": "Inheriting PostHog Code's default — pick personal or workspace settings to override.",
                },
            },
            source_blurb,
        ]

    runtime_label = _label(effective.runtime_adapter, RUNTIME_ADAPTER_DISPLAY_NAMES)
    model_label = _format_model_id(effective.model, owned_by="") if effective.model else "—"
    effort_part = (
        f" · Reasoning: *{_label(effective.reasoning_effort, REASONING_EFFORT_DISPLAY_NAMES)}*"
        if effective.reasoning_effort
        else ""
    )
    return [
        header,
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Currently running *{model_label}* · {runtime_label}{effort_part}",
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
            "Project routing",
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


def _account_section_blocks(account_state: AccountState) -> list[dict]:
    """Render the Sign-in-with-Slack account card.

    Visible only when `slack_oauth_link_enabled` returned True. Linked
    state mirrors the Claude home pattern: ✅ + email, with a danger-styled
    Disconnect button at the bottom.
    """
    if account_state.linked_email:
        return [
            _section_title("Linked PostHog account"),
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✅ Connected as *{account_state.linked_email}*",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
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
                ],
            },
        ]
    blocks: list[dict] = [
        _section_title(
            "Connect your PostHog account",
            "Link your Slack identity to a PostHog user so @PostHog knows it's you without falling back to email matching.",
        ),
    ]
    if account_state.link_url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "url": account_state.link_url,
                        "text": {"type": "plain_text", "text": "Connect to PostHog", "emoji": True},
                        "style": "primary",
                    }
                ],
            }
        )
    return blocks


def _personal_section_blocks(user_row: SlackSettings | None) -> list[dict]:
    """Personal AI override sub-card. Always editable by the user themselves."""

    has_override = bool(user_row and user_row.runtime_adapter and user_row.model)
    summary = _row_summary(user_row) if has_override else "_No personal override — inheriting the workspace default._"

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
                "text": {"type": "plain_text", "text": "Reset to workspace default", "emoji": True},
                "confirm": {
                    "title": {"type": "plain_text", "text": "Clear your override?"},
                    "text": {
                        "type": "mrkdwn",
                        "text": "You'll inherit the workspace default until you set new personal preferences.",
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


def _workspace_section_blocks(
    workspace_row: SlackSettings | None,
    *,
    is_admin: bool,
) -> list[dict]:
    """Workspace AI default sub-card — admin-only; non-admins don't see it."""

    if not is_admin:
        return []

    has_default = bool(workspace_row and workspace_row.runtime_adapter and workspace_row.model)
    summary = (
        _row_summary(workspace_row)
        if has_default
        else "_No workspace default set — falls back to PostHog's system default._"
    )
    blocks: list[dict] = [
        _subsection_label("Workspace default"),
        {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": ACTION_EDIT_WORKSPACE,
                    "text": {"type": "plain_text", "text": "Edit workspace default", "emoji": True},
                }
            ],
        },
    ]
    return blocks


def _footer_blocks() -> list[dict]:
    return []


def _row_summary(row: SlackSettings | None) -> str:
    if not row or not row.runtime_adapter or not row.model:
        return "_(none)_"
    owned_by = "openai" if row.runtime_adapter == "codex" else "anthropic"
    parts = [
        f"*Model:* {_format_model_id(row.model, owned_by=owned_by)}",
        f"*Runtime:* {_label(row.runtime_adapter, RUNTIME_ADAPTER_DISPLAY_NAMES)}",
    ]
    if row.reasoning_effort:
        parts.append(f"*Reasoning:* {_label(row.reasoning_effort, REASONING_EFFORT_DISPLAY_NAMES)}")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Edit modal
# ---------------------------------------------------------------------------


def render_edit_modal(
    *,
    scope: EditScope,
    current: AIPreferences,
    supported_efforts: list[str] | None = None,
) -> dict:
    """Build the Block Kit modal payload for personal or workspace editing.

    `supported_efforts` lets the caller pre-compute which efforts are valid for
    the currently selected model (using
    `products.tasks.backend.temporal.process_task.utils.get_supported_reasoning_efforts`).
    When `None`, the effort block is omitted entirely; the modal re-renders via
    `block_actions` on runtime_adapter / model change to fill it in.
    """

    callback_id = EDIT_MODAL_PERSONAL_CALLBACK_ID if scope == "personal" else EDIT_MODAL_WORKSPACE_CALLBACK_ID
    # Slack caps modal titles at 24 characters; longer ones get rejected with
    # `invalid_arguments` on `views.open`.
    title = "Personal AI preferences" if scope == "personal" else "Workspace AI preferences"

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
                "block_id": MODAL_BLOCK_MODEL,
                "label": {"type": "plain_text", "text": "Model"},
                "dispatch_action": True,
                "element": model_element,
            }

    effort_block: dict[str, Any] | None = None
    if supported_efforts:
        effort_options = [
            {
                "text": {"type": "plain_text", "text": _label(v, REASONING_EFFORT_DISPLAY_NAMES), "emoji": True},
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
            "block_id": MODAL_BLOCK_REASONING_EFFORT,
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
                    "text": (
                        "Pick the runtime and model that should handle PostHog Slack requests for you."
                        if scope == "personal"
                        else "Set the default runtime and model for everyone in this Slack workspace."
                    ),
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
        "callback_id": callback_id,
        "title": {"type": "plain_text", "text": title, "emoji": True},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


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


def _selected_value(state: dict, block_id: str, action_id: str) -> str | None:
    block = state.get(block_id, {})
    action = block.get(action_id, {})
    selected = action.get("selected_option")
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


def handle_app_home_opened(event: dict, slack_team_id: str) -> None:
    """Publish the Home tab for the user who just opened it.

    Gated by the slack-app-home flag — when off, the publish is skipped so
    installs without the manifest changes (and workspaces that haven't opted
    in) keep getting Slack's default blank Home tab instead of seeing an
    interactive UI for a feature that doesn't fire downstream.
    """

    slack_user_id = event.get("user")
    if not slack_user_id:
        return

    integration = _get_slack_integration(slack_team_id)
    if integration is None:
        return

    if not is_slack_app_home_enabled(integration):
        return

    effective = resolve_ai_preferences(integration, slack_user_id)
    user_row, workspace_row = _load_rows(integration, slack_user_id)

    slack = SlackIntegration(integration)
    is_admin = _is_admin(slack, integration, slack_user_id)
    account_state = _resolve_account_state(integration, slack_user_id)
    project_state = _resolve_project_state(integration, slack_user_id)

    view = render_home_view(
        effective=effective,
        user_row=user_row,
        workspace_row=workspace_row,
        is_admin=is_admin,
        account_state=account_state,
        project_state=project_state,
    )
    try:
        slack.client.views_publish(user_id=slack_user_id, view=view)
    except Exception:
        logger.exception(
            "slack_app_home_publish_failed",
            slack_user_id=slack_user_id,
            slack_team_id=slack_team_id,
        )


def handle_ai_preferences_block_action(payload: dict, action: dict) -> HttpResponse:
    """Dispatch a `block_actions` payload originating from the Home tab or modal."""

    action_id = action.get("action_id")
    slack_team_id = (payload.get("team") or {}).get("id", "")
    slack_user_id = (payload.get("user") or {}).get("id", "")
    trigger_id = payload.get("trigger_id")

    integration = _get_slack_integration(slack_team_id)
    if integration is None:
        return HttpResponse(status=200)

    # The flag is the kill-switch for the whole feature — writes and modal
    # opens must respect it too, otherwise a flipped-off flag silently
    # accumulates rows that the resolver will ignore.
    if not is_slack_app_home_enabled(integration):
        return HttpResponse(status=200)

    if action_id == ACTION_EDIT_PERSONAL and trigger_id:
        _open_edit_modal(integration, slack_user_id, scope="personal", trigger_id=trigger_id)
        return HttpResponse(status=200)

    if action_id == ACTION_EDIT_WORKSPACE and trigger_id:
        slack = SlackIntegration(integration)
        if not _is_admin(slack, integration, slack_user_id):
            _post_ephemeral_admin_only(slack, payload)
            return HttpResponse(status=200)
        _open_edit_modal(integration, slack_user_id, scope="workspace", trigger_id=trigger_id)
        return HttpResponse(status=200)

    if action_id == ACTION_RESET_PERSONAL:
        _clear_personal_override(integration, slack_user_id)
        _republish_home(integration, slack_user_id)
        return HttpResponse(status=200)

    if action_id == ACTION_SET_PROJECT_PERSONAL:
        _apply_project_pick(integration, slack_user_id=slack_user_id, action=action, scope="personal")
        _republish_home(integration, slack_user_id)
        return HttpResponse(status=200)

    if action_id == ACTION_RESET_PROJECT_PERSONAL:
        _clear_project_personal(integration, slack_user_id)
        _republish_home(integration, slack_user_id)
        return HttpResponse(status=200)

    if action_id == ACTION_SET_PROJECT_WORKSPACE:
        slack = SlackIntegration(integration)
        if not _is_admin(slack, integration, slack_user_id):
            _post_ephemeral_admin_only(slack, payload)
            return HttpResponse(status=200)
        _apply_project_pick(integration, slack_user_id=None, action=action, scope="workspace")
        _republish_home(integration, slack_user_id)
        return HttpResponse(status=200)

    if action_id == ACTION_UNLINK_ACCOUNT:
        # Only act when the OAuth-link feature is on for this workspace —
        # otherwise the button shouldn't have been rendered, and a stale
        # cached view shouldn't be allowed to drive deletes.
        if slack_oauth_link_enabled(integration, integration.integration_id):
            _unlink_user_account(integration, slack_user_id)
        _republish_home(integration, slack_user_id)
        return HttpResponse(status=200)

    if action_id in (MODAL_ACTION_RUNTIME_ADAPTER, MODAL_ACTION_MODEL):
        # Modal re-render: a runtime / model change updates which downstream
        # blocks (model list, effort options) are valid. Push an updated view.
        return _update_modal_after_input_change(payload)

    return HttpResponse(status=200)


def handle_app_home_view_submission(payload: dict) -> HttpResponse | JsonResponse:
    """Handle the Save click on the personal or workspace edit modal."""

    view = payload.get("view", {})
    callback_id = view.get("callback_id")
    if callback_id not in (EDIT_MODAL_PERSONAL_CALLBACK_ID, EDIT_MODAL_WORKSPACE_CALLBACK_ID):
        return HttpResponse(status=200)

    slack_team_id = (payload.get("team") or {}).get("id", "")
    slack_user_id = (payload.get("user") or {}).get("id", "")

    integration = _get_slack_integration(slack_team_id)
    if integration is None:
        return _modal_error_response("This Slack workspace is no longer connected to PostHog.")

    if not is_slack_app_home_enabled(integration):
        return _modal_error_response("AI preferences are not available for this workspace right now.")

    runtime_adapter, model, reasoning_effort = parse_modal_submission(view)

    try:
        validate_ai_preferences(runtime_adapter, model, reasoning_effort)
    except ValidationError as exc:
        return _modal_error_response(_first_validation_message(exc))

    if callback_id == EDIT_MODAL_PERSONAL_CALLBACK_ID:
        _write_row(
            integration,
            slack_user_id=slack_user_id,
            runtime_adapter=runtime_adapter,
            model=model,
            reasoning_effort=reasoning_effort,
        )
    else:
        slack = SlackIntegration(integration)
        if not _is_admin(slack, integration, slack_user_id):
            return _modal_error_response("Only Slack workspace admins can change the workspace default.")
        _write_row(
            integration,
            slack_user_id=None,
            runtime_adapter=runtime_adapter,
            model=model,
            reasoning_effort=reasoning_effort,
        )

    _republish_home(integration, slack_user_id)
    return JsonResponse({"response_action": "clear"})


# ---------------------------------------------------------------------------
# Handler internals
# ---------------------------------------------------------------------------


def _get_slack_integration(slack_team_id: str) -> Integration | None:

    if not slack_team_id:
        return None
    return (
        Integration.objects.select_related("team", "team__organization")
        .filter(kind="slack", integration_id=slack_team_id)
        .first()
    )


def _load_rows(integration: Integration, slack_user_id: str) -> tuple[SlackSettings | None, SlackSettings | None]:

    user_row = SlackSettings.objects.filter(
        slack_workspace_id=integration.integration_id,
        slack_user_id=slack_user_id,
    ).first()
    workspace_row = SlackSettings.objects.filter(
        slack_workspace_id=integration.integration_id,
        slack_user_id__isnull=True,
    ).first()
    return user_row, workspace_row


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


def _open_edit_modal(integration: Integration, slack_user_id: str, *, scope: EditScope, trigger_id: str) -> None:
    user_row, workspace_row = _load_rows(integration, slack_user_id)
    current = _row_to_settings(user_row if scope == "personal" else workspace_row)
    supported = _supported_efforts(current.runtime_adapter, current.model)
    slack = SlackIntegration(integration)

    # No models available (gateway down / misconfigured) — opening a modal
    # with an empty dropdown crashes Slack's validation. Show an info modal
    # instead so the user gets a clear message and doesn't see a silent
    # no-op click.
    if not _runtime_adapter_options():
        view = _render_unavailable_modal()
    else:
        view = render_edit_modal(scope=scope, current=current, supported_efforts=supported)

    try:
        slack.client.views_open(trigger_id=trigger_id, view=view)
    except Exception:
        logger.exception(
            "slack_app_home_open_modal_failed",
            slack_user_id=slack_user_id,
            scope=scope,
        )


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


def _update_modal_after_input_change(payload: dict) -> HttpResponse:
    """Re-render the modal in response to a runtime_adapter or model change.

    Reads the in-flight state from `payload["view"]`, derives the new supported
    efforts (changes when the model changes), and pushes the updated view via
    `views.update`. Nothing is persisted here — the user still has to Save to
    commit.
    """

    view = payload.get("view", {})
    callback_id = view.get("callback_id")
    if callback_id not in (EDIT_MODAL_PERSONAL_CALLBACK_ID, EDIT_MODAL_WORKSPACE_CALLBACK_ID):
        return HttpResponse(status=200)

    runtime_adapter, model, reasoning_effort = parse_modal_submission(view)
    current = AIPreferences(runtime_adapter=runtime_adapter, model=model, reasoning_effort=reasoning_effort)
    supported = _supported_efforts(runtime_adapter, model)

    scope: EditScope = "personal" if callback_id == EDIT_MODAL_PERSONAL_CALLBACK_ID else "workspace"
    updated_view = render_edit_modal(scope=scope, current=current, supported_efforts=supported)

    slack_team_id = (payload.get("team") or {}).get("id", "")
    integration = _get_slack_integration(slack_team_id)
    if integration is None:
        return HttpResponse(status=200)

    slack = SlackIntegration(integration)
    try:
        slack.client.views_update(view_id=view.get("id"), hash=view.get("hash"), view=updated_view)
    except Exception:
        logger.exception("slack_app_home_modal_update_failed")
    return HttpResponse(status=200)


def _supported_efforts(runtime_adapter: str | None, model: str | None) -> list[str] | None:
    if not runtime_adapter or not model:
        return None
    from products.tasks.backend.facade.run_config import get_supported_reasoning_efforts

    return [e.value for e in get_supported_reasoning_efforts(runtime_adapter, model)] or None


def _write_row(
    integration: Integration,
    *,
    slack_user_id: str | None,
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


def _clear_personal_override(integration: Integration, slack_user_id: str) -> None:
    """Clear just the AI fields on the user's row. Leaves routing alone."""

    SlackSettings.objects.filter(
        slack_workspace_id=integration.integration_id,
        slack_user_id=slack_user_id,
    ).update(ai_preferences=None)


def _clear_project_personal(integration: Integration, slack_user_id: str) -> None:
    """Clear the personal routing override; drop the row if no AI overrides remain."""

    row = SlackSettings.objects.filter(
        slack_workspace_id=integration.integration_id,
        slack_user_id=slack_user_id,
    ).first()
    if row is None:
        return
    if not row.ai_preferences:
        row.delete()
        return
    row.default_integration = None
    row.save(update_fields=["default_integration", "updated_at"])


def _republish_home(integration: Integration, slack_user_id: str) -> None:
    user_row, workspace_row = _load_rows(integration, slack_user_id)
    effective = resolve_ai_preferences(integration, slack_user_id)
    slack = SlackIntegration(integration)
    is_admin = _is_admin(slack, integration, slack_user_id)
    account_state = _resolve_account_state(integration, slack_user_id)
    project_state = _resolve_project_state(integration, slack_user_id)
    view = render_home_view(
        effective=effective,
        user_row=user_row,
        workspace_row=workspace_row,
        is_admin=is_admin,
        account_state=account_state,
        project_state=project_state,
    )
    try:
        slack.client.views_publish(user_id=slack_user_id, view=view)
    except Exception:
        logger.exception("slack_app_home_republish_failed")


def _resolve_account_state(integration: Integration, slack_user_id: str) -> AccountState:
    slack_team_id = integration.integration_id
    if not slack_oauth_link_enabled(integration, slack_team_id):
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


def _resolve_project_state(integration: Integration, slack_user_id: str) -> ProjectState:
    candidates = list(
        Integration.objects.filter(kind="slack", integration_id=integration.integration_id)
        .select_related("team", "team__organization")
        .order_by("id")
    )
    if not candidates:
        return ProjectState()

    accessible = _filter_accessible_integrations(integration, slack_user_id, candidates)

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

    def _label(c: Integration) -> str:
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
        workspace_team_label = next((_label(c) for c in candidates if c.team_id == workspace_team_id), None)

    return ProjectState(
        candidates=tuple(ProjectChoice(team_id=c.team_id, label=_label(c)) for c in accessible),
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
