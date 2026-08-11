from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-sparkpost",
    name="SparkPost warehouse source webhook",
    description="Receive SparkPost event webhook batches for data warehouse ingestion",
    icon_url="/static/services/sparkpost.png",
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

if (not inputs.bypass_authorization_check) {
  if (empty(inputs.authorization_header)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Authorization header value not configured',
      }
    }
  }

  // SparkPost authenticates every delivery with the basic-auth credentials set on the webhook
  // (`auth_type: "basic"`). PostHog generates those credentials at registration time and stores
  // the exact header value SparkPost will send, so verifying is a string comparison.
  let providedHeader := request.headers['authorization']

  if (empty(providedHeader)) {
    return {
      'httpResponse': {
        'status': 401,
        'body': 'Missing authorization header',
      }
    }
  }

  if (providedHeader != inputs.authorization_header) {
    return {
      'httpResponse': {
        'status': 401,
        'body': 'Bad authorization header',
      }
    }
  }
}

// A delivery is a JSON array of `{"msys": {"message_event": {...}}}` entries. Only one payload
// may be produced per request, so the whole batch is handed over as a string and the source's
// table transformer explodes it into one row per event.
let schemaId := inputs.schema_mapping?.['message_event']

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No schema mapping for message events, skipping'
    }
  }
}

if (empty(request.body)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'Empty batch, skipping'
    }
  }
}

produceToWarehouseWebhooks({'sparkpost_webhook_batch': jsonStringify(request.body)}, schemaId)""",
    inputs_schema=[
        {
            "type": "string",
            "key": "authorization_header",
            "label": "Authorization header value",
            "required": False,
            "secret": True,
            "hidden": False,
            "description": (
                "The exact value SparkPost sends in the Authorization header on each delivery "
                "(e.g. `Basic dXNlcjpwYXNz`). PostHog rejects deliveries whose header does not match."
            ),
        },
        {
            "type": "boolean",
            "key": "bypass_authorization_check",
            "label": "Bypass authorization header check",
            "description": "If set, the Authorization header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps SparkPost event groupings to ExternalDataSchema IDs",
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
