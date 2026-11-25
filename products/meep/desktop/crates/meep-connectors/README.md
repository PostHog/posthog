# meep-connectors

Every source flows through the person's PostHog account. PostHog Workflows owns the triggers and sends matching observations to one authenticated endpoint. A watch without a workflow polls PostHog's MCP server for native data or its installation gateway for connected services. Credentials, project selection and tool approvals stay with the account.

`ConnectorFactory::build(kind, config, secrets)` returns a boxed `LiveConnector`. It implements `meep_ingest::Connector` and reports health. HTTP 401 marks an account expired. Other polling failures include the account and cause.

## Receive a workflow delivery

A PostHog workflow posts its observation to `/v1/ingest/{connection}`. Pass the untouched bytes and request headers to the connector. After durable engine ingestion, acknowledge the event IDs so workflow retries can receive HTTP 204 without repeating delivery.

```rust
use std::{collections::BTreeMap, sync::Arc};
use http::HeaderMap;
use meep_connectors::{ConnectorFactory, StoreState};
use serde_json::json;

# fn main() -> anyhow::Result<()> {
let db = meep_store::Connection::open_in_memory()?;
let factory = ConnectorFactory::new(Arc::new(StoreState::new(db)?));
let config = json!({"connection":"analytics","preset":"posthog_workflow",
    "auth":{"kind":"shared_secret","header":"x-meep-secret"}});
let secrets = BTreeMap::from([("secret".into(), "example-only".into())]);
let connector = factory.build("webhook", config, &secrets)?;
let mut headers = HeaderMap::new();
headers.insert("x-meep-secret", "example-only".parse()?);
let body = serde_json::to_vec(&json!({
    "source":{"service":"posthog","kind":"insight","key":"signups"},
    "author":"Signup alert","at":"2026-01-01T10:00:00Z","text":"Signups reached 100.",
    "external_id":"workflow-run-23","thread_hint":"signups",
    "attributes":{"fact":"Signups reached 100."}
}))?;
let events = connector.receive_webhook(&headers, &body)?;
assert_eq!(events[0].channel, "signups");
// In a host, ingest these events durably before acknowledging them.
connector.acknowledge_webhook(&events)?;
assert!(connector.receive_webhook(&headers, &body)?.is_empty());
# Ok(())
# }
```

See [Connector configuration](configuration.md) for the workflow payload, watch modes, authentication and MCP polling templates.
