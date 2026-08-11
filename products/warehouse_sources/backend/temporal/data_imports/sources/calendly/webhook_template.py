from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-calendly",
    name="Calendly warehouse source webhook",
    description="Receive Calendly webhook events for data warehouse ingestion",
    icon_url="/static/services/calendly.png",
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

if (not inputs.bypass_signature_check) {
  if (empty(inputs.signing_secret)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Signing secret not configured',
      }
    }
  }

  let body := request.stringBody
  let signatureHeader := request.headers['calendly-webhook-signature']

  if (empty(signatureHeader)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature',
      }
    }
  }

  let headerParts := splitByString(',', signatureHeader)
  let timestamp := null
  let v1Signature := null

  for (let _, part in headerParts) {
      let trimmed := trim(part)
      if (trimmed like 't=%') {
          let tParts := splitByString('=', trimmed, 2)
          if (length(tParts) = 2) {
              timestamp := tParts[2]
          }
      }
      if (trimmed like 'v1=%') {
          let v1Parts := splitByString('=', trimmed, 2)
          if (length(v1Parts) = 2) {
              v1Signature := v1Parts[2]
          }
      }
  }

  if (empty(timestamp) or empty(v1Signature)) {
      return {
        'httpResponse': {
          'status': 400,
          'body': 'Could not parse signature',
        }
      }
  }

  let signedPayload := concat(timestamp, '.', body)
  let computedSignature := sha256HmacChainHex([inputs.signing_secret, signedPayload])

  if (computedSignature != v1Signature) {
      return {
        'httpResponse': {
          'status': 400,
          'body': 'Bad signature',
        }
      }
  }

  let currentTime := toInt(toUnixTimestamp(now()))
  let timestampDelta := currentTime - toInt(timestamp)
  if (timestampDelta > 300 or timestampDelta < -300) {
      return {
        'httpResponse': {
          'status': 400,
          'body': 'Timestamp outside tolerance',
        }
      }
  }
}

// Every subscribed event is an invitee event whose payload embeds the scheduled event. Events
// without one (a routing form submission, or an invitee payload missing it) are acked and
// dropped rather than routed to a table they don't fit.
let scheduledEvent := request.body.payload?.scheduled_event

if (empty(scheduledEvent) or empty(scheduledEvent?.uri)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No scheduled event found, skipping'
    }
  }
}

let schemaId := inputs.schema_mapping?.['scheduled_event']

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No schema mapping for scheduled events, skipping'
    }
  }
}

produceToWarehouseWebhooks(request.body, schemaId)""",
    inputs_schema=[
        {
            "type": "string",
            "key": "signing_secret",
            "label": "Signing key",
            "required": False,
            "secret": True,
            "hidden": False,
            "description": (
                "The webhook subscription's signing key. Used to verify the Calendly-Webhook-Signature "
                "header (HMAC-SHA256 over the timestamp and the raw request body) so deliveries "
                "provably come from Calendly."
            ),
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": (
                "If set, the Calendly-Webhook-Signature header will not be checked. This is not recommended."
            ),
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Calendly resource types to ExternalDataSchema IDs",
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
