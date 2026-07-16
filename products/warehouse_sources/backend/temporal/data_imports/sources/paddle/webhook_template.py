from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-paddle",
    name="Paddle warehouse source webhook",
    description="Receive Paddle webhook events for data warehouse ingestion",
    icon_url="/static/services/paddle.png",
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
  let signatureHeader := request.headers['paddle-signature']

  if (empty(signatureHeader)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature',
      }
    }
  }

  let headerParts := splitByString(';', signatureHeader)
  let timestamp := null
  // Paddle sends multiple h1 values while a signing secret rotation is in progress
  let h1Signatures := []

  for (let _, part in headerParts) {
      let trimmed := trim(part)
      if (trimmed like 'ts=%') {
          let tsParts := splitByString('=', trimmed, 2)
          if (length(tsParts) = 2) {
              timestamp := tsParts[2]
          }
      }
      if (trimmed like 'h1=%') {
          let h1Parts := splitByString('=', trimmed, 2)
          if (length(h1Parts) = 2) {
              h1Signatures := arrayPushBack(h1Signatures, h1Parts[2])
          }
      }
  }

  if (empty(timestamp) or empty(h1Signatures)) {
      return {
        'httpResponse': {
          'status': 400,
          'body': 'Could not parse signature',
        }
      }
  }

  // Replay protection: reject deliveries whose signature timestamp is older than
  // maximum_variance_seconds, mirroring the Paddle SDK's Verifier. Defaults to 5 when unset — the
  // webhook-creation path only persists schema_mapping/source_id/signing_secret, not input defaults,
  // so `?? 0` would silently disable the check in production. An explicit 0 still disables it (`??`
  // coalesces null only, not 0). toInt is null-coalesced too: a non-numeric ts would otherwise raise.
  let maxVariance := inputs.maximum_variance_seconds ?? 5
  if (maxVariance > 0) {
      if (toUnixTimestamp(now()) - (toInt(timestamp) ?? 0) > maxVariance) {
          return {
            'httpResponse': {
              'status': 400,
              'body': 'Signature timestamp too old',
            }
          }
      }
  }

  let signedPayload := concat(timestamp, ':', body)
  let computedSignature := sha256HmacChainHex([inputs.signing_secret, signedPayload])
  let signatureMatches := false

  for (let _, h1Signature in h1Signatures) {
      if (computedSignature = h1Signature) {
          signatureMatches := true
      }
  }

  if (not signatureMatches) {
      return {
        'httpResponse': {
          'status': 400,
          'body': 'Bad signature',
        }
      }
  }
}

let eventType := request.body.event_type

if (empty(eventType)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No event type found, skipping'
    }
  }
}

let entityType := splitByString('.', eventType)[1]

let schemaId := inputs.schema_mapping?.[entityType]

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'No schema mapping for event type: {eventType}, skipping'
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
            "description": "Used to validate the webhook came from Paddle",
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the paddle-signature header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "number",
            "key": "maximum_variance_seconds",
            "label": "Maximum signature age (seconds)",
            "description": "Reject webhooks whose signature timestamp is older than this many seconds, to limit replay. Set to 0 to disable. Mirrors the Paddle SDK default of 5.",
            "default": 5,
            "required": False,
            "secret": False,
            "hidden": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Paddle entity types to ExternalDataSchema IDs",
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
