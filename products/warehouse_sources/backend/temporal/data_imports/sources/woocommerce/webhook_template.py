from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-woocommerce",
    name="WooCommerce warehouse source webhook",
    description="Receive WooCommerce webhook events for data warehouse ingestion",
    icon_url="/static/services/woocommerce.png",
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

  let signature := request.headers['x-wc-webhook-signature']

  if (empty(signature)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature',
      }
    }
  }

  // WooCommerce sends base64(HMAC-SHA256(raw body, webhook secret)). No timestamp is involved.
  // The store's create-time ping carries no signature and lands here as a 400, which is expected
  // and harmless: WooCommerce ignores the ping response and it never counts as a delivery failure.
  let computedSignature := sha256HmacChain([inputs.signing_secret, request.stringBody], 'base64')

  if (computedSignature != signature) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Bad signature',
      }
    }
  }
}

// `deleted` payloads carry only `{"id": ...}`, so merging one would null out every other column
// of the row it matched.
if (request.headers['x-wc-webhook-event'] == 'deleted') {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'Delete event, skipping'
    }
  }
}

// WooCommerce puts the object type in a header rather than the body, so this is the only
// discriminator available for routing a delivery to its table.
let resource := request.headers['x-wc-webhook-resource']

if (empty(resource)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No webhook resource header found, skipping'
    }
  }
}

let schemaId := inputs.schema_mapping?.[resource]

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'No schema mapping for resource: {resource}, skipping'
    }
  }
}

// A payload with no id can't be merged onto the table, and it's what WooCommerce sends when the
// object was removed between the hook firing and the payload being built.
if (empty(request.body.id)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'Payload has no id, skipping'
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
                "The secret set on the WooCommerce webhook. Used to verify the X-WC-Webhook-Signature "
                "header (base64 HMAC-SHA256 of the raw request body) so deliveries provably come from "
                "your store."
            ),
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the X-WC-Webhook-Signature header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps WooCommerce webhook resources to ExternalDataSchema IDs",
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
