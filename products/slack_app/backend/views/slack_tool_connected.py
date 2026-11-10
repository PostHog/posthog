from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.views.decorators.http import require_GET

from posthog.views import login_required

from products.slack_app.backend.logic.connect_tool import (
    authorize_url,
    read_connected_state,
    resume_mention_workflow,
    return_to_slack_url,
)


@require_GET
@login_required
def slack_tool_connect(request: HttpRequest) -> HttpResponse:
    """The Connect button in Slack lands here, so a browser without a PostHog session logs in first, then goes on to
    the MCP store's OAuth start for the offered tool."""
    state_token = request.GET.get("state", "")
    state = read_connected_state(state_token)
    url = authorize_url(state_token, state) if state is not None else None
    return HttpResponseRedirect(url or "/")


@require_GET
@login_required
def slack_tool_connected(request: HttpRequest) -> HttpResponse:
    """The MCP install's OAuth flow returns here, so the Slack request that waits for the tool starts its task.
    The signed state names the waiting workflow and the Slack thread to send the person back to."""
    state = read_connected_state(request.GET.get("state", ""))
    if state is None:
        return HttpResponseRedirect("/")
    # A failed connection leaves the run to its own timeout, or to the "Continue without it" button.
    if request.GET.get("oauth_complete") == "true":
        resume_mention_workflow(state["workflow_id"])
    return HttpResponseRedirect(return_to_slack_url(state))
