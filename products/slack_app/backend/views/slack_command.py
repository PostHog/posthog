"""Slack slash command entry point.

Handles ``POST /slack/command-callback`` — the webhook Slack hits when a user
runs ``/posthog ...`` in a channel or DM. The vocabulary mirrors the
``@PostHog <command>`` mention path (``help``, ``rules ...``, ``project ...``);
free-text task creation stays on the mention path because slash commands lack
the thread context the task workflow depends on.

Slack imposes a hard 3-second response budget on slash commands — a slow first
response surfaces to the user as ``operation_timeout``. Cheap validation and
region routing stay inline; the slow work (user resolution, dispatch, posting
back to Slack) runs in the same durable Temporal command workflow the mention
path uses. We synthesise a mention-shaped ``event`` from the slash payload, hand
it to ``_start_command_workflow``, and ack Slack immediately with a 200.
"""

from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.integration import SlackIntegration, SlackIntegrationError, validate_slack_request

from products.slack_app.backend.api import (
    ROUTE_NO_INTEGRATION,
    ROUTE_PROXY_FAILED,
    SLACK_INTEGRATION_KIND,
    _start_command_workflow,
    cross_region_routing_enabled,
    is_us_host,
    other_region_domain,
    parse_rules_command,
    resolve_region_or_terminal_route,
    was_proxied,
)
from products.slack_app.backend.services.integration_resolver import load_integrations

logger = structlog.get_logger(__name__)

SLASH_COMMAND_NAME = "/posthog"


@csrf_exempt
def slack_app_command_handler(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        slack_config = SlackIntegration.slack_config()
        validate_slack_request(request, slack_config["SLACK_APP_SIGNING_SECRET"])
    except SlackIntegrationError as e:
        logger.warning("slack_app_slash_command_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    # Slack replays the POST verbatim when an ack fails to reach it; short-circuit
    # so a retry can't start a second command workflow for the same click.
    retry_num = request.headers.get("X-Slack-Retry-Num")
    if retry_num:
        logger.info("slack_app_slash_command_retry", retry_num=retry_num)
        return HttpResponse(status=200)

    payload = request.POST
    slack_team_id = payload.get("team_id", "")
    slack_user_id = payload.get("user_id", "")
    channel_id = payload.get("channel_id", "")
    # Present only when invoked inside a thread; forwarding it keeps the reply in-thread.
    thread_ts = payload.get("thread_ts", "")
    raw_text = (payload.get("text") or "").strip()
    command_name = payload.get("command", SLASH_COMMAND_NAME)
    # Unique per invocation — used to derive a distinct workflow id since slash
    # payloads carry no message ``ts`` or event id to key on.
    trigger_id = payload.get("trigger_id", "")

    if not slack_team_id or not slack_user_id:
        return _ephemeral_response("Missing Slack payload fields.")

    # A bare ``/posthog`` (no arguments) behaves as ``/posthog help``.
    sub_command_text = raw_text or "help"
    parsed = parse_rules_command(sub_command_text)

    logger.info(
        "slack_app_slash_command_received",
        slack_team_id=slack_team_id,
        slack_user_id=slack_user_id,
        channel_id=channel_id,
        command=command_name,
        sub_command=parsed.action if parsed is not None else "unknown",
    )
    if parsed is None:
        return _ephemeral_response(_unknown_command_help(command_name))

    # Region routing is cheap, so it stays inline — the sync response gives the
    # invoker immediate feedback when the workspace isn't connected.
    incoming_host = request.get_host()
    proxied = was_proxied(request)
    other_domain = other_region_domain(incoming_host)
    can_defer = cross_region_routing_enabled() and not is_us_host(incoming_host) and not proxied

    workspace_result = load_integrations(
        slack_team_id=slack_team_id,
        kinds=[SLACK_INTEGRATION_KIND],
        slack_user_id=slack_user_id,
    )
    region_route = resolve_region_or_terminal_route(
        request,
        slack_team_id,
        candidates_present=bool(workspace_result.candidates),
        kinds=[SLACK_INTEGRATION_KIND],
        proxied=proxied,
        other_domain=other_domain,
        incoming_host=incoming_host,
        can_defer=can_defer,
    )
    # ``None`` means handle locally; the ROUTE_* values are terminal exits.
    if region_route == ROUTE_NO_INTEGRATION:
        return _ephemeral_response(
            "This Slack workspace isn't connected to a PostHog organization. "
            "Connect it from a project's *Integrations* page first."
        )
    if region_route == ROUTE_PROXY_FAILED:
        return _ephemeral_response("Couldn't reach the PostHog backend — try again in a moment.")
    if region_route is not None:
        # ROUTE_PROXIED: the sibling region already accepted the forwarded payload
        # and will post the bot's reply through its own Slack client. Ack with 200.
        return HttpResponse(status=200)

    # Synthesise a mention-shaped event and hand off to the durable workflow;
    # ``user_id=None`` defers the slow user resolution off the request path.
    event: dict[str, Any] = {"channel": channel_id, "user": slack_user_id, "text": sub_command_text}
    if thread_ts:
        event["thread_ts"] = thread_ts

    _start_command_workflow(
        event,
        workspace_result.candidates,
        slack_team_id,
        event_id=trigger_id or None,
        user_id=None,
        command_prefix=command_name,
    )
    return HttpResponse(status=200)


def _ephemeral_response(text: str) -> JsonResponse:
    return JsonResponse({"response_type": "ephemeral", "text": text})


def _unknown_command_help(command_name: str) -> str:
    return (
        "I didn't recognize that sub-command. Try one of:\n"
        f"• `{command_name} help`\n"
        f"• `{command_name} rules list`\n"
        f'• `{command_name} rules add "description" org/repo`\n'
        f"• `{command_name} rules remove <number(s)>`\n"
        f"• `{command_name} project [<id>]`"
    )
