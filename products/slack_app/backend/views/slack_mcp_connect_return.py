"""Browser return leg for MCP servers connected from Slack onboarding messages.

A Connect button in the fleet-reveal DM carries a signed state naming the Slack workspace,
user, scout, and server. After the provider OAuth completes, mcp_store redirects here; we
refresh the fleet-reveal message (⚠️ → ✅) and bounce the user straight back into Slack.
"""

import hashlib

from django.core import signing
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.utils.html import escape

import structlog

from products.slack_app.backend import persona_onboarding

logger = structlog.get_logger(__name__)

_PAGE = """<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>{title}</title>
    {refresh}
    <style>
      body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0;
      }}
      main {{ text-align: center; max-width: 26rem; padding: 0 1rem; }}
    </style>
  </head>
  <body>
    <main>
      <h1>{heading}</h1>
      <p>{body}</p>
    </main>
  </body>
</html>"""


def slack_mcp_connected(request: HttpRequest) -> HttpResponse:
    state_token = str(request.GET.get("state") or "")
    try:
        payload = persona_onboarding.unsign_connect_state(state_token)
    except signing.BadSignature:
        return HttpResponse("This link is invalid or has expired.", status=400)
    success = request.GET.get("status", "success") != "error"
    # The signed state is reusable for its whole 30-day life, so a back-button or reload re-hits
    # this GET. Fire the connect-conversion event once per state token (hashed — raw tokens make
    # poor cache keys) so replays don't inflate the metric; the fleet refresh stays idempotent.
    token_hash = hashlib.sha256(state_token.encode()).hexdigest()
    first_visit = cache.add(
        f"slack_mcp_connect_event:{token_hash}", 1, timeout=persona_onboarding.CONNECT_STATE_MAX_AGE_SECONDS
    )
    deep_link = persona_onboarding.handle_mcp_connect_return(
        workspace_id=str(payload.get("w") or ""),
        slack_user_id=str(payload.get("u") or ""),
        readiness_key=str(payload.get("k") or ""),
        template_name=str(payload.get("t") or ""),
        success=success,
        error=str(request.GET.get("error") or ""),
        capture_event=first_visit,
    )
    server = escape(str(payload.get("t") or "MCP server"))
    if success:
        heading = f"{server} connected 🎉"
        body = f'Taking you back to Slack…<br /><a href="{escape(deep_link)}">Open Slack</a>'
        refresh = f'<meta http-equiv="refresh" content="0; url={escape(deep_link)}" />'
    else:
        heading = f"{server} connection failed"
        body = f'Head back to Slack and try again.<br /><a href="{escape(deep_link)}">Open Slack</a>'
        refresh = ""
    return HttpResponse(_PAGE.format(title=heading, refresh=refresh, heading=heading, body=body))
