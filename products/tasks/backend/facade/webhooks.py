"""
Facade re-exports for the inbound event handlers.

Core's unified GitHub webhook view dispatches to these: it verifies the signature on every
POST, routes pull-request events to the tasks handler, and fans events out to loop triggers.

The Slack app product's Events API handler dispatches ``message`` events to
``handle_slack_message_for_loops`` the same way, after its own signature check.
"""

from products.tasks.backend.loop_github_events import handle_github_event_for_loops
from products.tasks.backend.loop_slack_events import handle_slack_message_for_loops, slack_workspace_has_loop_triggers
from products.tasks.backend.models import Task
from products.tasks.backend.webhooks import (
    get_github_webhook_secret,
    handle_pull_request_event,
    verify_github_signature,
)

# So the Slack app can tell a loop-fired task's thread apart from a mention's without
# reaching for the model.
TASK_ORIGIN_PRODUCT_LOOP = Task.OriginProduct.LOOP.value

__all__ = [
    "TASK_ORIGIN_PRODUCT_LOOP",
    "get_github_webhook_secret",
    "handle_github_event_for_loops",
    "handle_pull_request_event",
    "handle_slack_message_for_loops",
    "slack_workspace_has_loop_triggers",
    "verify_github_signature",
]
