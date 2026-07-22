from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# Yousign signs deliveries with X-Yousign-Signature-256: sha256=<hex hmac-sha256 of the raw
# request body>, keyed with the subscription's secret_key (returned on webhook creation and
# visible on the subscription in the Yousign app).
template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-yousign",
    name="Yousign warehouse source webhook",
    description="Receive Yousign webhook events for data warehouse ingestion",
    icon_url="/static/services/yousign.png",
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

if (empty(inputs.signing_secret)) {
  return {
    'httpResponse': {
      'status': 400,
      'body': 'Signing secret not configured',
    }
  }
}

let body := request.stringBody
let signatureHeader := request.headers['x-yousign-signature-256']

if (empty(signatureHeader)) {
  return {
    'httpResponse': {
      'status': 400,
      'body': 'Missing signature',
    }
  }
}

if (not (signatureHeader like 'sha256=%')) {
  return {
    'httpResponse': {
      'status': 400,
      'body': 'Could not parse signature',
    }
  }
}

let sigParts := splitByString('sha256=', signatureHeader, 2)
let providedSignature := sigParts[2]

let computedSignature := sha256HmacChainHex([inputs.signing_secret, body])

if (computedSignature != providedSignature) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Bad signature',
      }
    }
}

let eventName := request.body.event_name

if (empty(eventName)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No event found, skipping'
    }
  }
}

// The event name prefix is the object type: signature_request.done -> signature_request.
let objectType := splitByString('.', eventName)[1]

let schemaId := inputs.schema_mapping?.[objectType]

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'No schema mapping for object type: {objectType}, skipping'
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
            "description": "Used to validate the webhook came from Yousign",
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Yousign object types to ExternalDataSchema IDs",
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
