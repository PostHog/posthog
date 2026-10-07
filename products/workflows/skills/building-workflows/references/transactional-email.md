# Backend-triggered transactional email

Use a workflow for an application-triggered receipt or notification when the backend authorizes who receives it. A browser's public PostHog capture key is not authorization to send to an arbitrary email address. Do not expose the webhook secret in client code or turn a client-supplied recipient into a send without checking it against the application's authenticated user and business operation.

## Configure a draft

Choose a verified email sender in the project and use its integration ID. The synthetic `123` below is a placeholder, not a usable sender. Store a generated webhook secret in backend secret storage and configure the trigger's `auth_header` with the same full value. `Authorization` must match exactly; leaving `auth_header` empty disables this check. Do not paste real secrets into chat, logs, or examples.

The zero timestamps are authoring placeholders. Create this graph with `workflows-create`, replacing the sender ID and secret through the customer's secure configuration path:

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

For an editable library design, use the `designing-email-templates` skill. Set the saved template's UUID in `config.template_uuid` and omit body keys from `inputs.email.value` so the server copies the saved content at creation. Keep `to` and `from` on the action. Later library edits do not update this snapshot.

The source uses Hog expressions with single braces to map `request.body` into event properties. The email uses Liquid with double braces. `recipient_email` need not be the person's profile email; `distinct_id` identifies the application subject. Send only necessary data. Webhook payloads and invocation data may be retained by PostHog even though a workflow webhook uses the mapped event as trigger data rather than capturing it as an analytics event. Avoid sensitive receipt contents or credentials in the body.

## Call from the authorized backend

After mock testing and the user's explicit approval to enable, use the webhook URL shown on the saved workflow's trigger. Its path is `/public/webhooks/<workflow UUID>` on the deployment's webhook host, not the project API route. Keep the URL and Authorization value in backend configuration. A backend POST uses `Content-Type: application/json`, the configured `Authorization` value, and a body such as:

```json
{
  "distinct_id": "example-user-42",
  "recipient_email": "recipient@example.com",
  "receipt_number": "EXAMPLE-42"
}
```

Resolve the recipient from trusted application records. Check that the operation permits this notification before making the request. For an optional application notification, check the application's notification preference too. A public endpoint that forwards arbitrary request bodies with the backend secret defeats this authorization boundary.

In an existing Convex application, the same pattern can live in an `internalAction`: pass an application record ID, use `ctx.runQuery` with an internal query to load the authorized recipient and app-owned preference, then POST with `fetch`. Store the webhook URL and Authorization value in Convex deployment environment variables and read them only in backend code. Schedule the internal action from the authorized application mutation with `ctx.scheduler.runAfter`. This needs no new package or component and adds no delivery guarantee. Do not accept a raw recipient from a public action.

## Policy and verification

- Transactional policy describes the message's purpose. Set `message_category_type: "transactional"` explicitly for genuine transactional messages; triggering from the backend alone does not make marketing transactional.
- Optional application notification preferences belong to the application. Transactional sends bypass PostHog marketing opt-outs, so check those app-owned preferences before the webhook request.
- Suppression protects addresses that should not receive mail, including bounces and complaints. Transactional classification does not bypass suppression.
- Marketing messages remain marketing, with category/global opt-outs and unsubscribe links. Do not relabel them to avoid preferences.

Keep `mock_async_functions` at its default `true` in `workflows-test-run`. Use sample `globals.event` with `event: "receipt_ready"`, `distinct_id: "example-user-42"`, and `properties` containing the synthetic recipient and receipt number. Walk through `nextActionId` to the email and exit. This checks the mapped-event path and rendering, not webhook Authorization or request mapping. Never disable mocks merely to validate this recipe.

Distinguish each result when reporting proof:

- A mock test proves the selected path and rendered inputs, with no real send.
- Webhook acceptance means the trigger accepted the request and queued the workflow, not that an email was sent.
- Provider acceptance means the provider accepted a send request, not that the recipient received it.
- Delivery events, when available, report delivery separately; provider acceptance is not proof of inbox placement.

Use `workflows-list-invocations`, `workflows-get-invocation`, and `workflows-logs` to inspect failures. This webhook has no caller-supplied idempotency contract or guaranteed retry protocol. Repeating a request can create another run and another send. On timeout or an ambiguous response, reconcile the invocation before deciding whether to retry; do not promise exactly-once sending.
