# Backend-triggered transactional email

Use this recipe for a receipt or application notification triggered by an authorized backend.

## 1. Authorize the notification

Resolve the recipient and `distinct_id` from trusted application records. Verify that the authenticated user and business operation permit the notification. A browser's public PostHog capture key does not authorize arbitrary-recipient sending.

Classify the message before configuring the email action:

- Transactional policy describes the message's purpose. Set `message_category_type: "transactional"` for genuine transactional messages.
- Optional application notification preferences belong to the application. Check them before calling the webhook; transactional sends bypass PostHog marketing opt-outs.
- Suppression protects addresses that should not receive mail, including bounces and complaints. It applies to transactional messages too.
- Marketing messages use marketing categories, category/global opt-outs, and unsubscribe links. A backend trigger does not change their purpose.

`recipient_email` can differ from the person's profile email. Send only the fields the workflow needs. PostHog may retain webhook payloads and invocation data even though a workflow webhook uses the mapped event as trigger data rather than capturing an analytics event. Keep sensitive receipt contents and credentials out of the body.

Continue when the application has authorized the recipient and message purpose, including any optional notification preference.

## 2. Configure a draft

Choose a verified email sender in the project. Replace the synthetic integration ID `123` below with its ID. Store a generated webhook secret in backend secret storage and configure `auth_header` with the same full value. `Authorization` must match exactly; an empty `auth_header` allows unauthenticated requests. Keep the secret in backend configuration, outside client code, chat, and logs.

Create this graph with `workflows-create`, replacing the sender ID and secret through the customer's secure configuration path. The zero timestamps are authoring placeholders.

```json
{
  "name": "Receipt notification",
  "exit_condition": "exit_only_at_end",
  "actions": [
    {
      "id": "trigger_node",
      "name": "Authorized receipt request",
      "type": "trigger",
      "config": {
        "type": "webhook",
        "template_id": "template-source-webhook",
        "inputs": {
          "event": {
            "value": "receipt_ready"
          },
          "distinct_id": {
            "value": "{request.body.distinct_id}"
          },
          "properties": {
            "value": {
              "recipient_email": "{request.body.recipient_email}",
              "receipt_number": "{request.body.receipt_number}"
            }
          },
          "auth_header": {
            "value": "Bearer REPLACE_WITH_BACKEND_SECRET"
          },
          "method": {
            "value": "POST"
          },
          "debug": {
            "value": false
          }
        }
      },
      "description": "",
      "created_at": 0,
      "updated_at": 0
    },
    {
      "id": "email_1",
      "name": "Send receipt",
      "type": "function_email",
      "config": {
        "template_id": "template-email",
        "message_category_type": "transactional",
        "tracking_enabled": false,
        "inputs": {
          "email": {
            "value": {
              "to": {
                "email": "{{ event.properties.recipient_email }}",
                "name": ""
              },
              "from": {
                "integrationId": 123
              },
              "subject": "Receipt {{ event.properties.receipt_number }}",
              "html": "<p>Your receipt {{ event.properties.receipt_number }} is ready.</p>",
              "text": "Your receipt {{ event.properties.receipt_number }} is ready."
            }
          }
        }
      },
      "description": "",
      "created_at": 0,
      "updated_at": 0
    },
    {
      "id": "exit_node",
      "name": "Done",
      "type": "exit",
      "config": {},
      "description": "",
      "created_at": 0,
      "updated_at": 0
    }
  ],
  "edges": [
    {
      "from": "trigger_node",
      "to": "email_1",
      "type": "continue",
      "index": 0
    },
    {
      "from": "email_1",
      "to": "exit_node",
      "type": "continue",
      "index": 0
    }
  ]
}
```

The webhook uses Hog expressions with single braces to map `request.body` into event properties. The email uses Liquid with double braces.

For an editable library design, use the `designing-email-templates` skill. Set its UUID in `config.template_uuid` and omit body keys from `inputs.email.value` so the server copies the saved content at creation. Keep `to` and `from` on the action. Later library edits do not update this snapshot.

The draft is configured when its sender is verified and its Authorization value matches backend secret storage.

## 3. Prove the mocked path

Keep `mock_async_functions` at its default `true` in `workflows-test-run`. Use sample `globals.event` with `event: "receipt_ready"`, `distinct_id: "example-user-42"`, and `properties` containing `recipient_email: "recipient@example.com"` and `receipt_number: "EXAMPLE-42"`.

Walk through `nextActionId` to the email and exit. Check that the trace selects the email step and renders the expected recipient and subject. This proves the mapped-event path without a real send. It does not exercise webhook Authorization or request-body mapping.

Continue when every step on this path passes and the rendered recipient and subject match the sample event. Keep mocks enabled throughout this check.

## 4. Enable and call from the backend

Obtain the user's explicit approval before enabling. Use the webhook URL shown on the saved workflow's trigger. Its path is `/public/webhooks/<workflow UUID>` on the deployment's webhook host. Store the URL and Authorization value in backend configuration.

POST with `Content-Type: application/json`, the configured `Authorization` value, and the authorized body:

```json
{
  "distinct_id": "example-user-42",
  "recipient_email": "recipient@example.com",
  "receipt_number": "EXAMPLE-42"
}
```

Forward only the authorized fields from step 1. A public endpoint that forwards arbitrary request bodies with the backend secret defeats this boundary.

### Optional Convex caller

In an existing Convex application, schedule an `internalAction` from the authorized mutation with `ctx.scheduler.runAfter`. Pass an application record ID. Use `ctx.runQuery` with an internal query to load the recipient and app-owned preference, then POST with `fetch`. Read the webhook URL and Authorization value from Convex deployment environment variables in backend code. This uses existing Convex functionality and adds no delivery guarantee.

## 5. Reconcile the outcome

Report the stage supported by the evidence:

- A mock test proves the selected path and rendered inputs, with no real send.
- Webhook acceptance means the trigger accepted the request and queued the workflow.
- Provider acceptance means the provider accepted a send request.
- Delivery events, when available, report delivery separately. Provider acceptance does not prove inbox placement.

Use `workflows-list-invocations`, `workflows-get-invocation`, and `workflows-logs` to inspect the send outcome or failure. The webhook has no caller-supplied idempotency contract or guaranteed retry protocol. Repeating a request can create another run and send. After a timeout or ambiguous response, reconcile the invocation before deciding whether to retry.

Finish with the observed stage and any unresolved failure. Claim delivery only when delivery evidence supports it.
