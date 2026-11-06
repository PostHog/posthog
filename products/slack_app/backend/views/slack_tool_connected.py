from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.views.decorators.http import require_GET

from posthog.views import login_required

from products.slack_app.backend.logic.connect_tool import read_connected_state, resume_mention_workflow


@require_GET
@login_required
def slack_tool_connected(request: HttpRequest) -> HttpResponse:
    """The MCP install's OAuth flow returns here, so the Slack request that waits for the tool starts its task.
    The signed state names the waiting workflow and the Slack conversation to send the person back to."""
    state = read_connected_state(request.GET.get("state", ""))
    if state is None:
        return HttpResponseRedirect("/")
    # A failed connection leaves the run to its own timeout, or to the "Continue without it" button.
    if request.GET.get("oauth_complete") == "true":
        resume_mention_workflow(state["workflow_id"])
    query = urlencode({"team": state["slack_team_id"], "channel": state["channel"]})
    return HttpResponseRedirect(f"https://slack.com/app_redirect?{query}")
