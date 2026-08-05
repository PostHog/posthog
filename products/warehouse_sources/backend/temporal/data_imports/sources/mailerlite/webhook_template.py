from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# MailerLite signs every delivery with a `Signature` header holding the lowercase hex
# HMAC-SHA256 of the raw request body, keyed by the `secret` MailerLite generates when the
# webhook is created (POST /api/webhooks returns it once).
#
# Flat subscriber deliveries carry the event name under `event`; the nested ones
# (`subscriber.added_to_group`, `subscriber.removed_from_group`) use `type` instead. Both are
# `<resource>.<action>`, so the resource prefix is the schema routing key and every campaign
# event falls through unmapped.
template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-mailerlite",
    name="MailerLite warehouse source webhook",
    description="Receive MailerLite webhook events for data warehouse ingestion",
    icon_url="/static/services/mailerlite.png",
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

  let signature := request.headers['signature']

  if (empty(signature)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature',
      }
    }
  }

  let computedSignature := sha256HmacChainHex([inputs.signing_secret, request.stringBody])

  if (lower(signature) != computedSignature) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Bad signature',
      }
    }
  }
}

let eventType := request.body.event ?? request.body.type

if (empty(eventType)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No event type found, skipping'
    }
  }
}

let resourceType := splitByString('.', eventType)[1]
let schemaId := inputs.schema_mapping?.[resourceType]

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'No schema mapping for resource type: {resourceType}, skipping'
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
            "description": (
                "The webhook's secret from MailerLite. Used to verify the Signature header "
                "(HMAC-SHA256 of the raw request body) so deliveries provably come from MailerLite."
            ),
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the Signature header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps MailerLite resource types to ExternalDataSchema IDs",
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
