use crate::accounts::Accounts;
use anyhow::{Context, Result, ensure};
use meep_posthog::mcp::{DEFAULT_ENDPOINT, Gateway, McpClient, McpSession, McpTool, ToolResult};
use meep_wire::WatchableSource;
use serde_json::{Value, json};
use std::collections::BTreeSet;

pub(super) async fn discover(
    accounts: &Accounts,
    topic: Option<&meep_topic::Topic>,
) -> Result<Vec<WatchableSource>> {
    let mut sources = Vec::new();
    let mut incomplete = false;
    for account in accounts.all() {
        if topic.is_some_and(|t| !account.public.grants.contains(&t.id)) {
            continue;
        }
        let Some(project) = &account.project else {
            continue;
        };
        let token = account
            .values
            .get("access_token")
            .context("Missing account token")?;
        let config: Value = account
            .values
            .get("config")
            .map(|s| serde_json::from_str(s))
            .transpose()?
            .unwrap_or_default();
        let local = format!("{}/mcp", project.origin.trim_end_matches('/'));
        let endpoint =
            config["mcp_endpoint"]
                .as_str()
                .unwrap_or_else(|| match project.origin.as_str() {
                    "https://us.posthog.com" | "https://eu.posthog.com" => DEFAULT_ENDPOINT,
                    _ => &local,
                });
        let gateway = Gateway::new(&project.origin, project.project)?;
        let client = McpClient::new(endpoint, Some(project.project))?;
        let (native, services) = tokio::join!(
            async {
                let mut session = client.initialize(token).await?;
                let tools = session.list_tools().await?;
                Ok::<_, anyhow::Error>((session, tools))
            },
            gateway.available(token)
        );
        if let Ok((mut session, tools)) = native {
            for (name, kind) in [
                ("insights-list", "insight"),
                ("feature-flag-get-all", "flag"),
            ] {
                if let Some(tool) = tools
                    .iter()
                    .find(|tool| tool.name.replace('_', "-") == name)
                {
                    match resources(&mut session, tool, &account.public.id, kind).await {
                        Ok(resources) => sources.extend(resources),
                        Err(_) => incomplete = true,
                    }
                }
            }
        } else {
            incomplete = true;
        }
        let services = match services {
            Ok(services) => services,
            Err(_) => {
                incomplete = true;
                continue;
            }
        };
        for service in services {
            if service
                .tools
                .iter()
                .any(|tool| tool.approval_state == "approved")
            {
                let supported_modes = if crate::service_watch::listing_tool(&service).is_some() {
                    vec!["pull".into(), "push".into()]
                } else {
                    vec!["push".into()]
                };
                sources.push(WatchableSource {
                    connection: account.public.id.clone(),
                    kind: "service".into(),
                    key: service.installation_id.to_string(),
                    label: service.name,
                    supported_modes,
                });
            }
        }
    }
    ensure!(
        !incomplete || !sources.is_empty(),
        "Could not discover PostHog sources"
    );
    if incomplete {
        log::warn!("Some PostHog sources could not be discovered");
    }
    sources.sort_by(|a, b| a.label.cmp(&b.label).then(a.key.cmp(&b.key)));
    Ok(sources)
}

async fn resources(
    session: &mut McpSession,
    tool: &McpTool,
    connection: &str,
    kind: &str,
) -> Result<Vec<WatchableSource>> {
    let mut sources = vec![];
    let mut keys = BTreeSet::new();
    let mut offset = 0;
    for _ in 0..1000 {
        let mut args = json!({});
        for (field, n) in [("limit", 100), ("offset", offset)] {
            if let Some(schema) = tool.input_schema["properties"].get(field) {
                args[field] = if schema["type"] == "string" {
                    json!(n.to_string())
                } else {
                    json!(n)
                };
            }
        }
        let page = decode(session.call(&tool.name, args).await?)?;
        let rows = page
            .as_array()
            .or_else(|| {
                ["results", "data", "items", "flags", "insights"]
                    .iter()
                    .find_map(|key| page[key].as_array())
            })
            .context("Unrecognized PostHog resource list")?;
        let before = keys.len();
        for r in rows {
            let key = r
                .get("id")
                .and_then(Value::as_u64)
                .map(|n| n.to_string())
                .or_else(|| {
                    r[if kind == "flag" { "key" } else { "short_id" }]
                        .as_str()
                        .map(str::to_owned)
                })
                .context("Missing resource ID")?;
            if !keys.insert(key.clone()) {
                continue;
            }
            let label = ["name", "derived_name", "key", "short_id"]
                .iter()
                .find_map(|k| r[k].as_str().filter(|s| !s.is_empty()))
                .unwrap_or(&key)
                .to_owned();
            sources.push(WatchableSource {
                connection: connection.into(),
                kind: kind.into(),
                key,
                label,
                supported_modes: vec!["pull".into()],
            });
        }
        let more = page.get("next").is_some_and(|v| !v.is_null())
            || page["hasMore"] == true
            || rows.len() == 100;
        if !more || rows.is_empty() || tool.input_schema["properties"].get("offset").is_none() {
            return Ok(sources);
        }
        ensure!(keys.len() > before, "Resource pagination repeated");
        offset += rows.len();
    }
    anyhow::bail!("Resource discovery exceeded 1,000 pages")
}

fn decode(result: ToolResult) -> Result<Value> {
    ensure!(!result.is_error, "PostHog declined resource discovery");
    if let Some(v) = result.structured_content {
        return Ok(v);
    }
    let text = result
        .content
        .iter()
        .find_map(|part| part["text"].as_str())
        .context("Missing resource list")?;
    serde_json::from_str(text)
        .or_else(|_| toon_format::decode_strict(text))
        .context("Invalid resource list")
}
