from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-github",
    name="GitHub warehouse source webhook",
    description="Receive GitHub webhook events for data warehouse ingestion",
    icon_url="/static/services/github.png",
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

  let signatureHeader := request.headers['x-hub-signature-256']

  if (empty(signatureHeader)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature',
      }
    }
  }

  // GitHub sends sha256=<hex>, where <hex> is the HMAC-SHA256 of the raw
  // request body keyed by the webhook secret. No timestamp is involved.
  let computedSignature := concat('sha256=', sha256HmacChainHex([inputs.signing_secret, request.stringBody]))

  if (computedSignature != signatureHeader) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Bad signature',
      }
    }
  }
}

// Event type comes from the X-GitHub-Event header, not the body.
let eventType := request.headers['x-github-event']

if (empty(eventType)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No event type found, skipping'
    }
  }
}

// Multi-repo sources key their mapping by 'owner/repo.event' (the payload's
// repository.full_name, lowercased) so two repos' events route to their own schemas.
// The bare event-type key remains as the fallback for legacy single-repo mappings.
let repoFullName := request.body?.repository?.full_name
let schemaId := null
if (not empty(repoFullName)) {
  schemaId := inputs.schema_mapping?.[concat(lower(repoFullName), '.', eventType)]
}
// The bare event-type key belongs to the legacy repository only. Restricting the fallback to the
// legacy repo (or to functions with no legacy binding — pure multi-repo mappings have no bare key,
// and pre-multi-repo functions predate this input) stops a secondary repo whose qualified schema
// is disabled/removed from leaking its events into the legacy repo's schema.
if (empty(schemaId) and (empty(inputs.legacy_repository) or lower(repoFullName) = lower(inputs.legacy_repository))) {
  schemaId := inputs.schema_mapping?.[eventType]
}

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'No schema mapping for event type: {eventType}, skipping'
    }
  }
}

// The poll endpoints land the job/run objects themselves, so the webhook lands the
// same nested object — request.body.workflow_job / request.body.workflow_run — rather
// than the whole event envelope. GitHub uses one object schema per resource, so the
// nested webhook object matches the REST "list jobs for a workflow run" response shape.
let row := request.body?.[eventType]

// pull_request_review does not nest the object under the event-type key: the review is at
// body.review and its PR at body.pull_request. Reshape so webhook rows match poll rows, which
// carry pr_number injected from the parent PR. The source-webhooks consumer substitutes the
// current template bytecode by template_id at request time, so existing functions run this code
// too; a source whose schema_mapping predates an event type no-ops on it above.
if (eventType = 'pull_request_review') {
  let review := request.body?.review
  let pullRequest := request.body?.pull_request
  if (empty(review) or empty(pullRequest)) {
    return {
      'httpResponse': {
        'status': 200,
        'body': 'No review or pull_request object in payload, skipping'
      }
    }
  }
  // The poll path drops reviews without submitted_at (unsubmitted drafts); mirror it so
  // the partition/cursor column stays non-null.
  if (empty(review?.submitted_at)) {
    return {
      'httpResponse': {
        'status': 200,
        'body': 'Review has no submitted_at, skipping'
      }
    }
  }
  // REST returns uppercase review states ('APPROVED') while webhook payloads use lowercase
  // ('approved'); normalize to the REST shape so a fallback poll never mixes casings in one column.
  if (not empty(review?.state)) {
    review.state := upper(review.state)
  }
  review.pr_number := pullRequest?.number
  row := review
}

if (empty(row)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'No {eventType} object in payload, skipping'
    }
  }
}

produceToWarehouseWebhooks(row, schemaId)""",
    inputs_schema=[
        {
            "type": "string",
            "key": "signing_secret",
            "label": "Signing secret",
            "required": False,
            "secret": True,
            "hidden": False,
            "description": "Used to validate the webhook came from GitHub. Set as the webhook's Secret in the repo's Settings > Webhooks.",
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the X-Hub-Signature-256 header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps GitHub event types to ExternalDataSchema IDs. Keys are either a bare event type (workflow_job, workflow_run, pull_request_review) for legacy single-repo sources, or 'owner/repo.event_type' for multi-repo sources.",
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
        {
            "type": "string",
            "key": "legacy_repository",
            "label": "Legacy repository",
            "description": "For multi-repo GitHub sources, the 'owner/repo' whose schema rows keep bare event keys. The bare-key fallback only routes events from this repository, so other repos can't leak into it. Empty for single-repo or pure multi-repo sources.",
            "required": False,
            "secret": False,
            "hidden": True,
        },
    ],
)
