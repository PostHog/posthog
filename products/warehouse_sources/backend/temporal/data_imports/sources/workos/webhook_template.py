from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-workos",
    name="WorkOS warehouse source webhook",
    description="Receive WorkOS webhook events for data warehouse ingestion",
    icon_url="/static/services/workos.png",
    category=["Data warehouse"],
    code_language="hog",
    code="""\
if (request.method != 'POST') {
  return {'httpResponse': {'status': 405, 'body': 'Method not allowed'}}
}

if (not inputs.bypass_signature_check) {
  if (empty(inputs.signing_secret)) {
    return {'httpResponse': {'status': 400, 'body': 'Signing secret not configured'}}
  }

  let signatureHeader := request.headers['workos-signature']
  if (empty(signatureHeader)) {
    return {'httpResponse': {'status': 400, 'body': 'Missing signature'}}
  }

  let parts := splitByString(',', signatureHeader)
  let timestamp := null
  let signature := null
  for (let _, part in parts) {
    let pair := splitByString('=', trim(part), 2)
    if (length(pair) = 2 and pair[1] = 't') { timestamp := pair[2] }
    if (length(pair) = 2 and pair[1] = 'v1') { signature := pair[2] }
  }

  if (empty(timestamp) or empty(signature)) {
    return {'httpResponse': {'status': 400, 'body': 'Could not parse signature'}}
  }

  let expected := sha256HmacChainHex([inputs.signing_secret, concat(timestamp, '.', request.stringBody)])
  if (expected != signature) {
    return {'httpResponse': {'status': 400, 'body': 'Bad signature'}}
  }

  let age := toUnixTimestampMilli(now()) - toInt(timestamp)
  if (age > 180000 or age < -180000) {
    return {'httpResponse': {'status': 400, 'body': 'Timestamp outside tolerance'}}
  }
}

let eventType := request.body.event
// Several event types feed one warehouse table, so the event is collapsed to a resource key
// before the schema lookup. Keep in sync with WEBHOOK_EVENTS_BY_SCHEMA in settings.py.
let resourceByEvent := {
  'user.created': 'users', 'user.updated': 'users', 'user.deleted': 'users',
  'organization.created': 'organizations', 'organization.updated': 'organizations', 'organization.deleted': 'organizations',
  'dsync.user.created': 'directory_users', 'dsync.user.updated': 'directory_users', 'dsync.user.deleted': 'directory_users',
  'dsync.group.created': 'directory_groups', 'dsync.group.updated': 'directory_groups', 'dsync.group.deleted': 'directory_groups',
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
            "description": "Used to verify WorkOS webhook deliveries",
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the WorkOS-Signature header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps WorkOS resources to ExternalDataSchema IDs",
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
