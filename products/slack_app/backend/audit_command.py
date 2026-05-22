"""
Staff-initiated audit slash command (`/ph-audit <project_id> <skill>`).

V0 scope (this PR): receive the slash command, gate on PostHog staff identity,
allowlist a small set of read-only audit skills, post an in-channel confirm
message, and on confirm write a "Team" activity log entry plus a public
disclosure message. The actual agent dispatch (scoped read-only token + skill
bundle + Temporal workflow) is intentionally a follow-up — see the TODO in
`_dispatch_audit_run`.

Region/local-gate wiring lives in `api.py` next to the existing
picker/terminate hint extractors so the interactivity handler stays in one
place.
"""

from dataclasses import dataclass

from django.core import signing
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.integration import Integration, SlackIntegration, SlackIntegrationError, validate_slack_request
from posthog.models.team.team import Team
from posthog.models.user import User

logger = structlog.get_logger(__name__)

AUDIT_CONFIRM_ACTION_ID = "posthog_code_audit_confirm"
AUDIT_CANCEL_ACTION_ID = "posthog_code_audit_cancel"
AUDIT_CONFIRM_TOKEN_SALT = "posthog_code_audit_confirm"
AUDIT_CONFIRM_TOKEN_MAX_AGE_SECONDS = 300

# V0 read-only audit skills. Every entry here must be a non-mutating
# investigation/audit skill — adding write-capable skills here is a security
# decision that needs a separate review.
AUDIT_SKILLS: frozenset[str] = frozenset(
    {
        "auditing-experiments-flags",
        "auditing-warehouse-data-health",
        "cleaning-up-stale-feature-flags",  # the *finding* half; cleanup itself is a separate flow
        "diagnosing-failed-warehouse-syncs",
        "diagnosing-missing-recordings",
        "diagnosing-sdk-health",
        "diagnosing-stacktrace-symbolication",
    }
)


@dataclass(frozen=True)
class AuditCommandArgs:
    project_id: int
    skill: str


class AuditCommandError(Exception):
    """Raised when the slash command text fails parsing or validation."""


def _parse_command_text(text: str) -> AuditCommandArgs:
    parts = (text or "").strip().split()
    if len(parts) != 2:
        raise AuditCommandError(
            f"Usage: `/ph-audit <project_id> <skill>`. Available skills: {', '.join(sorted(AUDIT_SKILLS))}."
        )
    try:
        project_id = int(parts[0])
    except ValueError:
        raise AuditCommandError(f"`{parts[0]}` isn't a valid project ID — expected an integer.")
    skill = parts[1]
    if skill not in AUDIT_SKILLS:
        raise AuditCommandError(
            f"`{skill}` isn't an allowed audit skill. Pick one of: {', '.join(sorted(AUDIT_SKILLS))}."
        )
    return AuditCommandArgs(project_id=project_id, skill=skill)


def _resolve_posthog_staff_user(slack_user_id: str, integration: Integration) -> User | None:
    """Resolve a Slack user to a PostHog `User`, but only if they're staff.

    Returns None if we can't resolve the email, the user isn't in PostHog,
    or they're not flagged `is_staff`. This is the *only* gate on who can
    initiate an audit against a customer project in v0.
    """
    from products.slack_app.backend.api import resolve_slack_user

    slack = SlackIntegration(integration)
    # post_feedback=False — we'll surface our own error via `response_url`
    ctx = resolve_slack_user(slack, integration, slack_user_id, channel="", thread_ts="", post_feedback=False)
    if ctx is None:
        return None
    if not ctx.user.is_staff:
        return None
    return ctx.user


def _ephemeral(text: str) -> JsonResponse:
    return JsonResponse({"response_type": "ephemeral", "text": text})


def _build_confirm_blocks(
    *,
    integration_id: int,
    slack_user_id: str,
    team: Team,
    staff_user: User,
    skill: str,
    confirm_token: str,
) -> list[dict]:
    org_name = team.organization.name if team.organization_id else "(unknown org)"
    return [
        {
            "type": "section",
            "block_id": f"posthog_code_audit:{integration_id}:{slack_user_id}",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":mag: *PostHog Code* wants to run the read-only `{skill}` audit "
                    f"against project *{team.name}* (org *{org_name}*, project id `{team.id}`).\n"
                    f"Initiated by *{staff_user.email}*. "
                    f"Activity will be logged to this project's audit trail."
                ),
            },
        },
        {
            "type": "actions",
            "block_id": f"posthog_code_audit_actions:{integration_id}:{slack_user_id}",
            "elements": [
                {
                    "type": "button",
                    "action_id": AUDIT_CONFIRM_ACTION_ID,
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "Run audit"},
                    "value": confirm_token,
                },
                {
                    "type": "button",
                    "action_id": AUDIT_CANCEL_ACTION_ID,
                    "text": {"type": "plain_text", "text": "Cancel"},
                    "value": confirm_token,
                },
            ],
        },
    ]


@csrf_exempt
def posthog_code_slash_command_handler(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        posthog_code_config = SlackIntegration.posthog_code_slack_config()
        validate_slack_request(request, posthog_code_config["SLACK_POSTHOG_CODE_SIGNING_SECRET"])
    except SlackIntegrationError as e:
        logger.warning("posthog_code_slash_command_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    command = request.POST.get("command", "")
    if command != "/ph-audit":
        return _ephemeral(f"Unknown command `{command}`.")

    slack_workspace_id = request.POST.get("team_id", "")
    slack_user_id = request.POST.get("user_id", "")
    channel_id = request.POST.get("channel_id", "")
    text = request.POST.get("text", "")

    try:
        args = _parse_command_text(text)
    except AuditCommandError as e:
        return _ephemeral(str(e))

    # nosemgrep: idor-lookup-without-team — Slack webhook endpoint, no team
    # context in the session; lookup is keyed by (kind, workspace id).
    integration = Integration.objects.filter(
        kind="slack-posthog-code",
        integration_id=slack_workspace_id,
    ).first()
    if integration is None:
        return _ephemeral("This workspace doesn't have a PostHog Code Slack integration installed.")

    staff_user = _resolve_posthog_staff_user(slack_user_id, integration)
    if staff_user is None:
        return _ephemeral(
            "This command is restricted to PostHog staff. "
            "If that's you and you're seeing this, make sure your Slack email matches your PostHog account."
        )

    team = Team.objects.filter(pk=args.project_id).select_related("organization").first()
    if team is None:
        return _ephemeral(f"Project `{args.project_id}` not found.")

    confirm_token = signing.dumps(
        {
            "integration_id": integration.id,
            "team_id": team.id,
            "skill": args.skill,
            "staff_user_id": staff_user.id,
            "slack_user_id": slack_user_id,
            "channel": channel_id,
        },
        salt=AUDIT_CONFIRM_TOKEN_SALT,
    )

    blocks = _build_confirm_blocks(
        integration_id=integration.id,
        slack_user_id=slack_user_id,
        team=team,
        staff_user=staff_user,
        skill=args.skill,
        confirm_token=confirm_token,
    )

    # Ephemeral so a fat-fingered project ID doesn't leak the wrong customer's
    # name into the public channel until staff actually confirms.
    return JsonResponse({"response_type": "ephemeral", "blocks": blocks})


def extract_audit_hints(payload: dict) -> tuple[int | None, str | None]:
    """Return `(integration_id, slack_user_id)` for an audit confirm/cancel action.

    Mirrors `_extract_picker_hints` / `_extract_terminate_hints` in api.py so
    the interactivity handler's local-region gate works the same way.
    """
    actions = payload.get("actions", [])
    action = next(
        (a for a in actions if a.get("action_id") in (AUDIT_CONFIRM_ACTION_ID, AUDIT_CANCEL_ACTION_ID)),
        None,
    )
    if not action:
        return None, None

    block_id = action.get("block_id", "")
    if not block_id.startswith("posthog_code_audit_actions:"):
        return None, None

    parts = block_id.split(":")
    if len(parts) < 3:
        return None, None
    try:
        integration_id = int(parts[1])
    except ValueError:
        return None, None
    return integration_id, parts[2]


def _decode_confirm_token(raw: str) -> dict | None:
    try:
        return signing.loads(raw, salt=AUDIT_CONFIRM_TOKEN_SALT, max_age=AUDIT_CONFIRM_TOKEN_MAX_AGE_SECONDS)
    except signing.BadSignature:
        return None


def _log_audit_run_started(*, team: Team, staff_user: User, skill: str) -> None:
    log_activity(
        organization_id=team.organization_id,
        team_id=team.id,
        user=staff_user,
        item_id=team.id,
        scope="Team",
        activity="external_audit_started",
        detail=Detail(name=team.name, type=skill),
        was_impersonated=False,
    )


def _dispatch_audit_run(*, team: Team, staff_user: User, skill: str, channel: str) -> None:
    """V1 will: mint a scoped read-only token for `team`, then start a Temporal
    workflow that runs the agent with the `skill` bundle and streams results
    back to `channel`. For v0 this is a no-op so we can ship the confirm/log
    surface without committing to the auth-layer changes (PAT TTL / ephemeral
    token model) those need.
    """
    logger.info(
        "posthog_code_audit_dispatch_stub",
        team_id=team.id,
        staff_user_id=staff_user.id,
        skill=skill,
        channel=channel,
    )


def handle_audit_confirm(payload: dict) -> HttpResponse:
    actions = payload.get("actions", [])
    action = next((a for a in actions if a.get("action_id") == AUDIT_CONFIRM_ACTION_ID), None)
    if action is None:
        return HttpResponse(status=200)

    token = _decode_confirm_token(action.get("value", ""))
    if token is None:
        return _respond_via_response_url(
            payload, "This audit confirmation expired. Re-run `/ph-audit` to get a fresh one."
        )

    clicking_slack_user = payload.get("user", {}).get("id", "")
    if clicking_slack_user != token.get("slack_user_id"):
        return _respond_via_response_url(
            payload, "Only the staff member who ran the slash command can confirm the audit."
        )

    team = Team.objects.filter(pk=token["team_id"]).select_related("organization").first()
    staff_user = User.objects.filter(pk=token["staff_user_id"]).first()
    if team is None or staff_user is None or not staff_user.is_staff:
        return _respond_via_response_url(payload, "Couldn't resolve the audit target — aborting.")

    _log_audit_run_started(team=team, staff_user=staff_user, skill=token["skill"])
    _dispatch_audit_run(team=team, staff_user=staff_user, skill=token["skill"], channel=token.get("channel", ""))

    return JsonResponse(
        {
            "replace_original": True,
            "response_type": "in_channel",
            "text": (
                f":mag: PostHog is running a read-only `{token['skill']}` audit on project "
                f"*{team.name}*. Initiated by *{staff_user.email}*. "
                f"Logged to the project's audit trail."
            ),
        }
    )


def handle_audit_cancel(payload: dict) -> HttpResponse:
    return JsonResponse({"replace_original": True, "text": "Audit cancelled."})


def _respond_via_response_url(payload: dict, text: str) -> JsonResponse:
    return JsonResponse({"replace_original": True, "response_type": "ephemeral", "text": text})
