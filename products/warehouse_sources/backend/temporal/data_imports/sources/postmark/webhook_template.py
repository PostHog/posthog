from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# Postmark does not sign webhook deliveries, but the Webhooks API pins static headers onto a
# webhook. `create_webhook` attaches a generated secret in the x-posthog-webhook-secret header,
# which this template requires on every delivery. A manually created webhook has to configure
# the same header (via the Webhooks API or the webhook editor) — there is no bypass, so an
# unauthenticated delivery is always rejected.
template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-postmark",
    name="Postmark warehouse source webhook",
    description="Receive Postmark webhook events for data warehouse ingestion",
    icon_url="/static/services/postmark.png",
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
      'status': 400,
      'body': 'Webhook secret not configured',
    }
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

let recordType := request.body.RecordType

// Spam complaints are bounce records too, so both land in the bounces table. Anything else is
// acknowledged and dropped rather than errored, so an over-broad webhook can't retry-storm us.
if (recordType != 'Bounce' and recordType != 'SpamComplaint') {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'Unhandled record type, skipping'
    }
  }
}

let schemaId := inputs.schema_mapping?.['Bounce']

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No schema mapping for bounces, skipping'
    }
  }
}

produceToWarehouseWebhooks(request.body, schemaId)""",
    inputs_schema=[
        {
            "type": "string",
            "key": "signing_secret",
            "label": "Webhook secret",
            "required": True,
            "secret": True,
            "hidden": False,
            "description": "Shared secret sent by Postmark in the x-posthog-webhook-secret header, used to verify the delivery came from your webhook",
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Postmark webhook record types to ExternalDataSchema IDs",
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
