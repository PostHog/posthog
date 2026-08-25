from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-pipedrive",
    name="Pipedrive warehouse source webhook",
    description="Receive Pipedrive webhook events for data warehouse ingestion",
    icon_url="/static/services/pipedrive.png",
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

if (not inputs.bypass_auth_check) {
  if (empty(inputs.http_auth_user) or empty(inputs.http_auth_password)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'HTTP auth credentials not configured',
      }
    }
  }

  let providedHeader := request.headers['authorization']

  if (empty(providedHeader)) {
    return {
      'httpResponse': {
        'status': 401,
        'body': 'Missing authorization header',
      }
    }
  }

  // Pipedrive signs nothing; it sends back the HTTP basic credentials set on the subscription.
  let expectedHeader := concat('Basic ', base64Encode(concat(inputs.http_auth_user, ':', inputs.http_auth_password)))

  if (providedHeader != expectedHeader) {
    return {
      'httpResponse': {
        'status': 401,
        'body': 'Bad authorization header',
      }
    }
  }
}

let meta := request.body.meta

if (empty(meta)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No meta block found, skipping'
    }
  }
}

// Only v2 deliveries carry the entity under `data` in the shape the polled tables use. A v1.0
// webhook would put a differently named payload in `current`, so reject it loudly instead of
// merging mismatched rows.
if (meta.version != '2.0') {
  return {
    'httpResponse': {
      'status': 400,
      'body': 'Only Pipedrive webhooks v2 deliveries are supported',
    }
  }
}

// Deletions carry no object to merge, and the warehouse table keeps the last known version of a
// row rather than tracking removals.
if (meta.action = 'delete') {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'Delete event, skipping'
    }
  }
}

let entity := meta.entity

if (empty(entity)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No entity found, skipping'
    }
  }
}

let schemaId := inputs.schema_mapping?.[entity]

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'No schema mapping for entity: {entity}, skipping'
    }
  }
}

produceToWarehouseWebhooks(request.body, schemaId)""",
    inputs_schema=[
        {
            "type": "string",
            "key": "http_auth_user",
            "label": "HTTP auth username",
            "required": False,
            "secret": False,
            "hidden": False,
            "description": (
                "The HTTP auth username set on the Pipedrive webhook. Pipedrive sends it back on "
                "every delivery as HTTP basic auth, which is how PostHog verifies the delivery."
            ),
        },
        {
            "type": "string",
            "key": "http_auth_password",
            "label": "HTTP auth password",
            "required": False,
            "secret": True,
            "hidden": False,
            "description": (
                "The HTTP auth password set on the Pipedrive webhook. PostHog rejects deliveries "
                "whose basic auth credentials do not match."
            ),
        },
        {
            "type": "boolean",
            "key": "bypass_auth_check",
            "label": "Bypass HTTP auth check",
            "description": "If set, the Authorization header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Pipedrive entity names to ExternalDataSchema IDs",
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
