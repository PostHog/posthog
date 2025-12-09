from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.team.team import Team

LINK_HOG_FUNCTION_CODE = """
if (inputs.debug) {
  print('Incoming request:', request.body);
}
if (inputs.redirect_url) {
  return {
    'httpResponse': {
      'status': 302,
      'body': { 'Location': inputs.redirect_url },
      'header': { 'Location': inputs.redirect_url },
    },
  };
}
postHogCapture({
  event: '$link_clicked',
  distinct_id: 'link_tracking',
  properties: inputs.properties,
});
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
                "type": "string",
                "key": "redirect_url",
                "label": "Redirect URL",
                "required": True,
                "secret": False,
                "hidden": False,
            },
            {
                "type": "json",
                "key": "properties",
                "label": "Event properties",
                "required": False,
                "default": {"$ip": "{request.ip}", "$lib": "posthog-webhook", "$source_url": "{source.url}"},
                "secret": False,
                "hidden": False,
                "description": "A mapping of the incoming webhook body to the PostHog event properties",
            },
            {
                "type": "boolean",
                "key": "debug",
                "label": "Log payloads",
                "required": False,
                "default": False,
                "secret": False,
                "hidden": False,
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
