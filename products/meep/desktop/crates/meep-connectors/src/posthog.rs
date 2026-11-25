use super::{Checkpoint, source_key, validate_watches};
use anyhow::{Context, Result, bail, ensure};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use chrono::Utc;
use meep_ingest::{Event, RoutedEvent};
use meep_posthog::api::ProjectEndpoint;
use meep_posthog::mcp::{DEFAULT_ENDPOINT, McpClient, McpSession, McpTool, ToolResult};
use meep_topic::Watch;
use serde::{Deserialize, Serialize};
use serde_json::{Number, Value, json};
use std::{
    collections::HashMap,
    time::{Duration, Instant},
};
use tokio::sync::Mutex;
use uuid::Uuid;

// MCP's SQL tool can serve a cached result for a moving now() window. A stable
// bucket shares results between fast polls but advances often enough to observe
// threshold crossings at the host's normal polling cadence.
const EVENT_QUERY_BUCKET_SECONDS: i64 = 30;

fn event_query(name: &str, seconds: u32, timestamp: i64) -> String {
    let name = STANDARD.encode(name.as_bytes());
    let bucket = timestamp.div_euclid(EVENT_QUERY_BUCKET_SECONDS);
    format!(
        "SELECT count() AS meep_count FROM events WHERE event = base64Decode('{name}') AND timestamp >= now() - toIntervalSecond({seconds}) AND timestamp <= now() AND {bucket} = {bucket}"
    )
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Config {
    connection: String,
    // The host may also supply the account's API origin for its other capabilities.
    origin: Option<String>,
    mcp_endpoint: Option<String>,
    project: Option<u64>,
    #[serde(default)]
    fresh_insights: bool,
    watches: Vec<Subscription>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Subscription {
    watch: Watch,
    resource_id: Option<u64>,
    threshold: Option<Number>,
    window_seconds: Option<u32>,
    result_pointer: Option<String>,
}

pub(super) struct PostHog {
    project: (String, Option<u64>),
    client: McpClient,
    session: Mutex<Option<Box<McpSession>>>,
    token: String,
    watches: Vec<Subscription>,
    fresh_insights: Option<ProjectEndpoint>,
    fresh_results: Mutex<HashMap<String, (Instant, Value)>>,
}

impl PostHog {
    pub(super) fn new(config: Value, token: String) -> Result<Self> {
        let config: Config =
            serde_json::from_value(config).context("invalid PostHog configuration")?;
        validate_watches(&config.connection, config.watches.iter().map(|s| &s.watch))?;
        for sub in &config.watches {
            match sub.watch.kind.as_str() {
                "insight" => {
                    sub.validate_resource()?;
                    if let Some(pointer) = &sub.result_pointer {
                        crate::mapping::validate_pointer(pointer)?;
                    }
                    ensure!(
                        sub.delta_threshold() >= 0.,
                        "insight threshold must be nonnegative"
                    );
                }
                "flag" => {
                    sub.validate_resource()?;
                }
                "event" => {
                    ensure!(
                        sub.count_threshold().is_some(),
                        "event threshold must be a positive integer"
                    );
                    ensure!(
                        sub.window_seconds.is_some_and(|n| n > 0),
                        "event window_seconds must be positive"
                    );
                }
                kind => bail!("unknown PostHog watch kind {kind}"),
            }
        }
        let endpoint = config
            .mcp_endpoint
            .unwrap_or_else(|| DEFAULT_ENDPOINT.into());
        let fresh_insights = if config.fresh_insights {
            Some(ProjectEndpoint::new(
                config
                    .origin
                    .as_deref()
                    .context("fresh insights require an API origin")?,
                config.project.context("fresh insights require a project")?,
                "query",
            )?)
        } else {
            None
        };
        Ok(Self {
            fresh_insights,
            fresh_results: Mutex::new(HashMap::new()),
            client: McpClient::new(&endpoint, config.project)?,
            project: (endpoint, config.project),
            session: Mutex::default(),
            token,
            watches: config.watches,
        })
    }

    pub(super) async fn poll(
        &self,
        previous: &Checkpoint,
        state: &mut Checkpoint,
    ) -> Result<(Vec<RoutedEvent>, Option<anyhow::Error>)> {
        let mut session = self.session.lock().await;
        if session.is_none() {
            *session = Some(Box::new(self.client.initialize(&self.token).await?));
        }
        let result = self
            .poll_session(
                session
                    .as_mut()
                    .context("missing initialized MCP session")?,
                previous,
                state,
            )
            .await;
        if result.is_err() {
            *session = None;
        }
        result
    }

    async fn poll_session(
        &self,
        session: &mut McpSession,
        previous: &Checkpoint,
        state: &mut Checkpoint,
    ) -> Result<(Vec<RoutedEvent>, Option<anyhow::Error>)> {
        let tools = session.list_tools().await?;
        let mut events = Vec::new();
        let mut failures = Vec::new();
        let mut succeeded = 0;
        for sub in &self.watches {
            let watch = &sub.watch;
            let value = match self.observe(sub, session, &tools).await {
                Ok(value) => value,
                Err(error) => {
                    // Keep the last successful value for this watch so recovery
                    // compares against it, while allowing other watches to advance.
                    if let Some(old) = previous.observations.get(&watch.id) {
                        state.observations.insert(watch.id, old.clone());
                    }
                    failures.push((format!("{} {}", watch.kind, watch.key), error));
                    continue;
                }
            };
            succeeded += 1;
            let source = source_key((
                "posthog",
                &self.project,
                &watch.kind,
                &watch.key,
                sub.resource_id,
                sub.window_seconds,
                &sub.result_pointer,
            ))?;
            let old = previous.value(watch.id, &source);
            if let Some(fact) = sub.change(old, &value)? {
                events.push(RoutedEvent {
                    event: Event {
                        connection: watch.connection.clone(),
                        kind: watch.kind.clone(),
                        channel: watch.key.clone(),
                        external_id: Uuid::new_v4().to_string(),
                        at: Utc::now(),
                        thread_hint: Some(format!(
                            "{}/{}/{}",
                            watch.connection, watch.kind, watch.key
                        )),
                        author: "PostHog".into(),
                        text: fact.clone(),
                        attributes: json!({"old":old,"new":value,"fact":fact}),
                    },
                    watch: Some(watch.id),
                });
            }
            state.record(watch.id, source, value);
        }
        if succeeded == 0 && !failures.is_empty() {
            let (watch, error) = failures.remove(0);
            return Err(error.context(format!("reading {watch}")));
        }
        let warning = if failures.is_empty() {
            None
        } else {
            let detail = failures
                .iter()
                .map(|(watch, error)| format!("{watch}: {error:#}"))
                .collect::<Vec<_>>()
                .join("; ");
            // Retain an authentication error in the chain so health remains
            // Expired even when other watches succeeded.
            let primary = failures
                .iter()
                .position(|(_, error)| {
                    error
                        .downcast_ref::<meep_posthog::api::ApiError>()
                        .is_some_and(|error| error.status == 401)
                })
                .unwrap_or(0);
            let (_, error) = failures.swap_remove(primary);
            Some(error.context(format!("Some PostHog watches failed: {detail}")))
        };
        Ok((events, warning))
    }

    async fn observe(
        &self,
        sub: &Subscription,
        session: &mut McpSession,
        tools: &[McpTool],
    ) -> Result<Value> {
        match sub.watch.kind.as_str() {
            "insight" => {
                let tool = resolve(tools, &["insight-query", "insight_query", "query-insight"])?;
                let id = sub
                    .numeric_id()
                    .map_or_else(|| json!(sub.watch.key), |n| json!(n));
                let mut args = json!({"insightId":id});
                if tool
                    .input_schema
                    .pointer("/properties/output_format")
                    .is_some()
                {
                    args["output_format"] = json!("json");
                }
                let value = tool_value(session.call(&tool.name, args).await?)?;
                let refreshed;
                let value = if let Some(api) = &self.fresh_insights {
                    let query = value
                        .pointer("/insight/query")
                        .filter(|q| q.is_object())
                        .context(
                            "MCP insight did not include its saved query; cannot refresh it",
                        )?;
                    let key = serde_json::to_string(query)?;
                    let mut cache = self.fresh_results.lock().await;
                    cache.retain(|_, (at, _)| at.elapsed() < Duration::from_secs(30));
                    if let Some((_, cached)) = cache.get(&key) {
                        refreshed = cached.clone();
                    } else {
                        let result: Value = api
                            .post(
                                &self.token,
                                "",
                                json!({"query": query, "refresh": "force_blocking"}),
                            )
                            .await
                            .context(
                                "refreshing PostHog insight; check the project API permissions",
                            )?;
                        ensure!(
                            result.get("is_cached").and_then(Value::as_bool) == Some(false),
                            "PostHog did not confirm a fresh insight result; retry after the provider refresh limit"
                        );
                        cache.insert(key, (Instant::now(), result.clone()));
                        refreshed = result;
                    }
                    &refreshed
                } else {
                    &value
                };
                let result = value
                    .get("results")
                    .or_else(|| value.get("result"))
                    .context("MCP insight has no results")?;
                let result = result.get("results").unwrap_or(result);
                let selected = if let Some(pointer) = &sub.result_pointer {
                    result.pointer(pointer)
                } else if result.is_number() {
                    Some(result)
                } else {
                    result
                        .pointer("/0/data")
                        .and_then(Value::as_array)
                        .and_then(|a| a.last())
                        .or_else(|| result.pointer("/0/aggregated_value"))
                        .or_else(|| result.pointer("/0/count"))
                        .or_else(|| result.pointer("/0/0"))
                }
                .context("no numeric insight value; configure result_pointer")?;
                ensure!(selected.is_number(), "insight value must be numeric");
                Ok(selected.clone())
            }
            "flag" => {
                let (aliases, args): (&[&str], Value) = if let Some(id) = sub.numeric_id() {
                    (
                        &[
                            "feature-flag-get-definition",
                            "feature_flag_get_definition",
                            "get-feature-flag",
                        ],
                        json!({"id":id}),
                    )
                } else {
                    (
                        &[
                            "feature-flag-get-definition-by-key",
                            "feature_flag_get_definition_by_key",
                        ],
                        json!({"key":sub.watch.key}),
                    )
                };
                let tool = resolve(tools, aliases)?;
                let flag = tool_value(session.call(&tool.name, args).await?)?;
                let flag = if let Some(text) = flag.as_str() {
                    toon_format::decode_strict::<Value>(text)
                        .context("invalid PostHog flag definition")?
                } else {
                    flag
                };
                ensure!(
                    flag["found"] != false,
                    "PostHog could not find flag '{}'",
                    sub.watch.key
                );
                let active = flag["active"]
                    .as_bool()
                    .context("missing boolean flag active state")?;
                let filters = flag["filters"]
                    .as_object()
                    .context("missing flag rollout filters")?;
                // Payloads and UI descriptions do not determine who receives a flag.
                let mut rollout = filters.clone();
                rollout.remove("payloads");
                Ok(json!({"active":active,"rollout":rollout}))
            }
            "event" => {
                let tool = resolve(tools, &["execute-sql", "execute_sql", "query-run"])?;
                let seconds = sub.window_seconds.context("missing event window")?;
                // execute-sql accepts a SQL string. Encoding the literal keeps all UTF-8
                // names (including quotes and backslashes) out of the query grammar.
                let sql = event_query(&sub.watch.key, seconds, Utc::now().timestamp());
                let args = if tool.name == "query-run" {
                    json!({"query":{"kind":"HogQLQuery","query":sql}})
                } else {
                    json!({"query":sql})
                };
                let value = tool_value(session.call(&tool.name, args).await?)?;
                let count = count_cell(&value)
                    .context("expected one unsigned meep_count from PostHog SQL")?;
                Ok(json!(count))
            }
            kind => bail!("unknown PostHog watch kind {kind}"),
        }
    }
}

impl Subscription {
    fn numeric_id(&self) -> Option<u64> {
        self.resource_id.or_else(|| self.watch.key.parse().ok())
    }

    fn validate_resource(&self) -> Result<()> {
        ensure!(
            self.numeric_id() != Some(0),
            "PostHog resource ID must be positive"
        );
        Ok(())
    }

    fn count_threshold(&self) -> Option<u64> {
        self.threshold.as_ref()?.as_u64().filter(|n| *n > 0)
    }

    fn delta_threshold(&self) -> f64 {
        self.threshold
            .as_ref()
            .and_then(Number::as_f64)
            .unwrap_or_default()
    }

    fn change(&self, old: Option<&Value>, new: &Value) -> Result<Option<String>> {
        let label = if self.watch.label.is_empty() {
            &self.watch.key
        } else {
            &self.watch.label
        };
        match self.watch.kind.as_str() {
            "insight" => {
                let Some(old) = old else { return Ok(None) };
                let from = old.as_f64().context("invalid saved insight value")?;
                let to = new.as_f64().context("invalid insight value")?;
                Ok(((to - from).abs() > self.delta_threshold())
                    .then(|| format!("{label} changed from {old} to {new}.")))
            }
            "flag" => {
                let Some(old) = old.filter(|old| *old != new) else {
                    return Ok(None);
                };
                let status = if new["active"] == true {
                    "active"
                } else {
                    "inactive"
                };
                let description = if new["rollout"] != old["rollout"] {
                    format!("The rollout for {label} changed. The flag is {status}.")
                } else {
                    format!("The flag {label} is now {status}.")
                };
                Ok(Some(description))
            }
            "event" => {
                let threshold = self.count_threshold().context("invalid event threshold")?;
                let count = new.as_u64().context("invalid event count")?;
                let previous = old
                    .map(|v| v.as_u64().context("invalid saved event count"))
                    .transpose()?;
                let seconds = self.window_seconds.context("missing event window")?;
                Ok((count >= threshold && previous.is_none_or(|n| n < threshold)).then(|| {
                    format!("{label} occurred {count} times in {seconds} seconds, reaching the threshold of {threshold}.")
                }))
            }
            kind => bail!("unknown PostHog watch kind {kind}"),
        }
    }
}

fn resolve<'a>(tools: &'a [McpTool], names: &[&str]) -> Result<&'a McpTool> {
    names
        .iter()
        .find_map(|name| tools.iter().find(|tool| tool.name == *name))
        .with_context(|| {
            format!(
                "PostHog MCP did not advertise an expected tool ({})",
                names.join(", ")
            )
        })
}

fn tool_value(result: ToolResult) -> Result<Value> {
    let mut texts = result
        .content
        .iter()
        .filter(|b| b["type"] == "text")
        .filter_map(|b| b["text"].as_str());
    if result.is_error {
        bail!(
            "PostHog MCP tool failed: {}",
            texts.next().unwrap_or("upstream error")
        );
    }
    if let Some(value) = result.structured_content {
        return Ok(value);
    }
    let text = texts
        .next()
        .context("PostHog MCP returned no tool content")?;
    ensure!(
        texts.next().is_none(),
        "expected a single PostHog MCP text result"
    );
    Ok(serde_json::from_str(text).unwrap_or_else(|_| Value::String(text.to_owned())))
}

fn count_cell(value: &Value) -> Option<u64> {
    let rows = value.get("results").unwrap_or(value);
    let rows = rows.get("results").unwrap_or(rows);
    if let Some(text) = rows.as_str() {
        let mut lines = text.trim().lines().map(str::trim);
        if lines.next()? != "meep_count" {
            return None;
        }
        let count = lines.next()?.parse().ok()?;
        return lines.next().is_none().then_some(count);
    }
    let [row] = rows.as_array()?.as_slice() else {
        return None;
    };
    let [count] = row.as_array()?.as_slice() else {
        return None;
    };
    count.as_u64()
}

#[cfg(test)]
mod tests {
    use super::event_query;

    #[test]
    fn event_query_keeps_a_bounded_cache_identity_without_changing_the_window() {
        let first = event_query("Bill's \\ signup", 900, 30);
        assert_eq!(first, event_query("Bill's \\ signup", 900, 59));
        let next = event_query("Bill's \\ signup", 900, 60);
        assert_ne!(first, next);
        assert!(first.contains("base64Decode('QmlsbCdzIFwgc2lnbnVw')"));
        assert!(
            first.contains("timestamp >= now() - toIntervalSecond(900) AND timestamp <= now()")
        );
        assert!(first.ends_with("AND 1 = 1"));
        assert!(next.ends_with("AND 2 = 2"));
    }
}
