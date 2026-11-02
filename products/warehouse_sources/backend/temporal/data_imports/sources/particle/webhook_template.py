from products.cdp.backend.templates.hog_function_template import HogFunctionTemplateDC

# Particle doesn't sign webhook deliveries. `create_webhook` pins a generated secret in the
# x-posthog-webhook-secret header of every hook it creates, and this template rejects a delivery
# without it. A manually created hook has to set the same header.
#
# Each delivery is captured as a PostHog event on the device (person profiles off), and the raw
# event is also written to the `events` table when that table is enabled.
template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-particle",
    name="Particle warehouse source webhook",
    description="Receive Particle device events as PostHog events and data warehouse rows",
    icon_url="/static/services/particle.png",
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
      'status': 200,
      'body': 'Webhook secret not configured, delivery dropped',
    },
    'appMetric': 'missing_credential'
  }
}

let providedSecret := request.headers['x-posthog-webhook-secret']
if (empty(providedSecret) or providedSecret != inputs.signing_secret) {
  return {
    'httpResponse': {
      'status': 400,
      'body': 'Bad webhook secret',
    }
  }
}

let eventName := request.query.event
let deviceId := request.query.device_id
if (empty(eventName) or empty(deviceId)) {
  return {
    'httpResponse': {
      'status': 400,
      'body': 'Missing Particle event name or device ID',
    }
  }
}

// A plain publish arrives as a string, and a typed publish (Device OS 6.2+) as a structured value.
let rawData := request.body.data
let data := rawData
let rawString := rawData
if (typeof(rawData) == 'string') {
  if (isValidJSON(rawData)) {
    data := jsonParse(rawData)
  }
} else if (rawData != null) {
  rawString := jsonStringify(rawData)
}

// Reserved keys are dropped from the device data rather than overwritten afterwards, because the
// product fields are only set when Particle filled them (sandbox devices leave them empty).
let reservedKeys := [
  '$process_person_profile',
  'particle_device_id',
  'particle_event_id',
  'particle_published_at',
  'particle_product_id',
  'particle_firmware_version'
]
let properties := {}
if (typeof(data) == 'object') {
  for (let key, value in data) {
    if (not has(reservedKeys, key)) {
      properties[key] := value
    }
  }
} else if (data != null) {
  properties['data'] := data
}

properties['$process_person_profile'] := false
properties['particle_device_id'] := deviceId
properties['particle_event_id'] := request.query.event_id
properties['particle_published_at'] := request.query.published_at
if (notEmpty(request.query.product_id)) {
  properties['particle_product_id'] := request.query.product_id
}
if (notEmpty(request.query.firmware_version)) {
  properties['particle_firmware_version'] := request.query.firmware_version
}

postHogCapture({
  'event': eventName,
  'distinct_id': deviceId,
  'properties': properties
})

let schemaId := inputs.schema_mapping?.['events']
if (notEmpty(schemaId)) {
  produceToWarehouseWebhooks({
    'event_id': request.query.event_id,
    'event': eventName,
    'data': rawString,
    'device_id': deviceId,
    'product_id': request.query.product_id,
    'firmware_version': request.query.firmware_version,
    'published_at': request.query.published_at
  }, schemaId)
}""",
    inputs_schema=[
        {
            "type": "string",
            "key": "signing_secret",
            "label": "Webhook secret",
            "required": True,
            "secret": True,
            "hidden": False,
            "description": "Shared secret sent by Particle in the x-posthog-webhook-secret header, used to verify the delivery came from your webhook",
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps the Particle events table to its ExternalDataSchema ID",
            "required": True,
            "secret": False,
            "hidden": True,
        },
        {
            "type": "string",
            "key": "source_id",
            "label": "Source ID",
            "description": "ID of the source this webhook belongs to",
            "required": True,
            "secret": False,
            "hidden": True,
        },
    ],
)
