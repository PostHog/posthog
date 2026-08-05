from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# Featurebase signs webhooks with HMAC-SHA256 over "{timestamp}.{raw body}" using the
# whsec_ signing secret, sent as X-Webhook-Signature with X-Webhook-Timestamp (5 minute
# replay window). The payload envelope is {topic, data: {item, changes}}; data.item.object
# identifies the resource type used for schema routing.
template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-featurebase",
    name="Featurebase warehouse source webhook",
    description="Receive Featurebase webhook events for data warehouse ingestion",
    icon_url="/static/services/featurebase.png",
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
  let signatureHeader := request.headers['x-webhook-signature']
  let timestamp := request.headers['x-webhook-timestamp']

  if (empty(signatureHeader) or empty(timestamp)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature',
      }
    }
  }

  let signedPayload := concat(timestamp, '.', body)
  let computedSignature := sha256HmacChainHex([inputs.signing_secret, signedPayload])

  if (computedSignature != signatureHeader) {
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

let objectType := request.body.data?.item?.object

if (empty(objectType)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No object type found, skipping'
    }
  }
}

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
            "description": "Used to validate the webhook came from Featurebase",
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the X-Webhook-Signature header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Featurebase object types to ExternalDataSchema IDs",
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
