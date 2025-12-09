from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.team.team import Team

LINK_HOG_FUNCTION_CODE = """
if(inputs.debug) {
  print('Incoming request:', request.body)
}

if (inputs.redirect_url) {
  return {
    'httpResponse': {
      'status': 302,
      'body': {
        'redirect_url': inputs.redirect_url
      }
    }
  }
}

postHogCapture({
  'event': '$link_clicked',
  'distinct_id': 'link_tracking',
  'properties': inputs.properties
})
"""


def get_hog_function(team: Team, redirect_url: str) -> HogFunction:
    return HogFunction(
        team=team,
        type="source_webhook",
        name="Link Tracking",
        description="A link tracking Hog function",
        icon_url="/static/services/webhook.svg",
        hog=LINK_HOG_FUNCTION_CODE,
        inputs_schema=[
            {
                "key": "event",
                "type": "string",
                "label": "Event name",
                "secret": False,
                "default": "{request.body.event}",
                "required": True,
            },
            {
                "key": "distinct_id",
                "type": "string",
                "label": "Distinct ID",
                "secret": False,
                "default": "{request.body.distinct_id}",
                "required": True,
                "description": "The distinct ID this event should be associated with",
            },
            {
                "key": "properties",
                "type": "json",
                "label": "Event properties",
                "secret": False,
                "default": {"$ip": "{request.ip}", "$lib": "posthog-webhook", "$source_url": "{source.url}"},
                "required": False,
                "description": "A mapping of the incoming webhook body to the PostHog event properties",
            },
            {
                "key": "auth_header",
                "type": "string",
                "label": "Authorization header value",
                "secret": True,
                "required": False,
                "description": 'If set, the incoming Authorization header must match this value exactly. e.g. "Bearer SECRET_TOKEN"',
            },
            {
                "key": "method",
                "type": "choice",
                "label": "Method",
                "secret": False,
                "choices": [
                    {"label": "POST", "value": "POST"},
                    {"label": "PUT", "value": "PUT"},
                    {"label": "PATCH", "value": "PATCH"},
                    {"label": "GET", "value": "GET"},
                    {"label": "DELETE", "value": "DELETE"},
                ],
                "default": "POST",
                "required": False,
                "description": "HTTP method to allow for the request.",
            },
            {
                "key": "debug",
                "type": "boolean",
                "label": "Log payloads",
                "secret": False,
                "default": False,
                "required": False,
                "description": "Logs the incoming request for debugging",
            },
        ],
        inputs={
            "redirect_url": {
                "value": redirect_url,
                "templating": "hog",
            },
            "properties": {
                "value": {"$$_extend_object": "{event.query}"},
                "templating": "hog",
            },
            "debug": {
                "value": False,
                "templating": "hog",
            },
        },
        enabled=True,
    )
