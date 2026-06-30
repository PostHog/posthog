"""App Home tab renderer + interactivity handlers for the PostHog Slack app.

The Home tab is the user-facing control panel for the integration. This
first iteration carries two cards — project routing (which PostHog project
@PostHog mentions land in) and account linking (Sign-in-with-Slack). The
layout leaves room for additional cards as they come online.

All Block Kit payloads are built as plain dicts here so they can be
unit-tested without any Slack client. The event/interactivity handlers in
`products/slack_app/backend/api.py` are the ones that actually call
`views.publish` / `views.open`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.http import HttpResponse

import structlog

from posthog.models.integration import Integration, SlackIntegration
from posthog.models.organization import OrganizationMembership
from posthog.models.user_integration import UserIntegration
from posthog.user_permissions import UserPermissions

from products.slack_app.backend.feature_flags import is_slack_app_home_enabled, slack_oauth_link_enabled
from products.slack_app.backend.models import SlackSettings, SlackUserProfileCache
from products.slack_app.backend.services.slack_user_info import is_slack_workspace_admin
from products.slack_app.backend.services.slack_user_oauth import build_invite_url, find_linked_posthog_user

logger = structlog.get_logger(__name__)

HOME_CALLBACK_ID = "slack_app_home"

ACTION_UNLINK_ACCOUNT = "slack_app_home:unlink_account"
ACTION_SET_PROJECT_PERSONAL = "slack_app_home:set_project_personal"
ACTION_SET_PROJECT_WORKSPACE = "slack_app_home:set_project_workspace"
ACTION_RESET_PROJECT_PERSONAL = "slack_app_home:reset_project_personal"


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
    """Inputs the renderer needs to draw the optional account-link card."""

    enabled: bool = False
    linked_email: str | None = None
    link_url: str | None = None


def render_home_view(
    *,
    is_admin: bool,
    account_state: AccountState | None = None,
    project_state: ProjectState | None = None,
) -> dict:
    """Render the Block Kit payload for `views.publish` on the App Home tab."""

    blocks: list[dict] = []
    blocks.extend(_header_blocks())

    if project_state and project_state.has_anything_to_show:
        blocks.append({"type": "divider"})
        blocks.extend(_project_section_blocks(project_state, is_admin=is_admin))

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


def _footer_blocks() -> list[dict]:
    return [
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "Mention @PostHog in any channel to get started."},
            ],
        }
    ]


# ---------------------------------------------------------------------------
# Event + interactivity handlers
# ---------------------------------------------------------------------------


def handle_app_home_opened(event: dict, slack_team_id: str) -> None:
    """Publish the Home tab for the user who just opened it.

    Gated by the slack-app-home flag — when off the publish is skipped so
    installs without the manifest changes (and workspaces that haven't
    opted in) keep getting Slack's default blank Home tab.
    """

    slack_user_id = event.get("user")
    if not slack_user_id:
        return

    integration = _get_slack_integration(slack_team_id)
    if integration is None:
        return

    if not is_slack_app_home_enabled(integration):
        return

    slack = SlackIntegration(integration)
    is_admin = _is_admin(slack, integration, slack_user_id)
    account_state = _resolve_account_state(integration, slack_user_id)
    project_state = _resolve_project_state(integration, slack_user_id)

    view = render_home_view(
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


def handle_home_block_action(payload: dict, action: dict) -> HttpResponse:
    """Dispatch a `block_actions` payload originating from the Home tab."""

    action_id = action.get("action_id")
    slack_team_id = (payload.get("team") or {}).get("id", "")
    slack_user_id = (payload.get("user") or {}).get("id", "")

    integration = _get_slack_integration(slack_team_id)
    if integration is None:
        return HttpResponse(status=200)

    # The flag is the kill-switch for the whole feature — writes must
    # respect it too, otherwise a flipped-off flag silently accumulates
    # rows that the resolver will ignore.
    if not is_slack_app_home_enabled(integration):
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

    return HttpResponse(status=200)


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


def _clear_project_personal(integration: Integration, slack_user_id: str) -> None:
    """Clear the personal routing override."""
    SlackSettings.objects.filter(
        slack_workspace_id=integration.integration_id,
        slack_user_id=slack_user_id,
    ).delete()


def _republish_home(integration: Integration, slack_user_id: str) -> None:
    slack = SlackIntegration(integration)
    is_admin = _is_admin(slack, integration, slack_user_id)
    account_state = _resolve_account_state(integration, slack_user_id)
    project_state = _resolve_project_state(integration, slack_user_id)
    view = render_home_view(
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
    workspace_team_id = (
        workspace_row.default_integration.team_id if workspace_row and workspace_row.default_integration_id else None
    )
    workspace_team_label: str | None = None
    if workspace_team_id is not None:
        workspace_team_label = next((_label(c) for c in candidates if c.team_id == workspace_team_id), None)

    return ProjectState(
        candidates=tuple(ProjectChoice(team_id=c.team_id, label=_label(c)) for c in accessible),
        personal_team_id=(
            user_row.default_integration.team_id if user_row and user_row.default_integration_id else None
        ),
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


def _post_ephemeral_admin_only(slack: SlackIntegration, payload: dict) -> None:
    """Tell a non-admin that workspace edits are gated."""
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
