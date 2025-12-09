from posthog.cdp.validation import compile_hog, generate_template_bytecode
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


def _get_inputs(redirect_url: str) -> dict:
    inputs = {
        "debug": {"order": 2, "value": False, "templating": "hog"},
        "properties": {
            "order": 1,
            "value": {"$$_extend_object": "{event.query}"},
            "templating": "hog",
        },
        "redirect_url": {"order": 0, "value": redirect_url, "templating": "hog"},
    }
    for value in inputs.values():
        value["bytecode"] = generate_template_bytecode(value["value"], set())
    return inputs


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
                "key": "redirect_url",
                "type": "string",
                "label": "Redirect URL",
                "hidden": False,
                "secret": False,
                "required": True,
            },
            {
                "key": "properties",
                "type": "json",
                "label": "Event properties",
                "hidden": False,
                "secret": False,
                "default": {"$ip": "{request.ip}", "$lib": "posthog-webhook", "$source_url": "{source.url}"},
                "required": False,
                "description": "A mapping of the incoming webhook body to the PostHog event properties",
            },
            {
                "key": "debug",
                "type": "boolean",
                "label": "Log payloads",
                "hidden": False,
                "secret": False,
                "default": False,
                "required": False,
                "description": "Logs the incoming request for debugging",
            },
        ],
        inputs=_get_inputs(redirect_url),
        enabled=True,
        bytecode=compile_hog(LINK_HOG_FUNCTION_CODE, "destination"),
    )
