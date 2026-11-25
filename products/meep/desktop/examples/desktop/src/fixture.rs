//! An ephemeral project implementing just the PostHog requests used by the two examples.
//! Clients talk ordinary HTTP. The fixture never forwards traffic or runs an agent.
use http_body_util::{BodyExt, Full, Limited};
use hyper::{
    Method, Request, Response,
    body::{Bytes, Incoming},
    server::conn::http1,
    service::service_fn,
};
use hyper_util::rt::TokioIo;
use meep_posthog::workflows::Invocation;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    convert::Infallible,
    sync::{Arc, Mutex},
};
use uuid::Uuid;

pub const FLOW: Uuid = Uuid::from_u128(0x330);

pub fn recent_runs() -> Vec<Invocation> {
    [
        (0xa108, "succeeded", 184),
        (0x7b09, "failed", 31),
        (0x4c10, "succeeded", 206),
    ]
    .into_iter()
    .map(|(n, status, duration)| Invocation {
        invocation_id: Uuid::from_u128(n << 112),
        status: status.into(),
        duration_ms: Some(duration),
    })
    .collect()
}

pub const TEMPLATE: Uuid = Uuid::from_u128(0x110);
pub const INSTALLATION: Uuid = Uuid::from_u128(0x220);

#[derive(Default)]
struct Project {
    tasks: BTreeMap<Uuid, (String, Vec<Value>)>,
    connected: bool,
    invocations: BTreeMap<Uuid, Uuid>,
}

impl Project {
    fn reply(
        &mut self,
        method: &Method,
        uri: &hyper::Uri,
        body: &Value,
        key: Option<&str>,
    ) -> (u16, Value) {
        let segments: Vec<_> = uri.path().trim_matches('/').split('/').collect();
        let routes = match segments.as_slice() {
            ["api", "projects", "1", rest @ ..] => rest,
            _ => return (404, json!({"detail":"Unknown project"})),
        };
        match (method, routes) {
            (&Method::GET, ["hog_flows", flow, "invocation_results"])
                if Uuid::parse_str(flow) == Ok(FLOW) =>
            {
                let limit = uri
                    .query()
                    .and_then(|q| q.strip_prefix("limit="))
                    .and_then(|n| n.parse::<usize>().ok())
                    .unwrap_or(50);
                let running = self.invocations.values().map(|id| {
                    json!({
                        "invocation_id":id,"status":"running","duration_ms":null
                    })
                });
                let completed = recent_runs().into_iter().map(|run| json!({
                    "invocation_id":run.invocation_id,"status":run.status,"duration_ms":run.duration_ms
                }));
                (200, running.chain(completed).take(limit).collect())
            }
            (&Method::POST, ["hog_flows", flow, "run"])
                if Uuid::parse_str(flow) == Ok(FLOW) && body["variables"].is_object() =>
            {
                let Some(key) = key.and_then(|s| Uuid::parse_str(s).ok()) else {
                    return (400, json!({"detail":"Missing idempotency key"}));
                };
                let id = self.invocations.entry(key).or_insert_with(Uuid::new_v4);
                (200, json!({"invocation_id":id,"status":"queued"}))
            }
            (&Method::GET, ["hog_flows", flow, "invocation_results", run])
                if Uuid::parse_str(flow) == Ok(FLOW)
                    && self
                        .invocations
                        .values()
                        .any(|id| Ok(*id) == Uuid::parse_str(run)) =>
            {
                (
                    200,
                    json!({"invocation_id":run,"status":"running","duration_ms":null}),
                )
            }
            (&Method::POST, ["tasks"]) => {
                let Some(prompt) = body["description"]
                    .as_str()
                    .filter(|text| !text.trim().is_empty())
                else {
                    return (400, json!({"detail":"Enter a task description."}));
                };
                let id = Uuid::new_v4();
                self.tasks.insert(id, (prompt.to_owned(), Vec::new()));
                (
                    201,
                    json!({"id":id,"title":prompt,"description":prompt,"status":"backlog"}),
                )
            }
            (method, ["tasks", id, "thread_messages"]) => {
                let Some((_, messages)) = Uuid::parse_str(id)
                    .ok()
                    .and_then(|id| self.tasks.get_mut(&id))
                else {
                    return (404, json!({"detail":"Task not found"}));
                };
                if method == Method::GET {
                    return (200, json!(messages));
                }
                if method == Method::POST
                    && let Some(text) = body["content"].as_str().filter(|s| !s.trim().is_empty())
                {
                    let message = json!({"id":Uuid::new_v4(),"author_kind":"user","content":text});
                    messages.push(message.clone());
                    return (201, message);
                }
                (400, json!({"detail":"Enter a message."}))
            }
            (&Method::POST, ["mcp_server_installations", "install_template"])
                if body["template_id"] == json!(TEMPLATE) && body["scope"] == "personal" =>
            {
                self.connected = true;
                (201, json!({"id":INSTALLATION}))
            }
            (&Method::GET, ["mcp_server_installations", "available_tools"]) => {
                let servers = if self.connected {
                    vec![json!({
                        "installation_id":INSTALLATION, "name":"Reading library","slug":"library",
                        "tools":[{
                            "name":"list_collections", "description":"List your reading collections",
                            "input_schema":{"type":"object","properties":{}},
                            "annotations":{"readOnlyHint":true}, "approval_state":"approved"
                        }]
                    })]
                } else {
                    Vec::new()
                };
                (200, json!({"servers":servers}))
            }
            (&Method::POST, ["mcp_server_installations", id, "call_tool"])
                if self.connected
                    && Uuid::parse_str(id) == Ok(INSTALLATION)
                    && body["tool_name"] == "list_collections"
                    && body["arguments"] == json!({}) =>
            {
                (
                    200,
                    json!({
                        "content":[{"type":"text","text":"Design notes, Fieldwork, Archive"}],
                        "is_error":false,
                        "structured_content":{"collections":["Design notes","Fieldwork","Archive"]}
                    }),
                )
            }
            _ => (
                404,
                json!({"detail":"Operation unavailable in this example project"}),
            ),
        }
    }
}

pub struct Endpoint {
    pub origin: String,
    pub token: String,
    listener: tokio::task::JoinHandle<()>,
}
impl Drop for Endpoint {
    fn drop(&mut self) {
        self.listener.abort();
    }
}

pub async fn start() -> anyhow::Result<Endpoint> {
    let socket = tokio::net::TcpListener::bind(("127.0.0.1", 0)).await?;
    let origin = format!("http://{}", socket.local_addr()?);
    let token = Uuid::new_v4().to_string();
    let auth = Arc::new(format!("Bearer {token}"));
    let project = Arc::new(Mutex::new(Project::default()));
    let listener = tokio::spawn(async move {
        while let Ok((stream, _)) = socket.accept().await {
            let project = project.clone();
            let auth = auth.clone();
            tokio::spawn(async move {
                let service = service_fn(move |req: Request<Incoming>| {
                    let project = project.clone();
                    let auth = auth.clone();
                    async move {
                        let (parts, body) = req.into_parts();
                        let (status, value) = if parts
                            .headers
                            .get("authorization")
                            .and_then(|h| h.to_str().ok())
                            != Some(&auth)
                        {
                            (401, json!({"detail":"Unknown fixture session"}))
                        } else if let Ok(bytes) = Limited::new(body, 128 * 1024).collect().await {
                            let bytes = bytes.to_bytes();
                            match if bytes.is_empty() {
                                Ok(Value::Null)
                            } else {
                                serde_json::from_slice(&bytes)
                            } {
                                Ok(body) => project.lock().unwrap().reply(
                                    &parts.method,
                                    &parts.uri,
                                    &body,
                                    parts
                                        .headers
                                        .get("Idempotency-Key")
                                        .and_then(|v| v.to_str().ok()),
                                ),
                                Err(_) => (400, json!({"detail":"Invalid JSON"})),
                            }
                        } else {
                            (413, json!({"detail":"Request too large"}))
                        };
                        Ok::<_, Infallible>(
                            Response::builder()
                                .status(status)
                                .header("content-type", "application/json")
                                .body(Full::new(Bytes::from(value.to_string())))
                                .unwrap(),
                        )
                    }
                });
                let _ = http1::Builder::new()
                    .serve_connection(TokioIo::new(stream), service)
                    .await;
            });
        }
    });
    Ok(Endpoint {
        origin,
        token,
        listener,
    })
}
