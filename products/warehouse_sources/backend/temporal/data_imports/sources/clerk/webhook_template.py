from products.cdp.backend.templates.hog_function_template import HogFunctionTemplateDC

# Clerk sends webhooks through Svix. Svix signs "{svix-id}.{svix-timestamp}.{raw body}" with
# HMAC-SHA256. The key is the base64 part of the whsec_ signing secret, decoded to bytes. The
# svix-signature header holds one or more space-separated "v1,<base64 signature>" entries.
template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-clerk",
    name="Clerk warehouse source webhook",
    description="Receive Clerk webhook events for data warehouse ingestion",
    icon_url="/static/services/clerk.png",
    category=["Data warehouse"],
    code_language="hog",
    code="""\
if (request.method != 'POST') {
  return {'httpResponse': {'status': 405, 'body': 'Method not allowed'}}
}

if (not inputs.bypass_signature_check) {
  if (empty(inputs.signing_secret)) {
    return {
      'httpResponse': {'status': 200, 'body': 'Signing secret not configured, delivery dropped'},
      'appMetric': 'missing_credential'
    }
  }

  let messageId := request.headers['svix-id']
  let timestamp := request.headers['svix-timestamp']
  let signatureHeader := request.headers['svix-signature']
  if (empty(messageId) or empty(timestamp) or empty(signatureHeader)) {
    return {'httpResponse': {'status': 400, 'body': 'Missing signature'}}
  }

  // The standard base64 alphabet has no underscore, so 'whsec_' can only match the prefix.
  let key := replaceOne(trim(inputs.signing_secret), 'whsec_', '')
  let expected := sha256HmacBase64Key(key, concat(messageId, '.', timestamp, '.', request.stringBody), 'base64')
  let matched := false
  for (let _, entry in splitByString(' ', signatureHeader)) {
    let pair := splitByString(',', trim(entry), 2)
    if (length(pair) = 2 and pair[1] = 'v1' and pair[2] = expected) {
      matched := true
    }
  }
  if (not matched) {
    return {'httpResponse': {'status': 400, 'body': 'Bad signature'}}
  }

  let age := toInt(toUnixTimestamp(now())) - toInt(timestamp)
  if (age > 300 or age < -300) {
    return {'httpResponse': {'status': 400, 'body': 'Timestamp outside tolerance'}}
  }
}

let eventType := request.body.type
// Several event types feed one warehouse table, so the event is collapsed to a resource key
// before the schema lookup. Keep in sync with WEBHOOK_EVENTS_BY_SCHEMA in settings.py.
let resourceByEvent := {
  'user.created': 'users', 'user.updated': 'users',
  'organization.created': 'organizations', 'organization.updated': 'organizations',
  'organizationMembership.created': 'organization_memberships',
  'organizationMembership.updated': 'organization_memberships',
}
let resource := resourceByEvent?.[eventType]
if (empty(resource)) {
  return {'httpResponse': {'status': 200, 'body': f'Unhandled event type: {eventType}, skipping'}}
}
let schemaId := inputs.schema_mapping?.[resource]
if (empty(schemaId)) {
  return {'httpResponse': {'status': 200, 'body': f'No schema mapping for event type: {eventType}, skipping'}}
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
            "description": "Used to verify Clerk webhook deliveries",
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the svix-signature header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Clerk resources to ExternalDataSchema IDs",
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
