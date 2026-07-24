from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# UpPromote signs webhooks with HMAC-SHA256 over the raw request body using the subscription's
# secret key, sent as X-UpPromote-Signature (hex digest, no timestamp). The payload is the bare
# object with no event-name envelope, so routing derives the object type from the payload shape:
# paid payments carry `payment_id`, referrals carry `tracking_type`/`commission_rule`, and
# affiliates carry a top-level `email`. The `*.status-changed` diff payloads
# ({previous_status, current_status}) match none of these and are skipped.
template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-uppromote",
    name="UpPromote warehouse source webhook",
    description="Receive UpPromote webhook events for data warehouse ingestion",
    icon_url="/static/services/uppromote.png",
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
  let signatureHeader := request.headers['x-uppromote-signature']

  if (empty(signatureHeader)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature',
      }
    }
  }

  let computedSignature := sha256HmacChainHex([inputs.signing_secret, body])

  if (computedSignature != signatureHeader) {
      return {
        'httpResponse': {
          'status': 400,
          'body': 'Bad signature',
        }
      }
  }
}

let payload := request.body
let objectType := ''

if (not empty(payload.payment_id)) {
  objectType := 'payment'
}
if (objectType == '' and (not empty(payload.tracking_type) or not empty(payload.commission_rule))) {
  objectType := 'referral'
}
if (objectType == '' and not empty(payload.email)) {
  objectType := 'affiliate'
}

if (empty(objectType)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'Unrecognized payload shape, skipping'
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
            "description": "Used to validate the webhook came from UpPromote",
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the X-UpPromote-Signature header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps UpPromote object types to ExternalDataSchema IDs",
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
