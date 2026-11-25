use crate::{
    Checkpoint,
    mapping::{Mapping, Row},
    source_key, validate_watches,
};
use anyhow::{Context, Result, bail, ensure};
use chrono::{DateTime, Utc};
use meep_ingest::Event;
use meep_posthog::mcp::{Gateway, ToolResult};
use meep_topic::Watch;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use std::collections::{BTreeSet, HashSet};
use uuid::Uuid;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    connection: String,
    origin: String,
    project: u64,
    installation_id: Uuid,
    watches: Vec<Subscription>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Subscription {
    watch: Watch,
    tool: String,
    arguments: Map<String, Value>,
    mapping: Mapping,
    cursor_argument: Option<String>,
    initial_cursor_format: Option<TimeFormat>,
    pagination: Option<Pagination>,
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum TimeFormat {
    UnixSeconds,
    Rfc3339,
}

impl TimeFormat {
    fn format(&self, since: DateTime<Utc>) -> String {
        match self {
            Self::Rfc3339 => since.to_rfc3339(),
            Self::UnixSeconds => {
                let nanos = i128::from(since.timestamp()) * 1_000_000_000
                    + i128::from(since.timestamp_subsec_nanos());
                let magnitude = nanos.abs();
                let sign = if nanos < 0 { "-" } else { "" };
                format!(
                    "{sign}{}.{:09}",
                    magnitude / 1_000_000_000,
                    magnitude % 1_000_000_000
                )
            }
        }
    }
}

#[derive(Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Pagination {
    Cursor {
        argument: String,
        next: String,
    },
    Numbered {
        argument: String,
        size_argument: String,
        size: u32,
        #[serde(default)]
        newest_first: bool,
    },
}

#[derive(Clone, Deserialize, Serialize)]
struct Cursor {
    at: DateTime<Utc>,
    raw: Value,
    ids: BTreeSet<String>,
}

pub(super) struct Mcp {
    config: Config,
    gateway: Gateway,
    token: String,
}

impl Mcp {
    pub fn new(config: Value, token: String) -> Result<Self> {
        let config: Config = serde_json::from_value(config).context("invalid MCP configuration")?;
        validate_watches(&config.connection, config.watches.iter().map(|s| &s.watch))?;
        for sub in &config.watches {
            sub.mapping.validate()?;
            ensure!(
                sub.initial_cursor_format.is_none() || sub.cursor_argument.is_some(),
                "initial_cursor_format requires cursor_argument"
            );
            if let Some(Pagination::Cursor { next, .. }) = &sub.pagination {
                crate::mapping::validate_pointer(next)?;
            }
            ensure!(!sub.tool.trim().is_empty(), "missing MCP tool name");
            if let Some(Pagination::Numbered { size, .. }) = sub.pagination {
                ensure!(size > 0, "page size must be positive");
            }
        }
        Ok(Self {
            gateway: Gateway::new(&config.origin, config.project)?,
            token,
            config,
        })
    }

    pub async fn poll(
        &self,
        previous: &Checkpoint,
        state: &mut Checkpoint,
        since: DateTime<Utc>,
    ) -> Result<Vec<Event>> {
        let servers = self.gateway.available(&self.token).await?;
        let id = self.config.installation_id;
        let server = servers
            .iter()
            .find(|s| s.installation_id == id)
            .with_context(|| format!("MCP installation {id} is not available"))?;
        let mut events = Vec::new();
        for sub in &self.config.watches {
            let tool = server
                .tools
                .iter()
                .find(|t| t.name == sub.tool)
                .with_context(|| {
                    format!(
                        "{} installation {id} does not advertise tool '{}'",
                        server.name, sub.tool
                    )
                })?;
            ensure!(
                tool.approval_state == "approved",
                "{} tool '{}' needs approval before polling (approval_state: {})",
                server.name,
                sub.tool,
                tool.approval_state
            );
            let source = source_key((
                "mcp",
                &self.config.origin,
                self.config.project,
                id,
                &sub.watch.kind,
                &sub.watch.key,
                &sub.tool,
                &sub.arguments,
                &sub.mapping,
                &sub.cursor_argument,
            ))?;
            let old: Option<Cursor> = previous
                .value(sub.watch.id, &source)
                .map(|v| serde_json::from_value(v.clone()))
                .transpose()?;
            let (batch, next) = self
                .read(sub, old, since)
                .await
                .with_context(|| format!("calling {} on {}", sub.tool, server.name))?;
            events.extend(batch);
            if let Some(next) = next {
                state.record(sub.watch.id, source, serde_json::to_value(next)?);
            }
        }
        Ok(events)
    }

    async fn read(
        &self,
        sub: &Subscription,
        old: Option<Cursor>,
        since: DateTime<Utc>,
    ) -> Result<(Vec<Event>, Option<Cursor>)> {
        let mut args = sub.arguments.clone();
        if let Some(arg) = &sub.cursor_argument {
            if let Some(cursor) = &old {
                args.insert(arg.clone(), cursor.raw.clone());
            } else if let Some(format) = &sub.initial_cursor_format {
                args.entry(arg)
                    .or_insert_with(|| json!(format.format(since)));
            }
        }
        let mut next = old.clone();
        let floor = old.as_ref().map_or(since, |c| c.at.max(since));
        let mut events = Vec::new();
        let mut ids = HashSet::new();
        let mut page_tokens = HashSet::new();
        if let Some(Pagination::Numbered {
            argument,
            size_argument,
            size,
            ..
        }) = &sub.pagination
        {
            args.insert(argument.clone(), json!(1));
            args.insert(size_argument.clone(), json!(size));
        }
        for page in 1..=1000 {
            let result = self
                .gateway
                .call(&self.token, self.config.installation_id, &sub.tool, &args)
                .await?;
            let value = tool_json(result)?;
            let rows = sub.mapping.rows(&value, &sub.watch)?;
            let count = rows.len();
            let reached_floor = rows.iter().any(|r| r.event.at < floor);
            for row in rows {
                let e = &row.event;
                if e.at < floor
                    || old
                        .as_ref()
                        .is_some_and(|c| c.at == e.at && c.ids.contains(&e.external_id))
                    || !ids.insert(e.external_id.clone())
                {
                    continue;
                }
                advance(&mut next, &row);
                events.push(row.event);
            }
            match &sub.pagination {
                Some(Pagination::Cursor {
                    argument,
                    next: path,
                }) => {
                    let token = value
                        .pointer(path)
                        .filter(|v| !v.is_null())
                        .map(|v| {
                            v.as_str()
                                .with_context(|| format!("expected a string page cursor at {path}"))
                        })
                        .transpose()?;
                    let Some(token) = token.filter(|t| !t.is_empty()) else {
                        ensure!(
                            value["has_more"] != true,
                            "tool reports more items but returned no page cursor"
                        );
                        break;
                    };
                    ensure!(
                        page_tokens.insert(token.to_owned()),
                        "tool repeated a page cursor"
                    );
                    args.insert(argument.clone(), json!(token));
                }
                Some(Pagination::Numbered {
                    argument,
                    size,
                    newest_first,
                    ..
                }) => {
                    if count < *size as usize || (*newest_first && reached_floor) {
                        break;
                    }
                    args.insert(argument.clone(), json!(page + 1));
                }
                None => {
                    ensure!(
                        value["has_more"] != true,
                        "tool reports more items; configure pagination"
                    );
                    break;
                }
            }
            ensure!(page < 1000, "tool exceeded 1000 pages in a poll");
        }
        Ok((events, next))
    }
}

fn advance(cursor: &mut Option<Cursor>, row: &Row) {
    if cursor.as_ref().is_none_or(|c| c.at < row.event.at) {
        *cursor = Some(Cursor {
            at: row.event.at,
            raw: row.raw_timestamp.clone(),
            ids: BTreeSet::new(),
        });
    }
    if let Some(c) = cursor
        && c.at == row.event.at
    {
        c.ids.insert(row.event.external_id.clone());
    }
}

fn tool_json(result: ToolResult) -> Result<Value> {
    let mut texts = result
        .content
        .iter()
        .filter(|block| block["type"] == "text")
        .filter_map(|b| b["text"].as_str());
    if result.is_error {
        bail!(
            "MCP tool failed: {}",
            texts.next().unwrap_or("upstream service returned an error")
        );
    }
    if let Some(value) = result.structured_content {
        return Ok(value);
    }
    let text = texts.next().context("MCP tool returned no JSON result")?;
    ensure!(
        texts.next().is_none(),
        "expected one JSON text block from MCP tool"
    );
    serde_json::from_str(text).context("MCP tool text was not JSON")
}
