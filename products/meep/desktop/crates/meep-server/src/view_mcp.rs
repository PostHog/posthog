//! Stateless Streamable HTTP MCP. Capabilities authorize exactly one active view turn.
use crate::{
    Server,
    http::{App, Failure, bearer},
};
use anyhow::{Context, Result, bail, ensure};
use axum::{
    Json,
    extract::Path,
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
};
use chrono::Utc;
use meep_wire::views::{View, ViewEnvelope};
use serde_json::{Value, json};
use uuid::Uuid;

pub(super) async fn list(axum::Extension(a): axum::Extension<App>) -> Json<Vec<View>> {
    Json(a.s.views.list())
}
pub(super) async fn command(
    axum::Extension(a): axum::Extension<App>,
    Json(e): Json<ViewEnvelope>,
) -> Result<Json<View>, Failure> {
    a.s.views.command(e).map(Json).map_err(|e| {
        if e.is::<crate::views::MissingView>() {
            Failure::missing_view()
        } else if e.is::<crate::views::Rejected>() {
            Failure::bad(&e.to_string())
        } else {
            Failure::internal(e)
        }
    })
}
pub(super) async fn device_source(
    axum::Extension(a): axum::Extension<App>,
    Path(id): Path<Uuid>,
    Json(args): Json<Value>,
) -> Result<Json<Value>, Failure> {
    a.s.views.read(id).map_err(|_| Failure::missing_view())?;
    source(&a.s, id, &args)
        .await
        .map(Json)
        .map_err(|e| match e.downcast::<meep_engine::Error>() {
            Ok(e) => e.into(),
            Err(e) => Failure::bad(&e.to_string()),
        })
}

fn string<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v[k].as_str()
        .with_context(|| format!("Expected string {k}"))
}

const CONTRACT: &str = "Use host.call(source, tool, arguments) in init, events or a refresh command. list_sources returns topic UUIDs and live PostHog tools. For source 'topics' use tasks, threads, facts, files, table, file or routine_data (the last dataset published for this view by a workflow) with {topic: UUID, path?: string}. tasks, threads and facts return arrays; files returns names; table returns {columns,rows}; file returns text. Each tasks row has id, title, column and status. column is one of Todo, InProgress, NeedsYou or Done; status is its human-readable label: To do, In progress, Needs you or Done. Use column for filtering and status for display. For source 'posthog' use a listed tool and its input schema. For connected installations use their UUID as source. Implement commands.refresh to re-read data on topic/workflow changes. All data operations are read-only. Use semantic theme colors and native components.";
fn tools() -> Value {
    let text = json!({"type":"string"});
    let number = json!({"type":"integer","minimum":0});
    json!([
        crate::mcp::tool(
            "read_view",
            "Read the current source, tile and generation.",
            json!({}),
            &[]
        ),
        crate::mcp::tool(
            "design_system",
            "Read the Meep host contract, JavaScript SDK, native declarations, design guide or an example.",
            json!({"topic":{"enum":["host","script","native","design","example"]}}),
            &[]
        ),
        crate::mcp::tool(
            "list_sources",
            "List topic IDs and available read-only PostHog tools.",
            json!({}),
            &[]
        ),
        crate::mcp::tool(
            "read_source",
            "Query a live source using the script host.call contract.",
            json!({"source":text,"tool":text,"arguments":{"type":"object"}}),
            &["source", "tool", "arguments"]
        ),
        crate::mcp::tool(
            "write_view",
            "Validate and publish JavaScript against a known generation. Optionally name the view and choose its tile.",
            json!({"expected":number,"source":text,"title":text,"icon":text,"color":text}),
            &["expected", "source"]
        ),
        crate::mcp::tool(
            "patch_view",
            "Replace a unique literal in the source and publish after validation.",
            json!({"expected":number,"old":text,"new":text}),
            &["expected", "old", "new"]
        )
    ])
}

pub(super) async fn mcp(
    axum::Extension(a): axum::Extension<App>,
    Path(crate::http::ObjectPath { id }): Path<crate::http::ObjectPath<Uuid>>,
    headers: HeaderMap,
    Json(req): Json<Value>,
) -> Result<Response, Failure> {
    let token = bearer(&headers)?;
    if !a.s.views.authorized(id, token) {
        return Err(Failure::auth());
    }
    if !a.s.accepts_mcp_origin(&headers) {
        return Ok(StatusCode::FORBIDDEN.into_response());
    }
    Ok(crate::mcp::respond(
        &req,
        "meep-view",
        || CONTRACT,
        tools,
        async |name, args| {
            call(&a.s, id, token, name, args)
                .await
                .map(|v| match v {
                    Value::String(text) => text,
                    other => other.to_string(),
                })
                .map_err(|e| e.to_string())
        },
    )
    .await)
}

async fn call(s: &Server, id: Uuid, token: &str, name: &str, args: &Value) -> Result<Value> {
    let view = s.views.read(id)?;
    match name {
        "read_view" => Ok(
            json!({"id":view.id,"title":view.title,"icon":view.icon,"color":view.color,"generation":view.generation(),"source":view.revisions.last().map(|r|&r.source)}),
        ),
        "design_system" => Ok(json!(match args["topic"].as_str().unwrap_or("host") {
            "host" => CONTRACT,
            "design" => include_str!("../../meep-render/meep-script/agent/DESIGN.md"),
            "script" => include_str!("../../meep-render/meep-script/agent/SCRIPT.md"),
            "native" => include_str!("../../meep-render/meep-script/agent/native-sdk.d.ts"),
            "example" => include_str!("../../meep-render/meep-script/agent/examples/tasks.js"),
            _ => bail!("Unknown guide"),
        })),
        "list_sources" => catalog(s).await,
        "read_source" => source(s, id, args).await,
        "write_view" | "patch_view" => {
            let expected = args["expected"]
                .as_u64()
                .context("Expected generation is required")?;
            ensure!(
                view.generation() == expected,
                "View changed. Read its source again."
            );
            let source = if name == "write_view" {
                string(args, "source")?.to_owned()
            } else {
                let src = &view.revisions.last().context("No published source")?.source;
                let old = string(args, "old")?;
                ensure!(
                    !old.is_empty() && src.match_indices(old).count() == 1,
                    "Patch must match exactly once"
                );
                src.replacen(old, string(args, "new")?, 1)
            };
            ensure!(source.len() <= 512 * 1024, "Source exceeds 512 KiB");
            let preview_server = s.clone();
            let runtime = tokio::runtime::Handle::current();
            let (source, diagnostics) = tokio::task::spawn_blocking(move || {
                let mut diagnostics = meep_script::script::validate(&source, &json!({}))
                    .map_err(anyhow::Error::msg)?;
                let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
                let preview = meep_script::script::validate_populated(&source, |args| {
                    let left = deadline.checked_duration_since(std::time::Instant::now())?;
                    let value = runtime.block_on(async {
                        tokio::time::timeout(left, self::source(&preview_server, id, args)).await
                    }).ok()?.ok()?;
                    (serde_json::to_vec(&value).ok()?.len() <= 512 * 1024).then_some(value)
                }).map_err(anyhow::Error::msg)?;
                if preview == Some(false) {
                    diagnostics["warnings"].as_array_mut().expect("validation warnings")
                        .push(json!("Live data preview was unavailable; check populated states after publishing."));
                }
                Ok::<_, anyhow::Error>((source, diagnostics))
            })
            .await??;
            s.views.update(id, |r| {
                ensure!(crate::views::authorized(r, token), "Turn has ended");
                let v = &mut r.view;
                for (k, field, max) in [
                    ("title", &mut v.title, 256),
                    ("icon", &mut v.icon, 64),
                    ("color", &mut v.color, 32),
                ] {
                    if let Some(value) = args.get(k) {
                        let value = value.as_str().context("Expected text")?.trim();
                        ensure!(!value.is_empty() && value.len() <= max, "Invalid {k}");
                        *field = value.into();
                    }
                }
                v.publish(expected, source, Utc::now())?;
                Ok(json!({"generation":v.generation(),"diagnostics":diagnostics}))
            })
        }
        _ => bail!("Unknown view tool"),
    }
}
use meep_posthog::mcp::view::native_allowed;
fn client(a: &crate::accounts::Account) -> Result<meep_posthog::mcp::McpClient> {
    let p = a.project.as_ref().context("PostHog unavailable")?;
    let config: Value = a
        .values
        .get("config")
        .map(|s| serde_json::from_str(s))
        .transpose()?
        .unwrap_or_default();
    let local = format!("{}/mcp", p.origin.trim_end_matches('/'));
    let endpoint = config["mcp_endpoint"]
        .as_str()
        .unwrap_or_else(|| match p.origin.as_str() {
            "https://us.posthog.com" | "https://eu.posthog.com" => {
                meep_posthog::mcp::DEFAULT_ENDPOINT
            }
            _ => &local,
        });
    meep_posthog::mcp::McpClient::new(endpoint, Some(p.project))
}
async fn catalog(s: &Server) -> Result<Value> {
    let topics = s
        .engine
        .topics()
        .into_iter()
        .map(|t| json!({"id":t.topic.id,"name":t.topic.name}))
        .collect::<Vec<_>>();
    let mut sources = vec![
        json!({"source":"topics","tools":["tasks","threads","facts","files","file","table","routine_data"],"topics":topics}),
    ];
    if let Some(a) = s.accounts.get("posthog") {
        let token = a
            .values
            .get("access_token")
            .context("PostHog token unavailable")?;
        let p = a.project.as_ref().context("PostHog unavailable")?;
        let gateway = meep_posthog::mcp::Gateway::new(&p.origin, p.project)?;
        let (native, installed) = tokio::join!(
            async { client(&a)?.initialize(token).await?.list_tools().await },
            gateway.available(token)
        );
        match native {
            Ok(tools) => {
                let reads: Vec<_> = tools
                    .into_iter()
                    .filter(|t| native_allowed(&t.name))
                    .collect();
                sources.push(json!({"source":"posthog","tools":reads}));
            }
            Err(e) => sources.push(json!({"source":"posthog","error":e.to_string()})),
        }
        if let Ok(installed) = installed {
            for service in installed {
                let tools: Vec<_> = service
                    .tools
                    .into_iter()
                    .filter(|t| {
                        t.approval_state == "approved" && t.annotations["readOnlyHint"] == true
                    })
                    .collect();
                if !tools.is_empty() {
                    sources.push(
                        json!({"source":service.installation_id,"name":service.name,"tools":tools}),
                    );
                }
            }
        }
    }
    Ok(json!(sources))
}
async fn source(s: &Server, view: Uuid, params: &Value) -> Result<Value> {
    let source = string(params, "source")?;
    let tool = string(params, "tool")?;
    let args = &params["arguments"];
    if source == "topics" {
        let id = string(args, "topic")?.parse()?;
        let state = s.engine.topic(id)?;
        return match tool {
            "routine_data" => Ok(state.view_data.get(&view).cloned().unwrap_or_default()),
            "files" => Ok(json!(s.engine.blobs().names(id)?)),
            "file" | "table" => {
                let path = string(args, "path")?;
                let file = s
                    .engine
                    .blobs()
                    .get(id, path, None)?
                    .context("File not found")?;
                if tool == "table" {
                    Ok(json!(meep_wire::table::read(path, &file.bytes)?))
                } else {
                    Ok(json!(String::from_utf8(file.bytes)?))
                }
            }
            _ => meep_wire::views::topic_rows(&state, tool),
        };
    }
    let a = s.accounts.get("posthog").context("Connect PostHog first")?;
    let p = a.project.as_ref().context("PostHog unavailable")?;
    let token = a
        .values
        .get("access_token")
        .context("PostHog token unavailable")?;
    meep_posthog::mcp::view::read_source(
        client(&a)?,
        &p.origin,
        p.project,
        token,
        source,
        tool,
        args,
    )
    .await
}
