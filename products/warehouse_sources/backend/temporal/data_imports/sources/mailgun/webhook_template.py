from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-mailgun",
    name="Mailgun warehouse source webhook",
    description="Receive Mailgun webhook events for data warehouse ingestion",
    icon_url="/static/services/mailgun.png",
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

let signature := request.body.signature

if (not inputs.bypass_signature_check) {
  if (empty(inputs.signing_secret)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Signing secret not configured',
      }
    }
  }

  if (empty(signature) or empty(signature.timestamp) or empty(signature.token) or empty(signature.signature)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature',
      }
    }
  }

  // Mailgun signs the concatenation of the delivery's timestamp and token with the account's
  // HTTP webhook signing key, hex encoded. The request body itself is not part of the digest.
  let computedSignature := sha256HmacChainHex([inputs.signing_secret, concat(signature.timestamp, signature.token)])

  if (computedSignature != signature.signature) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Bad signature',
      }
    }
  }

  // The digest covers no body, so a captured delivery stays valid forever without a freshness
  // check. Mailgun recommends rejecting timestamps outside a few minutes of now.
  //
  // Because Mailgun's scheme signs only the timestamp and token, a signature proves the delivery
  // came from Mailgun but does not bind it to the payload it arrived with. Anyone holding a
  // captured triple can therefore re-post it with substituted event-data until it goes stale, and
  // that is a property of Mailgun's protocol rather than something this template can verify away.
  // Consuming each token once would close it, but a hog template has no atomic store to consume
  // against, so the window below is the control: it is the only thing bounding how long a captured
  // triple stays usable, so keep it tight. Downstream, the transformer keeps one row per event id
  // within a batch and the table delta-merges on that id, so a straight replay of an unmodified
  // delivery is idempotent; only substituted event-data lands new rows.
  let timestampDelta := toInt(toUnixTimestamp(now())) - toInt(signature.timestamp)
  if (timestampDelta > 300 or timestampDelta < -300) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Timestamp outside tolerance',
      }
    }
  }
}

let eventData := request.body['event-data']
let eventName := eventData.event

if (empty(eventName)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No event type found, skipping'
    }
  }
}

// Every Mailgun event type feeds the one webhook-only table, so the event is collapsed to a
// resource key before the schema lookup. Keep in sync with WEBHOOK_EVENT_NAMES in settings.py.
let resourceByEvent := {
  'accepted': 'email_event',
  'clicked': 'email_event',
  'complained': 'email_event',
  'delivered': 'email_event',
  'failed': 'email_event',
  'opened': 'email_event',
  'unsubscribed': 'email_event',
}

let resource := resourceByEvent?.[eventName]

if (empty(resource)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'Unhandled event type: {eventName}, skipping'
    }
  }
}

let schemaId := inputs.schema_mapping?.[resource]

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'No schema mapping for event type: {eventName}, skipping'
    }
  }
}

produceToWarehouseWebhooks(request.body, schemaId)""",
    inputs_schema=[
        {
            "type": "string",
            "key": "signing_secret",
            "label": "HTTP webhook signing key",
            "required": False,
            "secret": True,
            "hidden": False,
            "description": (
                "Your Mailgun account's HTTP webhook signing key, from Settings > API security. Used to "
                "verify the HMAC-SHA256 signature Mailgun sends on every delivery."
            ),
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the Mailgun signature will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Mailgun resource keys to ExternalDataSchema IDs",
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
