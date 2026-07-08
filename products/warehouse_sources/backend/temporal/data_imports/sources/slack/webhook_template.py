from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-slack",
    name="Slack warehouse source webhook",
    description="Receive Slack webhook events for data warehouse ingestion",
    icon_url="/static/services/slack.png",
    category=["Data warehouse"],
    code_language="hog",
    code="""\
if (request.method != 'POST') {
  return {
    'httpResponse': {
      'status': 405,
      'body': 'Method not allowed'
    }
  }
}

let body := request.body
let isUrlVerification := body.type = 'url_verification'

// Slack's url_verification handshake fires the moment a manifest with a
// request_url is submitted. We have no signing secret yet at that point
// (the user hasn't seen the app credentials page), so allow url_verification
// through unsigned only when no secret is configured. Once the secret is set,
// even url_verification requests are validated normally.
if (not inputs.bypass_signature_check and not (isUrlVerification and empty(inputs.signing_secret))) {
  if (empty(inputs.signing_secret)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Signing secret not configured',
      }
    }
  }

  let rawBody := request.stringBody
  let slackSignature := request.headers['x-slack-signature']
  let slackTimestamp := request.headers['x-slack-request-timestamp']

  if (empty(slackSignature) or empty(slackTimestamp)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature headers',
      }
    }
  }

  // Reject requests whose timestamp is more than 5 minutes off — Slack's
  // recommendation to defend against replay attacks. Without this, a
  // captured signed request could be replayed indefinitely.
  let nowTs := toUnixTimestamp(now())
  let slackTs := toFloat(slackTimestamp)
  if (slackTs < nowTs - 300 or slackTs > nowTs + 300) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Stale request timestamp',
      }
    }
  }

  let sigBasestring := concat('v0:', slackTimestamp, ':', rawBody)
  let computedSignature := concat('v0=', sha256HmacChainHex([inputs.signing_secret, sigBasestring]))

  if (computedSignature != slackSignature) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Bad signature',
      }
    }
  }
}

if (isUrlVerification) {
  return {
    'httpResponse': {
      'status': 200,
      'contentType': 'application/json',
      'body': jsonStringify({'challenge': body.challenge})
    }
  }
}

// Only process event_callback types
if (body.type != 'event_callback') {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'Not an event_callback, skipping'
    }
  }
}

let channelId := body.event?.channel

if (empty(channelId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No channel found in event, skipping'
    }
  }
}

let schemaId := inputs.schema_mapping?.[channelId]

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'No schema mapping for channel: {channelId}, skipping'
    }
  }
}

produceToWarehouseWebhooks(request.body, schemaId)""",
    inputs_schema=[
        {
            "type": "string",
            "key": "signing_secret",
            "label": "Signing secret",
            "required": False,
            "secret": True,
            "hidden": False,
            "description": "Used to validate the webhook came from Slack. Found under Basic Information > App Credentials in your Slack app settings.",
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the x-slack-signature header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Slack channel IDs to ExternalDataSchema IDs",
            "required": True,
            "secret": False,
            "hidden": True,
        },
        {
            "type": "string",
            "key": "source_id",
            "label": "Source ID",
            "description": "The ExternalDataSource ID this webhook is associated with",
            "required": True,
            "secret": False,
            "hidden": True,
        },
    ],
)
