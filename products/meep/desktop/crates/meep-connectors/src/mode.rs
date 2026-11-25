use crate::{ValidateSecret, webhook::Webhook};
use anyhow::{Context, Result, ensure};
use meep_topic::Watch;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::HashSet;

/// Delivery method for one configured Topics watch.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum WatchMode {
    /// A PostHog workflow sends matching observations to the signed endpoint.
    Push,
    /// Poll an advertised native or connected PostHog MCP tool.
    Pull,
}

/// Supported modes in preference order. A configured workflow makes push the
/// default for an MCP source. A dedicated workflow webhook supports only push.
pub fn supported_modes(kind: &str, workflow_configured: bool) -> &'static [WatchMode] {
    use WatchMode::{Pull, Push};
    match (kind, workflow_configured) {
        ("webhook", _) => &[Push],
        ("mcp" | "posthog", true) => &[Push, Pull],
        ("mcp" | "posthog", false) => &[Pull],
        _ => &[],
    }
}

pub(super) struct Plan {
    pub webhook: Option<Webhook>,
    pub pull: Option<Value>,
}

pub(super) fn plan(kind: &str, mut config: Value, secret: &ValidateSecret<'_>) -> Result<Plan> {
    if kind == "webhook" {
        return Ok(Plan {
            webhook: Some(Webhook::new(config, secret("secret")?)?),
            pull: None,
        });
    }
    ensure!(
        matches!(kind, "posthog" | "mcp"),
        "unknown connector kind {kind}"
    );
    let connection = config["connection"].clone();
    let fields = config
        .as_object_mut()
        .context("expected connector config object")?;
    let auth = fields.remove("webhook_auth");
    let watches: Vec<Value> =
        serde_json::from_value(fields.remove("watches").context("missing watches")?)?;
    let idle = watches.is_empty();
    let mut ids = HashSet::new();
    let mut push = vec![];
    let mut pull = vec![];
    for mut entry in watches {
        let fields = entry
            .as_object_mut()
            .context("expected watch configuration object")?;
        let watch: Watch =
            serde_json::from_value(fields.get("watch").context("missing watch")?.clone())?;
        ensure!(ids.insert(watch.id), "duplicate watch {}", watch.id);
        let workflow: Option<String> = fields
            .remove("workflow")
            .map(serde_json::from_value)
            .transpose()?;
        if let Some(id) = &workflow {
            ensure!(!id.trim().is_empty(), "workflow ID must be nonempty");
        }
        let modes = supported_modes(kind, workflow.is_some());
        let mode = fields
            .remove("mode")
            .map(serde_json::from_value)
            .transpose()?
            .unwrap_or(modes[0]);
        match mode {
            WatchMode::Push => push.push(watch),
            WatchMode::Pull => pull.push(entry),
        }
    }
    let webhook = if push.is_empty() {
        None
    } else {
        let options =
            json!({"connection":connection,"watches":push,"auth":auth,"preset":"posthog_workflow"});
        Some(Webhook::new(
            options,
            secret("secret").context("push watch needs the connection's workflow secret")?,
        )?)
    };
    let has_pull = idle || !pull.is_empty();
    config["watches"] = Value::Array(pull);
    Ok(Plan {
        webhook,
        pull: has_pull.then_some(config),
    })
}
