//! Read-only data access for rendered workspace views.
use super::{Gateway, McpClient};
use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use uuid::Uuid;

const NATIVE: &[&str] = &[
    "insights-list",
    "insight-get",
    "feature-flag-get-all",
    "feature-flag-get-definition",
    "event-definitions-list",
    "query-run",
];
/// Whether a native PostHog tool is available to rendered views.
pub fn native_allowed(name: &str) -> bool {
    NATIVE.contains(&name.replace('_', "-").as_str())
}

/// Execute a native or approved installation read under the signed-in account.
pub async fn read_source(
    client: McpClient,
    origin: &str,
    project: u64,
    token: &str,
    source: &str,
    tool: &str,
    args: &Value,
) -> Result<Value> {
    let result = if source == "posthog" {
        ensure!(native_allowed(tool), "Unsupported PostHog read operation");
        client
            .initialize(token)
            .await?
            .call(tool, args.clone())
            .await?
    } else {
        let id = source.parse::<Uuid>()?;
        let gateway = Gateway::new(origin, project)?;
        ensure!(
            gateway
                .available(token)
                .await?
                .iter()
                .any(|s| s.installation_id == id
                    && s.tools.iter().any(|t| t.name == tool
                        && t.approval_state == "approved"
                        && t.annotations["readOnlyHint"] == true)),
            "Read access unavailable for this tool"
        );
        gateway
            .call(
                token,
                id,
                tool,
                args.as_object().context("Expected arguments")?,
            )
            .await?
    };
    ensure!(!result.is_error, "PostHog declined the read operation");
    if let Some(value) = result.structured_content {
        return Ok(value);
    }
    if let Some(text) = result.content.first().and_then(|v| v["text"].as_str()) {
        return Ok(serde_json::from_str(text)
            .or_else(|_| toon_format::decode_strict(text))
            .unwrap_or_else(|_| json!(text)));
    }
    Ok(json!(result.content))
}
