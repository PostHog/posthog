from products.warehouse_sources.sources.sdk import HogFunctionTemplateDC

# Nylas verifies a webhook URL once, when the webhook is created or set back to active: it sends
# `GET <url>?challenge=<value>` and expects the bare value back within 10 seconds. That request
# is unsigned, because the secret is only returned by the create call it belongs to.
#
# Every notification is a POST signed with a hex HMAC-SHA256 of the raw body, keyed with the
# webhook secret, in `x-nylas-signature`. The envelope is `{type, time, data: {object}}`.
# `message.created` and `message.updated` also arrive with a `.truncated` suffix (body removed
# above 1 MB) or a `.transformed` suffix (fields trimmed in the Nylas dashboard). The table is
# picked from `data.object.object`: message, event or contact.
template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-nylas",
    name="Nylas warehouse source webhook",
    description="Receive Nylas message, event and contact notifications for data warehouse ingestion",
    icon_url="/static/services/nylas.png",
    category=["Data warehouse"],
    code_language="hog",
    code="""\
if (request.method == 'GET') {
  let challenge := request.query.challenge

  // The value is echoed back, so only a plain token is accepted.
  if (empty(challenge) or not match(challenge, '^[A-Za-z0-9_-]{1,128}$')) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing or invalid challenge'
      }
    }
  }

  return {
    'httpResponse': {
      'status': 200,
      'contentType': 'text/plain',
      'body': challenge
    }
  }
}

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
      'status': 200,
      'body': 'Webhook secret not configured, delivery dropped',
    },
    'appMetric': 'missing_credential'
  }
}

let signature := request.headers['x-nylas-signature']

if (empty(signature)) {
  return {
    'httpResponse': {
      'status': 400,
      'body': 'Missing signature',
    }
  }
}

let computedSignature := sha256HmacChainHex([inputs.signing_secret, request.stringBody])

if (computedSignature != lower(signature)) {
  return {
    'httpResponse': {
      'status': 400,
      'body': 'Bad signature',
    }
  }
}

let eventType := request.body.type

let isSynced := false
if (not empty(eventType)) {
  for (let prefix in ['message.created', 'message.updated', 'event.created', 'event.updated', 'event.deleted', 'contact.updated']) {
    if (eventType == prefix or eventType like concat(prefix, '.%')) {
      isSynced := true
    }
  }
}

if (not isSynced) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'Not a synced notification type, skipping'
    }
  }
}

let objectType := request.body.data?.object?.object

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
            "label": "Webhook secret",
            "required": False,
            "secret": True,
            "hidden": False,
            "description": "Used to validate the webhook came from Nylas",
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Nylas object types to ExternalDataSchema IDs",
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
