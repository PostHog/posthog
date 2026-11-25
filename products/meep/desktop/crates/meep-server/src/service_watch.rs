//! Observe advertised, argument-free read tools for a connected installation.
//! The account's workflow takes precedence when a matching push binding exists.
use crate::accounts::Account;
use anyhow::{Context, Result, ensure};
use meep_connectors::StateStore;
use meep_engine::Engine;
use meep_ingest::Event;
use meep_posthog::mcp::{Gateway, Server, Tool};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use uuid::Uuid;

pub(super) fn listing_tool(service: &Server) -> Option<&Tool> {
    service
        .tools
        .iter()
        .filter(|tool| {
            let name = tool.name.to_ascii_lowercase().replace('-', "_");
            tool.approval_state == "approved"
                && tool.annotations["readOnlyHint"] == true
                && tool.annotations["destructiveHint"] != true
                && tool.input_schema["required"]
                    .as_array()
                    .is_none_or(Vec::is_empty)
                && name.split('_').any(|word| word == "list")
        })
        .min_by_key(|tool| (!tool.name.contains("recent"), &tool.name))
}
fn push_binding(config: &Value, key: &str) -> bool {
    config["watches"].as_array().into_iter().flatten().any(|s| {
        s["watch"]["kind"] == "service"
            && s["watch"]["key"] == key
            && (s["mode"] == "push" || (s["mode"].is_null() && s["workflow"].is_string()))
    })
}

#[derive(Serialize, Deserialize)]
struct Observation {
    generation: u64,
    digest: String,
}

pub(super) async fn poll(
    engine: &Engine,
    a: &Account,
    checkpoints: &dyn StateStore,
    config: &Value,
) -> Result<()> {
    let Some(project) = &a.project else {
        return Ok(());
    };
    let mut keys = BTreeSet::new();
    for id in &a.public.grants {
        if let Ok(state) = engine.topic(*id) {
            keys.extend(
                state
                    .topic
                    .watches()
                    .filter(|w| {
                        w.connection == a.public.id
                            && w.kind == "service"
                            && !push_binding(config, &w.key)
                    })
                    .map(|w| w.key.clone()),
            );
        }
    }
    if keys.is_empty() {
        return Ok(());
    }
    let token = a
        .values
        .get("access_token")
        .context("PostHog needs sign-in")?;
    let gateway = Gateway::new(&project.origin, project.project)?;
    let services = gateway.available(token).await?;
    let mut failures = Vec::new();
    for key in keys {
        let result: Result<()> = async {
            let installation = Uuid::parse_str(&key)?;
            let service = services
                .iter()
                .find(|s| s.installation_id == installation)
                .context("Connected service is unavailable")?;
            let tool = listing_tool(service).context(
                "Configure a PostHog workflow or grant an argument-free read-only list tool",
            )?;
            let result = gateway
                .call(token, installation, &tool.name, &Default::default())
                .await?;
            ensure!(
                !result.is_error,
                "PostHog declined the connected service read"
            );
            let content = result
                .structured_content
                .unwrap_or(Value::Array(result.content));
            let body = serde_json::to_string(&content)?;
            let digest = format!("{:x}", Sha256::digest(body.as_bytes()));
            let checkpoint = serde_json::to_string(&(
                "topics/service",
                &a.public.id,
                &project.origin,
                project.project,
                installation,
                &tool.name,
            ))?;
            let old = checkpoints.load(&checkpoint)?;
            let previous = old
                .as_ref()
                .map(|v| serde_json::from_value::<Observation>(v.clone()))
                .transpose()?;
            if previous.as_ref().is_some_and(|v| v.digest == digest) {
                return Ok(());
            }
            let generation = previous.as_ref().map_or(0, |v| v.generation + 1);
            if previous.is_some() {
                let external_id = format!(
                    "{:x}",
                    Sha256::digest(serde_json::to_vec(&(&checkpoint, generation, &digest))?)
                );
                let excerpt = body.chars().take(2048).collect::<String>();
                engine
                    .ingest(Event {
                        connection: a.public.id.clone(),
                        kind: "service".into(),
                        channel: key.clone(),
                        external_id,
                        thread_hint: Some(format!("{installation}/{}", tool.name)),
                        author: service.name.clone(),
                        at: chrono::Utc::now(),
                        text: format!("{} · {} changed\n{excerpt}", service.name, tool.name),
                        attributes: json!({"tool":tool.name,"installation_id":installation}),
                    })
                    .await?;
            }
            checkpoints.commit(
                &checkpoint,
                old.as_ref(),
                &serde_json::to_value(Observation { generation, digest })?,
            )?;
            Ok(())
        }
        .await;
        if let Err(error) = result {
            log::warn!("Could not poll service watch {key}: {error:#}");
            failures.push(format!("{key}: {error:#}"));
        }
    }
    ensure!(
        failures.is_empty(),
        "Service watches failed: {}",
        failures.join("; ")
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tool(name: &str, policy: &str, annotations: Value, required: Value) -> Tool {
        Tool {
            name: name.into(),
            description: String::new(),
            input_schema: json!({"type":"object","required":required}),
            annotations,
            approval_state: policy.into(),
        }
    }

    #[test]
    fn only_approved_argument_free_nondestructive_read_lists_are_polled() {
        let readonly = json!({"readOnlyHint":true,"destructiveHint":false});
        let mut service = Server {
            installation_id: Uuid::new_v4(),
            name: "Fixture".into(),
            slug: "fixture".into(),
            tools: vec![
                tool("list_denied", "do_not_use", readonly.clone(), json!([])),
                tool("list_review", "needs_approval", readonly.clone(), json!([])),
                tool("list_missing_hint", "approved", json!({}), json!([])),
                tool(
                    "list_destructive",
                    "approved",
                    json!({"readOnlyHint":true,"destructiveHint":true}),
                    json!([]),
                ),
                tool(
                    "list_requires_argument",
                    "approved",
                    readonly.clone(),
                    json!(["id"]),
                ),
                tool("delete_fixture", "approved", readonly.clone(), json!([])),
            ],
        };
        assert!(listing_tool(&service).is_none());
        service
            .tools
            .push(tool("list_items", "approved", readonly, json!([])));
        assert_eq!(
            listing_tool(&service).map(|tool| tool.name.as_str()),
            Some("list_items")
        );
        service.tools.last_mut().unwrap().approval_state = "do_not_use".into();
        assert!(listing_tool(&service).is_none());
    }
}
