//! The topic MCP builds PostHog workflows and binds them as routines. PostHog is a loopback stand-in.
mod support;
use anyhow::{Context, Result};
use axum::{
    Json, Router,
    extract::Path,
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
};
use meep_topic::TopicId;
use parking_lot::Mutex;
use reqwest::Method;
use serde_json::{Value, json};
use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};
use support::{Host, create};
use uuid::Uuid;

const BASE: &str = "https://topics.example.test/tunnel";
/// A workflow that already exists in the stand-in PostHog project.
const EXISTING_FLOW: &str = "6c1f4f0e-6f4e-4a52-9a43-2a8f0f1d5e01";

#[derive(Clone, Default)]
struct Seen {
    descriptions: Arc<Mutex<Vec<String>>>,
    runs: Arc<Mutex<Vec<Value>>>,
    lose_default_receipt: Arc<AtomicBool>,
    defaults: Arc<Mutex<Vec<(Uuid, Value)>>>,
    flows: Arc<Mutex<Vec<Value>>>,
    schedules: Arc<Mutex<Vec<Value>>>,
    patches: Arc<Mutex<Vec<Value>>>,
    dispatches: Arc<Mutex<Vec<(Uuid, Value)>>>,
    origins: Arc<Mutex<Vec<Option<Value>>>>,
    done: Arc<AtomicBool>,
    /// Messages Meep sent to the run, echoed back in its log like PostHog does.
    sent: Arc<Mutex<Vec<String>>>,
}

/// Tasks and hog flow endpoints for project 7.
async fn posthog(seen: Seen) -> Result<(String, tokio::task::JoinHandle<()>)> {
    let task = Uuid::new_v4();
    let run = Uuid::new_v4();
    let flow = Uuid::new_v4();
    let tasks = format!("/api/projects/7/tasks/{task}");
    let flows = "/api/projects/7/hog_flows";
    let s = seen.clone();
    let router = Router::new()
        .route(
            "/api/projects/7/tasks/",
            get(|| async { Json(json!({"results":[]})) }).post({
                let s = s.clone();
                move |Json(body): Json<Value>| async move {
                    let text = body["description"].as_str().unwrap_or_default();
                    s.descriptions.lock().push(text.to_owned());
                    s.origins.lock().push(body.get("origin_product").cloned());
                    Json(json!({"id":task}))
                }
            }),
        )
        // Runs carrying a Meep MCP ask for the account's Claude runtime model.
        .route(
            "/api/projects/7/tasks/@me/config/",
            get(|| async { Json(json!({"resolved_ai_run_defaults":{"runtime":"acp","runtime_adapter":"claude","model":"claude-test","reasoning_effort":null}})) }),
        )
        .route(
            "/api/projects/7/tasks/models/",
            get(|| async {
                Json(json!({"models":[{"model":"claude-test","display_name":"Claude","runtime_adapter":"claude"}]}))
            }),
        )
        // Source discovery: one insight, no connected services, and relevance scores.
        .route(
            "/api/projects/7/mcp_server_installations/available_tools/",
            get(|| async { Json(json!({"servers":[]})) }),
        )
        .route(
            "/mcp",
            post(|Json(body): Json<Value>| async move {
                let result = match body["method"].as_str() {
                    Some("initialize") => json!({"protocolVersion":"2025-06-18","capabilities":{"tools":{}}}),
                    Some("tools/list") => json!({"tools":[{"name":"insights-list","inputSchema":{"type":"object"}}]}),
                    Some("tools/call") => json!({"content":[],"structuredContent":{"results":[{"id":42,"name":"Saved page opens"}]},"isError":false}),
                    _ => return StatusCode::ACCEPTED.into_response(),
                };
                Json(json!({"jsonrpc":"2.0","id":body["id"],"result":result})).into_response()
            }),
        )
        .route(
            "/v1/systemone",
            post(|Json(q): Json<Value>| async move {
                let answers = q["questions"]
                    .as_object()
                    .map(|qs| {
                        qs.keys()
                            .map(|k| (k.clone(), json!({"type":"score","score":2.0})))
                            .collect::<serde_json::Map<_, _>>()
                    })
                    .unwrap_or_default();
                Json(json!({"model":q["model"],"answers":answers,"usage":{}}))
            }),
        )
        .route(
            &format!("{tasks}/run/"),
            post({
                let s = s.clone();
                move |Json(body): Json<Value>| async move {
                    if let Some(text) = body["pending_user_message"].as_str() {
                        s.sent.lock().push(text.to_owned());
                    }
                    s.runs.lock().push(body);
                    Json(json!({"run":{"id":run,"status":"queued"}}))
                }
            }),
        )
        .route(
            &format!("{tasks}/runs/{run}/"),
            get({
                let s = s.clone();
                move || async move {
                    let status = if s.done.load(Ordering::SeqCst) { "completed" } else { "in_progress" };
                    Json(json!({"id":run,"status":status}))
                }
            }),
        )
        .route(
            &format!("{tasks}/runs/{run}/command/"),
            post({
                let s = s.clone();
                move |Json(body): Json<Value>| async move {
                    assert_eq!(body["method"], "user_message");
                    s.sent
                        .lock()
                        .push(body["params"]["content"].as_str().unwrap_or_default().to_owned());
                    Json(json!({"result":{"queued":true}}))
                }
            }),
        )
        .route(
            &format!("{tasks}/runs/{run}/session_logs/"),
            get({
                let s = s.clone();
                move || async move {
                    if s.done.load(Ordering::SeqCst) {
                        let update = |kind: &str, text: &str| json!({"notification":{"method":"session/update","params":{"update":{"sessionUpdate":kind,"content":{"type":"text","text":text}}}}});
                        let mut log: Vec<Value> =
                            s.sent.lock().iter().map(|t| update("user_message", t)).collect();
                        log.push(update("agent_message", "Routine ready"));
                        Json(Value::Array(log))
                    } else {
                        Json(json!([]))
                    }
                }
            }),
        )
        .route(
            &format!("{flows}/"),
            post({
                let s = s.clone();
                move |headers:axum::http::HeaderMap,Json(body): Json<Value>| async move {
                    if let Some(key)=headers.get("idempotency-key"){
                        let id=Uuid::parse_str(key.to_str().unwrap()).unwrap();
                        s.defaults.lock().push((id,body.clone()));
                        if s.lose_default_receipt.swap(false,Ordering::SeqCst){return (StatusCode::SERVICE_UNAVAILABLE,Json(json!({}))).into_response();}
                        return (StatusCode::CREATED,Json(json!({"id":id,"status":"draft"}))).into_response();
                    }
                    s.flows.lock().push(body.clone());
                    if body["name"] == "Broken" {
                        return (StatusCode::BAD_REQUEST, Json(json!({"type":"validation_error","code":"invalid_input","detail":"Exactly one trigger action is required","attr":"actions"}))).into_response();
                    }
                    (StatusCode::CREATED, Json(json!({"id":flow,"status":body["status"],"schedules":[]}))).into_response()
                }
            }).get({
                let s=s.clone();
                move ||async move{Json(json!({"results":s.defaults.lock().iter().map(|(id,f)|json!({"id":id,"description":f["description"]})).collect::<Vec<_>>(),"next":null}))}
            }),
        )
        .route(
            &format!("{flows}/{{flow}}/schedules/"),
            post({
                let s = s.clone();
                move |Path(id): Path<Uuid>, Json(body): Json<Value>| async move {
                    assert_eq!(id, flow);
                    s.schedules.lock().push(body);
                    (StatusCode::CREATED, Json(json!({"id":Uuid::new_v4()})))
                }
            }),
        )
        .route(
            &format!("{flows}/{{flow}}/run/"),
            post({
                let s = s.clone();
                move |Path(id): Path<Uuid>, Json(body): Json<Value>| async move {
                    s.dispatches.lock().push((id, body));
                    Json(json!({"invocation_id":Uuid::new_v4(),"status":"queued"}))
                }
            }),
        )
        .route(
            &format!("{flows}/{{flow}}/"),
            get({
                let s = s.clone();
                move |Path(id): Path<Uuid>| async move {
                    if id.to_string() == EXISTING_FLOW {
                        return Json(json!({"id":id,"name":"Signup digest","status":"active","actions":[{"id":"trigger","type":"trigger","config":{"type":"schedule"}}]})).into_response();
                    }
                    if let Some((_,body))=s.defaults.lock().iter().find(|(key,_)|*key==id){return Json(json!({"id":id,"name":"Sort inbox","status":"active","actions":body["actions"]})).into_response();}
                    if id != flow {
                        return (StatusCode::NOT_FOUND, Json(json!({"detail":"Not found."}))).into_response();
                    }
                    let last = s.patches.lock().iter().rev().find(|p| p.get("actions").is_some()).cloned().unwrap_or_default();
                    let status=s.patches.lock().iter().rev().find_map(|p|p["status"].as_str().map(String::from)).unwrap_or_else(|| "active".into());
                    Json(json!({"id":flow,"status":status,"trigger":{"type":"schedule"},"actions":last["actions"],"schedules":s.schedules.lock().clone()})).into_response()
                }
            })
            .patch({
                let s = s.clone();
                move |Path(id): Path<Uuid>, Json(body): Json<Value>| async move {
                    if id!=flow {assert!(s.defaults.lock().iter().any(|(k,_)|*k==id));return Json(json!({"id":id,"status":body["status"]}));}
                    s.patches.lock().push(body.clone());
                    Json(json!({"id":flow,"status":body["status"]}))
                }
            }),
        );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let origin = format!("http://{}", listener.local_addr()?);
    let server = tokio::spawn(async move {
        axum::serve(listener, router).await.unwrap();
    });
    Ok((origin, server))
}

async fn connect(h: &Host, origin: &str, t: TopicId) -> Result<()> {
    let grant = json!({"kind":"posthog","label":"Analytics","account":"Work","secrets":{
        "access_token":"token","region":origin,"project_id":"7"
    },"grants":[t]});
    h.request(Method::PUT, "connections/work")
        .json(&grant)
        .send()
        .await?
        .error_for_status()?;
    Ok(())
}

async fn started(seen: &Seen) -> Result<Value> {
    until(seen, |s| s.runs.lock().first().cloned())
        .await
        .context("The topic agent run never started")
}

/// The JSON run context after the marker line and the Meep skill.
fn context(description: &str) -> Result<Value> {
    let (head, json) = description
        .split_once(&format!("\n{}\n", meep_engine::RUN_CONTEXT_HEADING))
        .context("run context")?;
    let (_, skill) = head.split_once('\n').context("marker line")?;
    assert_eq!(skill.trim_end(), meep_engine::MEEP_SKILL.trim_end());
    Ok(serde_json::from_str(json)?)
}

struct Mcp<'a> {
    h: &'a Host,
    url: String,
    token: String,
}
impl Mcp<'_> {
    async fn rpc(&self, method: &str, params: Value) -> Result<reqwest::Response> {
        Ok(self
            .h
            .client
            .post(&self.url)
            .bearer_auth(&self.token)
            .json(&json!({"jsonrpc":"2.0","id":1,"method":method,"params":params}))
            .send()
            .await?)
    }
    /// Call a tool and return (isError, decoded text).
    async fn tool(&self, name: &str, arguments: Value) -> Result<(bool, Value)> {
        let reply: Value = self
            .rpc("tools/call", json!({"name":name,"arguments":arguments}))
            .await?
            .error_for_status()?
            .json()
            .await?;
        let result = &reply["result"];
        let text = result["content"][0]["text"].as_str().context("tool text")?;
        Ok((
            result["isError"] == true,
            serde_json::from_str(text).unwrap_or_else(|_| json!(text)),
        ))
    }
}

#[tokio::test]
async fn a_topic_run_creates_binds_and_switches_a_posthog_routine() -> Result<()> {
    let seen = Seen::default();
    let (origin, provider) = posthog(seen.clone()).await?;
    let h = Host::open_with_base(tempfile::tempdir()?, Some(BASE)).await?;
    let t: TopicId = Uuid::new_v4().into();
    let other: TopicId = Uuid::new_v4().into();
    h.commands(vec![create(t), create(other)]).await?;
    connect(&h, &origin, t).await?;

    // Granting PostHog opens the topic's one setup conversation, which starts the run.
    let run = started(&seen).await?;
    let description = seen.descriptions.lock()[0].clone();
    let (marker, _) = description.split_once('\n').unwrap();
    assert_eq!(marker, format!("[meep topic:{t}]"));
    let prompt = context(&description)?;
    assert_eq!(prompt["setup"], true);
    assert!(prompt.get("watches").is_none());
    assert!(prompt.get("facts").is_none());
    assert_eq!(
        prompt["untrusted_source_data"]["thread"]["messages"][0]["author"],
        "Meep"
    );
    assert!(
        prompt["more"]["how"]
            .as_str()
            .unwrap()
            .contains("list_facts")
    );
    assert_eq!(prompt["task"]["title"], meep_engine::SETUP_TITLE);
    let instructions = prompt["instructions"].as_str().unwrap();
    assert!(instructions.contains("respect all limits the person stated"));
    assert!(instructions.contains("never watch sources or create routines"));
    let state = h.server.engine().topic(t)?;
    assert_eq!(state.threads.len(), 1);
    assert_eq!(state.threads[0].messages[0].author, "Meep");
    let server = &run["imported_mcp_servers"][0];
    assert_eq!(server["type"], "http");
    assert_eq!(server["name"], "meep-topic");
    assert_eq!(server["url"], format!("{BASE}/v1/topics/{t}/mcp"));
    let token = server["headers"][0]["value"]
        .as_str()
        .and_then(|v| v.strip_prefix("Bearer "))
        .context("bearer capability")?
        .to_owned();
    let stored = serde_json::to_string(&h.server.engine().topic(t)?)?;
    assert!(!stored.contains(&token), "the capability never replicates");
    let mcp = Mcp {
        h: &h,
        url: format!("{}/v1/topics/{t}/mcp", h.origin),
        token: token.clone(),
    };

    // Credentials are scoped to the run's topic.
    for (url, token) in [
        (mcp.url.clone(), "wrong".to_owned()),
        (format!("{}/v1/topics/{other}/mcp", h.origin), token.clone()),
        (mcp.url.clone(), h.token.clone()),
    ] {
        let status = h
            .client
            .post(url)
            .bearer_auth(token)
            .json(&json!({"jsonrpc":"2.0","id":1,"method":"tools/list"}))
            .send()
            .await?
            .status();
        assert_eq!(status, StatusCode::UNAUTHORIZED);
    }
    let foreign = h
        .client
        .post(&mcp.url)
        .bearer_auth(&token)
        .header("origin", "https://elsewhere.example")
        .json(&json!({"jsonrpc":"2.0","id":1,"method":"ping"}))
        .send()
        .await?;
    assert_eq!(foreign.status(), StatusCode::FORBIDDEN);

    let init: Value = mcp
        .rpc("initialize", json!({"protocolVersion":"2025-06-18"}))
        .await?
        .json()
        .await?;
    assert_eq!(init["result"]["serverInfo"]["name"], "meep-topic");
    let tools: Value = mcp.rpc("tools/list", json!({})).await?.json().await?;
    let names: Vec<_> = tools["result"]["tools"]
        .as_array()
        .unwrap()
        .iter()
        .map(|t| t["name"].as_str().unwrap())
        .collect();
    assert!(names.contains(&"create_routine") && names.contains(&"propose_action"));
    // Every tool runs as the agent: none approves work.
    assert!(!names.iter().any(|n| n.contains("approve")));
    let instructions = init["result"]["instructions"].as_str().unwrap();
    assert!(instructions.starts_with(meep_engine::MEEP_SKILL.trim_end()));
    assert!(
        instructions.contains("Context references are passive and do not authorize monitoring")
    );
    assert!(instructions.contains("Questions belong in the task conversation"));
    assert!(instructions.contains("to `publish_report` to send it an agent-authored report"));
    assert!(!instructions.contains("\"template\":\"urgent-only\""));
    assert!(!instructions.contains("A source workflow can use system1_sort"));
    let descriptions = tools["result"]["tools"].as_array().unwrap();
    let description = |name: &str| {
        descriptions
            .iter()
            .find(|tool| tool["name"] == name)
            .unwrap()["description"]
            .as_str()
            .unwrap()
    };
    assert!(description("list_threads").contains("agent-published reports"));
    assert!(description("get_thread").contains("legacy review"));
    assert!(!description("set_routine_sources").contains("Sort inbox"));

    // Invalid input is a tool error and contacts nobody.
    let (failed, text) = mcp
        .tool(
            "create_routine",
            json!({"name":"Empty","trigger":{"type":"manual"},"steps":[]}),
        )
        .await?;
    assert!(failed, "{text}");
    let (failed, text) = mcp
        .tool("create_routine", json!({"name":"Late","trigger":{"type":"schedule","hour":25},"steps":[{"name":"Say","kind":"report_to_topic","config":{"text":"hi"}}]}))
        .await?;
    assert!(
        failed && text.as_str().unwrap().contains("out of range"),
        "{text}"
    );
    let (failed, text) = mcp.tool("create_routine", json!({"name":"Wait","trigger":{"type":"manual"},"steps":[{"name":"Pause","kind":"delay","config":{"duration":"1秒"}}]})).await?;
    assert!(
        failed && text.as_str().is_some_and(|s| s.contains("duration")),
        "{text}"
    );
    for (kind, config) in [
        ("report_to_topic", json!({"op":"note"})),
        ("webhook", json!({"url":"http://example.com"})),
        (
            "webhook",
            json!({"url":"https://example.com","method":"TRACE"}),
        ),
    ] {
        let (failed, text) = mcp
            .tool(
                "create_routine",
                json!({"name":"Invalid","trigger":{"type":"manual"},
            "steps":[{"name":"Step","kind":kind,"config":config}]}),
            )
            .await?;
        assert!(failed, "{text}");
    }
    assert!(seen.flows.lock().is_empty());

    // PostHog's own rejection reaches the agent and binds nothing.
    let (failed, text) = mcp
        .tool("create_routine", json!({"name":"Broken","trigger":{"type":"manual"},"steps":[{"name":"Say","kind":"report_to_topic","config":{"text":"hi"}}]}))
        .await?;
    assert!(failed);
    assert!(
        text.as_str()
            .unwrap()
            .contains("Exactly one trigger action is required"),
        "{text}"
    );
    assert!(
        h.server
            .engine()
            .topic(t)?
            .topic
            .routines
            .iter()
            .all(|r| r.binding.backend == "system" || r.binding.name == "Sort inbox")
    );

    let (failed, created) = mcp
        .tool(
            "create_routine",
            json!({
                "name":"Weekday saved-page summary",
                "description":"Summarize saved-page opens",
                "trigger":{"type":"schedule","days":["MO","TU","WE","TH","FR"],"hour":9,"timezone":"Europe/Berlin"},
                "steps":[
                    {"name":"Wait for data","kind":"delay","config":{"duration":"5m"}},
                    {"name":"Ask for the summary","kind":"report_to_topic","config":{"op":"task","text":"Summarize today's saved-page opens"}}
                ]
            }),
        )
        .await?;
    assert!(!failed, "{created}");
    let id = "weekday-saved-page-summary";
    let callback = format!("{BASE}/v1/routines/{t}/{id}/callback");
    let draft = seen.flows.lock()[1].clone();
    assert_eq!(draft["status"], "draft");
    assert_eq!(draft["name"], "Weekday saved-page summary");
    let kinds: Vec<_> = draft["actions"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| (a["id"].as_str().unwrap(), a["type"].as_str().unwrap()))
        .collect();
    assert_eq!(
        kinds,
        [
            ("trigger", "trigger"),
            ("step_1", "delay"),
            ("step_2", "function"),
            ("step_2_report", "function"),
            ("exit", "exit")
        ]
    );
    assert_eq!(draft["actions"][0]["config"], json!({"type":"schedule"}));
    assert_eq!(
        draft["actions"][1]["config"],
        json!({"delay_duration":"5m"})
    );
    assert_eq!(
        draft["edges"],
        json!([
            {"from":"trigger","to":"step_1","type":"continue"},
            {"from":"step_1","to":"step_2","type":"continue"},
            {"from":"step_2","to":"step_2_report","type":"continue"},
            {"from":"step_2_report","to":"exit","type":"continue"}
        ])
    );
    let agent = &draft["actions"][2];
    assert_eq!(
        agent["config"]["template_id"],
        "template-posthog-create-task"
    );
    assert!(
        agent["config"]["inputs"]["prompt"]["value"]
            .as_str()
            .unwrap()
            .contains("Summarize today's saved-page opens")
    );
    assert_eq!(
        agent["output_variable"][0]["result_path"],
        "output.reports_json"
    );
    let inputs = &draft["actions"][3]["config"]["inputs"];
    assert_eq!(
        draft["actions"][3]["config"]["template_id"],
        "template-webhook"
    );
    assert_eq!(inputs["url"]["value"], callback);
    assert_eq!(
        inputs["headers"]["value"]["Idempotency-Key"],
        "{md5Hex(concat(event.uuid, ':step_2'))}"
    );
    assert_eq!(
        inputs["body"]["value"]["op"],
        json!({"kind":"Report","event_id":"{event.uuid}","run_id":"{variables.report_run}","reports_json":"{variables.reports_json}"})
    );
    assert_eq!(inputs["body"]["value"]["secret"], "pending");
    let schedule = seen.schedules.lock()[0].clone();
    assert_eq!(
        schedule["rrule"],
        "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=9;BYMINUTE=0;BYSECOND=0"
    );
    assert_eq!(schedule["timezone"], "Europe/Berlin");

    // A finalized draft is inspectable before the server authorizes activation.
    let secret = h.server.engine().routine_secret(t, id)?;
    let last = seen.patches.lock().last().cloned().unwrap();
    assert_eq!(last["status"], "draft");
    assert_eq!(created["status"], "awaiting_approval");
    let approval = serde_json::from_value(created["task"].clone())?;
    assert!(seen.patches.lock().iter().all(|p| p["status"] != "active"));
    h.server.engine().approve(t, approval, None, true).await?;
    h.server.engine().tick_topic(t).await?;
    assert_eq!(
        seen.patches.lock().last().unwrap(),
        &json!({"status":"active"})
    );
    let mut body = last["actions"][3]["config"]["inputs"]["body"]["value"].clone();
    assert_eq!(body["secret"], secret);
    let flow = created["flow"].as_str().unwrap().to_owned();
    assert_eq!(
        created["url"],
        format!("{origin}/project/7/workflows/{flow}/workflow")
    );
    assert_eq!(created["routine"]["id"], id);
    let routines = h.server.engine().topic(t)?.topic.routines;
    assert_eq!(routines.len(), 1);
    assert!(routines.iter().all(|r| r.binding.backend == "posthog"));
    let binding = &routines
        .iter()
        .find(|r| r.binding.id == id)
        .unwrap()
        .binding;
    assert_eq!(binding.backend, "posthog");
    assert_eq!(binding.external_id, flow);
    assert_eq!(binding.trigger, "Weekdays at 09:00 (Europe/Berlin)");

    // The webhook body PostHog would send applies through the existing callback.
    let before = h.server.engine().topic(t)?.tasks.len();
    let run = Uuid::new_v4();
    body["op"]["event_id"] = json!(Uuid::new_v4());
    body["op"]["run_id"] = json!(run);
    body["op"]["reports_json"] = json!(json!([{"title":"Saved pages","body":"Usage increased","priority":"P2","impact":"10 more opens","proposal":"Review adoption","evidence":[{"kind":"event","at":"2026-01-01T09:00:00Z","description":"Page opened","source_id":"insight:42"}]}]).to_string());
    let key = Uuid::new_v4();
    for _ in 0..2 {
        h.client
            .post(format!("{}/v1/routines/{t}/{id}/callback", h.origin))
            .header("idempotency-key", key.to_string())
            .json(&body)
            .send()
            .await?
            .error_for_status()?;
    }
    let state = h.server.engine().topic(t)?;
    assert_eq!(state.tasks.len(), before);
    assert_eq!(
        state
            .threads
            .iter()
            .filter(|t| t.is_agent_report() && t.subject == "Saved pages")
            .count(),
        1
    );
    assert_eq!(state.routine_report_runs.len(), 1);
    let entry = &state.routine_report_runs[0];
    assert_eq!(entry.runs, vec![run]);
    assert_eq!(entry.threads.len(), 1);
    assert_eq!(entry.routine, id);

    body["op"]["reports_json"] = json!("[]");
    body["op"]["run_id"] = json!(Uuid::new_v4());
    body["op"]["event_id"] = json!(Uuid::new_v4());
    h.client
        .post(format!("{}/v1/routines/{t}/{id}/callback", h.origin))
        .header("idempotency-key", Uuid::new_v4().to_string())
        .json(&body)
        .send()
        .await?
        .error_for_status()?;
    let state = h.server.engine().topic(t)?;
    assert_eq!(state.routine_report_runs.len(), 2);
    assert!(state.routine_report_runs[1].threads.is_empty());
    assert_eq!(state.tasks.len(), before);

    let (failed, listed) = mcp.tool("list_routines", json!({})).await?;
    assert!(!failed, "{listed}");
    let listed = listed
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["routine"] == id)
        .unwrap();
    assert_eq!(
        listed["steps"],
        json!([{"name":"Wait for data","type":"delay"},{"name":"Ask for the summary","type":"function"},{"name":"File reports","type":"function"}])
    );

    let (failed, switched) = mcp
        .tool("set_routine_enabled", json!({"routine":id,"enabled":false}))
        .await?;
    assert!(!failed, "{switched}");
    assert_eq!(
        seen.patches.lock().last().unwrap(),
        &json!({"status":"draft"})
    );
    let (failed, _) = mcp
        .tool(
            "set_routine_enabled",
            json!({"routine":"missing","enabled":true}),
        )
        .await?;
    assert!(failed);

    let (failed, allowed) = mcp
        .tool("set_routine_enabled", json!({"routine":id,"enabled":true}))
        .await?;
    assert!(!failed && allowed["status"] == "active", "{allowed}");
    for (command, status) in [
        (meep_topic::Command::ArchiveTopic, "draft"),
        (meep_topic::Command::UnarchiveTopic, "active"),
    ] {
        let before = seen.patches.lock().len();
        h.server
            .engine()
            .apply(support::envelope(t, command))
            .await?;
        tokio::time::timeout(Duration::from_secs(5), async {
            while !seen.patches.lock()[before..]
                .iter()
                .any(|patch| patch["status"] == status)
            {
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
        })
        .await
        .context("Archive transition did not reach the scheduled workflow")?;
    }
    h.server
        .engine()
        .add_rule(
            t,
            "Never activate",
            meep_topic::RuleEffect::Deny(meep_topic::ActionKind("routine-activate".into())),
        )
        .await?;
    let before = seen.patches.lock().len();
    let (failed, denied) = mcp
        .tool("set_routine_enabled", json!({"routine":id,"enabled":true}))
        .await?;
    assert!(!failed && denied["status"] == "denied", "{denied}");
    assert_eq!(seen.patches.lock().len(), before);
    configure_the_topic(&h, &mcp, t).await?;
    let setups = seen
        .descriptions
        .lock()
        .iter()
        .filter(|d| d.contains(meep_engine::SETUP_TITLE))
        .count();
    assert_eq!(setups, 1, "one setup run per topic");

    // A finished run loses its capability, and its answer closes the setup conversation.
    seen.done.store(true, Ordering::SeqCst);
    tokio::time::timeout(Duration::from_secs(9), async {
        while mcp.rpc("ping", json!({})).await?.status() != StatusCode::UNAUTHORIZED {
            tokio::time::sleep(Duration::from_millis(30)).await;
        }
        anyhow::Ok(())
    })
    .await??;
    tokio::time::timeout(Duration::from_secs(9), async {
        loop {
            let state = h.server.engine().topic(t)?;
            let setup = state
                .tasks
                .iter()
                .find(|task| task.title == meep_engine::SETUP_TITLE)
                .context("setup task")?;
            if setup.result.as_deref() == Some("Routine ready") {
                return anyhow::Ok(());
            }
            tokio::time::sleep(Duration::from_millis(30)).await;
        }
    })
    .await??;
    h.close().await?;
    provider.abort();
    Ok(())
}

/// Mission, goals and watches change through topic commands and reach device snapshots.
async fn configure_the_topic(h: &Host, mcp: &Mcp<'_>, t: TopicId) -> Result<()> {
    let (failed, topic) = mcp.tool("get_topic", json!({})).await?;
    assert!(!failed, "{topic}");
    assert_eq!(topic["mission"], "Track releases");
    for (tool, args) in [
        ("set_mission", json!({"mission":"  "})),
        ("set_mission", json!({"mission":"x","extra":1})),
        ("add_goal", json!({"text":""})),
        (
            "add_goal",
            json!({"text":"Grow","target":{"current":1,"target":2}}),
        ),
        ("watch_sources", json!({"keys":[]})),
    ] {
        let (failed, text) = mcp.tool(tool, args).await?;
        assert!(failed, "{tool}: {text}");
    }
    let (failed, text) = mcp
        .tool("watch_sources", json!({"keys":["unknown"]}))
        .await?;
    assert!(
        failed
            && text
                .as_str()
                .unwrap()
                .contains("Unknown source key unknown")
    );
    assert!(h.server.engine().topic(t)?.topic.watches().next().is_none());

    let (failed, _) = mcp
        .tool(
            "set_mission",
            json!({"mission":"Grow saved-page engagement"}),
        )
        .await?;
    assert!(!failed);
    let (failed, goal) = mcp
        .tool(
            "add_goal",
            json!({"text":"Weekly saved-page opens","target":{"current":120,"target":200,"unit":"opens"}}),
        )
        .await?;
    assert!(!failed, "{goal}");
    // A chat agent can add an exact reference without discovery, polling, or a watch.
    let reference =
        json!({"connection":"work","kind":"insight","key":"42","label":"Saved page opens"});
    let (failed, added) = mcp.tool("add_context_source", reference.clone()).await?;
    assert!(!failed, "{added}");
    assert_eq!(added["context_sources"].as_array().unwrap().len(), 1);
    let source_id = added["context_sources"][0]["id"].clone();
    assert!(h.server.engine().topic(t)?.topic.watches().next().is_none());
    let (failed, _) = mcp
        .tool(
            "add_context_source",
            json!({"connection":"ungranted","kind":"flag","key":"x","label":"X"}),
        )
        .await?;
    assert!(failed);
    let (failed, _) = mcp.tool("add_context_source", reference).await?;
    assert!(!failed);
    assert_eq!(h.server.engine().topic(t)?.topic.context_sources.len(), 1);
    let (failed, _) = mcp
        .tool("remove_context_source", json!({"id":source_id}))
        .await?;
    assert!(!failed);
    assert!(h.server.engine().topic(t)?.topic.context_sources.is_empty());
    let (failed, added) = mcp
        .tool(
            "add_context_source",
            json!({"connection":"work","kind":"feature-flag","key":"42","label":"Flag"}),
        )
        .await?;
    assert!(!failed);
    assert_eq!(added["context_sources"][0]["kind"], "flag");
    let (failed, _) = mcp
        .tool(
            "remove_context_source",
            json!({"id":added["context_sources"][0]["id"]}),
        )
        .await?;
    assert!(!failed);

    let (failed, sources) = mcp.tool("list_sources", json!({})).await?;
    assert!(!failed, "{sources}");
    assert_eq!(sources[0]["key"], "42");
    assert_eq!(sources[0]["label"], "Saved page opens");
    let (failed, watched) = mcp.tool("watch_sources", json!({"keys":["42"]})).await?;
    assert!(!failed, "{watched}");
    // Watching again keeps a single subscription.
    mcp.tool("watch_sources", json!({"keys":["42"]})).await?;

    let snapshot: meep_wire::TopicSnapshot = h
        .request(Method::GET, &format!("topics/{t}"))
        .send()
        .await?
        .error_for_status()?
        .json()
        .await?;
    let topic = snapshot.state.topic;
    assert_eq!(topic.mission, "Grow saved-page engagement");
    assert_eq!(topic.goals.len(), 1);
    assert_eq!(
        topic.goals[0].progress,
        Some(meep_topic::Progress::Target {
            current: 120.0,
            target: 200.0,
            unit: "opens".into()
        })
    );
    assert_eq!(topic.watches().count(), 1);
    assert_eq!(
        (
            topic.watches().next().unwrap().connection.as_str(),
            topic.watches().next().unwrap().kind.as_str(),
            topic.watches().next().unwrap().label.as_str()
        ),
        ("work", "insight", "Saved page opens")
    );
    Ok(())
}

#[tokio::test]
async fn setup_opens_once_and_survives_restarts() -> Result<()> {
    let seen = Seen::default();
    let (origin, provider) = posthog(seen.clone()).await?;
    let h = Host::open_with_base(tempfile::tempdir()?, Some(BASE)).await?;
    let t: TopicId = Uuid::new_v4().into();
    h.commands(vec![create(t)]).await?;
    let watch = meep_topic::Watch {
        id: Uuid::new_v4().into(),
        connection: "chat".into(),
        kind: "channel".into(),
        key: "42".into(),
        label: "Support".into(),
    };
    h.server.engine().set_watch(t, vec![watch.clone()]).await?;
    let before_setup = meep_ingest::Event {
        connection: watch.connection.clone(),
        kind: watch.kind.clone(),
        channel: watch.key.clone(),
        external_id: "while-waiting".into(),
        author: "Fixture".into(),
        text: "Buffered before sign-in".into(),
        at: chrono::Utc::now(),
        thread_hint: None,
        attributes: Value::Null,
    };
    h.server.engine().ingest(before_setup.clone()).await?;
    h.server.engine().ingest(before_setup).await?;
    assert_eq!(h.server.engine().source_observations(t, 10)?.len(), 1);
    assert!(seen.dispatches.lock().is_empty());
    // Restart before any agent can take the setup: it stays pending.
    let h = Host::open_with_base(h.close().await?, Some(BASE)).await?;
    assert!(
        h.server
            .engine()
            .topic(t)?
            .threads
            .iter()
            .all(|thread| !thread.is_agent_report())
    );
    connect(&h, &origin, t).await?;
    started(&seen).await?;
    let h = Host::open_with_base(h.close().await?, Some(BASE)).await?;
    tokio::time::sleep(Duration::from_millis(800)).await;
    let state = h.server.engine().topic(t)?;
    assert!(state.topic.default_sort.is_none());
    assert!(seen.defaults.lock().is_empty());
    assert!(seen.dispatches.lock().is_empty());
    let setups = state
        .tasks
        .iter()
        .filter(|task| task.title == meep_engine::SETUP_TITLE)
        .count();
    assert_eq!(setups, 1);
    assert!(state.threads.iter().any(|thread| {
        thread
            .messages
            .iter()
            .any(|message| message.author == "Meep")
    }));
    assert_eq!(seen.runs.lock().len(), 1);
    assert_eq!(seen.descriptions.lock().len(), 1);
    h.close().await?;
    provider.abort();
    Ok(())
}

#[tokio::test]
async fn without_a_public_base_topic_runs_start_without_tools() -> Result<()> {
    let seen = Seen::default();
    let (origin, provider) = posthog(seen.clone()).await?;
    let h = Host::new().await?;
    let t: TopicId = Uuid::new_v4().into();
    h.commands(vec![create(t)]).await?;
    connect(&h, &origin, t).await?;
    let path = format!("topics/{t}/routines");
    let sorter = h
        .request(Method::POST, &path)
        .json(&json!({"template":"sort-inbox"}))
        .send()
        .await?;
    assert_eq!(sorter.status(), StatusCode::BAD_REQUEST);
    let denied = h
        .request(Method::POST, &path)
        .json(&json!({"template":"weekly-goals"}))
        .send()
        .await?;
    assert_eq!(denied.status(), StatusCode::BAD_REQUEST);
    assert_eq!(
        denied.json::<Value>().await?["message"],
        "Routines need a public address. Set MEEP_PUBLIC_BASE_URL."
    );
    assert!(seen.defaults.lock().is_empty());
    let run = started(&seen).await?;
    assert_eq!(
        run,
        json!({"mode":"interactive","model":"claude-test","runtime_adapter":"claude"})
    );
    let description = seen.descriptions.lock()[0].clone();
    assert!(description.starts_with(&format!("[meep topic:{t}]\n")));
    assert!(description.contains(meep_engine::MEEP_SKILL.trim_end()));
    let prompt = context(&description)?;
    assert_eq!(prompt["setup"], true);
    let instructions = prompt["instructions"].as_str().unwrap();
    assert!(instructions.contains("MEEP_PUBLIC_BASE_URL is not set"));
    assert!(instructions.contains("cannot change the topic yourself"));
    let status = h
        .client
        .post(format!("{}/v1/topics/{t}/mcp", h.origin))
        .bearer_auth("anything")
        .json(&json!({"jsonrpc":"2.0","id":1,"method":"ping"}))
        .send()
        .await?
        .status();
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    h.close().await?;
    provider.abort();
    Ok(())
}

/// A host with a public base and three topics: `t`, whose setup run holds the capability under
/// test, `shared`, granted to the same PostHog account, and `stranger`, which is not.
struct Session {
    seen: Seen,
    h: Host,
    provider: tokio::task::JoinHandle<()>,
    t: TopicId,
    shared: TopicId,
    stranger: TopicId,
    token: String,
}
impl Session {
    async fn open(connection: &str) -> Result<Self> {
        let seen = Seen::default();
        let (origin, provider) = posthog(seen.clone()).await?;
        let h = Host::open_with_base(tempfile::tempdir()?, Some(BASE)).await?;
        let (t, shared, stranger): (TopicId, TopicId, TopicId) = (
            Uuid::new_v4().into(),
            Uuid::new_v4().into(),
            Uuid::new_v4().into(),
        );
        let named = |topic, name: &str| {
            support::envelope(
                topic,
                meep_topic::Command::CreateTopic {
                    name: name.into(),
                    mission: format!("Look after {name}"),
                },
            )
        };
        h.commands(vec![
            create(t),
            named(shared, "Billing"),
            named(stranger, "Private"),
        ])
        .await?;
        let grant = json!({"kind":"posthog","label":"Analytics","account":"Work","secrets":{
            "access_token":"token","region":origin,"project_id":"7"
        },"grants":[t, shared]});
        h.request(Method::PUT, &format!("connections/{connection}"))
            .json(&grant)
            .send()
            .await?
            .error_for_status()?;
        let url = format!("{BASE}/v1/topics/{t}/mcp");
        let token = until(&seen, |seen| {
            seen.runs
                .lock()
                .iter()
                .find(|r| r["imported_mcp_servers"][0]["url"] == url.as_str())
                .and_then(|r| r["imported_mcp_servers"][0]["headers"][0]["value"].as_str())
                .and_then(|v| v.strip_prefix("Bearer "))
                .map(str::to_owned)
        })
        .await?;
        Ok(Self {
            seen,
            h,
            provider,
            t,
            shared,
            stranger,
            token,
        })
    }
    fn mcp(&self) -> Mcp<'_> {
        Mcp {
            h: &self.h,
            url: format!("{}/v1/topics/{}/mcp", self.h.origin, self.t),
            token: self.token.clone(),
        }
    }
    async fn close(self) -> Result<()> {
        self.h.close().await?;
        self.provider.abort();
        Ok(())
    }
}

#[tokio::test]
async fn task_report_uses_authenticated_origin_and_preserves_citations_on_retry() -> Result<()> {
    let session = Session::open("work").await?;
    let engine = session.h.server.engine();
    until(&session.seen, |_| {
        engine.active_runs(session.t).ok()?.first().cloned()
    })
    .await?;
    let mcp = session.mcp();
    let tools: Value = mcp
        .rpc("tools/list", json!({}))
        .await?
        .error_for_status()?
        .json()
        .await?;
    let report_tool = tools["result"]["tools"]
        .as_array()
        .context("tools list")?
        .iter()
        .find(|tool| tool["name"] == "publish_report")
        .context("report tool")?;
    let schema = &report_tool["inputSchema"];
    assert_eq!(schema["required"], json!(["title"]));
    assert_eq!(
        schema["allOf"][0]["oneOf"],
        json!([{"required":["summary"]},{"required":["body"]}])
    );
    assert_eq!(
        schema["allOf"][1]["anyOf"],
        json!([
            {"required":["evidence"],"properties":{"evidence":{"minItems":1}}},
            {"required":["sources"],"properties":{"sources":{"minItems":1}}}
        ])
    );
    assert!(
        report_tool["description"]
            .as_str()
            .unwrap()
            .contains("shared destination")
    );
    assert!(
        schema["properties"]["topic"]["description"]
            .as_str()
            .unwrap()
            .contains("shared")
    );
    for invalid in [
        json!({"title":"Missing findings"}),
        json!({"title":"Missing sources", "summary":"Findings"}),
        json!({"title":"Empty evidence", "summary":"Findings", "evidence":[], "sources":[]}),
        json!({"title":"Conflicting fields", "summary":"Findings", "body":"Other findings", "sources":["Source"]}),
    ] {
        assert!(mcp.tool("publish_report", invalid).await?.0);
    }
    let args = json!({"title":"Checkout errors increased","body":"Three merchants reported timeouts after the release.","sources":["Slack #support, thread 1742"]});
    let receipt = mcp.ok("publish_report", args.clone()).await?;
    assert_eq!(mcp.ok("publish_report", args).await?, receipt);
    let state = engine.topic(session.t)?;
    let thread = state
        .threads
        .iter()
        .find(|t| json!(t.id) == receipt["thread"])
        .context("report")?;
    assert_eq!(
        thread.messages[0].reply_target(),
        Some(meep_topic::Source::Topic(session.t))
    );
    assert!(matches!(
        thread.messages[0].producer,
        meep_topic::Producer::PostHogTask(_)
    ));
    assert_eq!(
        thread.report_sources.as_ref().unwrap().references,
        ["Slack #support, thread 1742"]
    );
    assert_eq!(thread.messages.len(), 1);
    let structured = mcp.ok("publish_report", json!({"title":"Error spike", "summary":"Errors rose after the release.", "priority":"P1", "impact":"4,749 users saw the error toast.", "proposal":"Restore the retry.", "evidence":[{"description":"Checkout errors", "source_id":"https://example.org/insight", "kind":"error", "at":"2026-11-20T10:00:00Z"}]})).await?;
    let structured_state = engine.topic(session.t)?;
    let structured_thread = structured_state
        .threads
        .iter()
        .find(|t| json!(t.id) == structured["thread"])
        .context("structured report")?;
    let evidence = &structured_thread.report_sources.as_ref().unwrap().evidence;
    assert_eq!(evidence[0].description, "Checkout errors");
    assert_eq!(evidence[0].source_id, "https://example.org/insight");
    // A Scout-style report keeps its priority, impact, proposal and evidence kind.
    let sources = structured_thread.report_sources.as_ref().unwrap();
    assert_eq!(sources.priority, Some(meep_topic::ReportPriority::P1));
    assert_eq!(
        sources.impact.as_deref(),
        Some("4,749 users saw the error toast.")
    );
    assert_eq!(sources.proposal.as_deref(), Some("Restore the retry."));
    assert_eq!(evidence[0].kind.as_deref(), Some("error"));
    assert!(mcp.tool("publish_report", json!({"title":"Bad priority", "summary":"Findings", "priority":"P9", "sources":["Source"]})).await?.0);
    assert!(structured_thread.is_agent_report());
    let cross = mcp.ok("publish_report", json!({"topic":session.shared, "title":"Billing finding", "summary":"A shared account finding.", "evidence":[{"description":"Billing insight", "source_id":"https://example.org/billing"}]})).await?;
    let target = engine.topic(session.shared)?;
    let cross_thread = target
        .threads
        .iter()
        .find(|t| json!(t.id) == cross["thread"])
        .context("cross-topic report")?;
    assert!(cross_thread.is_agent_report());
    assert_eq!(
        cross_thread.messages[0].reply_target(),
        Some(meep_topic::Source::Topic(session.t))
    );
    assert!(
        cross_thread.messages[0]
            .author
            .contains(&engine.topic(session.t)?.topic.name)
    );
    let report_id = cross_thread.id;
    let task_id = Uuid::new_v4().into();
    session
        .h
        .commands(vec![support::envelope(
            session.shared,
            meep_topic::Command::AddReportTask {
                thread: report_id,
                id: task_id,
                title: "Investigate billing".into(),
                instructions: "Compare the affected cohorts".into(),
            },
        )])
        .await?;
    let target = engine.topic(session.shared)?;
    let task = target
        .tasks
        .iter()
        .find(|t| t.id == task_id)
        .context("report task")?;
    assert_eq!(task.from_thread, Some(report_id));
    assert!(task.queued);
    assert!(
        task.instructions
            .as_ref()
            .unwrap()
            .contains("A shared account finding.")
    );
    assert!(mcp.tool("publish_report", json!({"topic":session.stranger, "title":"Unauthorized", "summary":"Not shared", "evidence":[{"description":"Source", "source_id":"id"}]})).await?.0);
    assert!(
        mcp.tool(
            "publish_report",
            json!({"title":"Brief","body":"Findings","sources":[]})
        )
        .await?
        .0
    );
    session.close().await
}

#[tokio::test]
async fn the_conversation_asks_in_its_reply_instead_of_pausing() -> Result<()> {
    let session = Session::open("work").await?;
    let engine = session.h.server.engine();
    let topic = session.t;
    until(&session.seen, |_| {
        engine.active_runs(topic).ok()?.first().cloned()
    })
    .await?;
    let before = engine.topic(topic)?;
    let reply = session
        .mcp()
        .ok("ask_user", json!({"question":"Which period should I use?"}))
        .await?;
    assert_eq!(reply["status"], "ask_in_reply");
    // Nothing pauses: the conversation keeps its run and its tools.
    assert_eq!(engine.topic(topic)?.tasks, before.tasks);
    assert!(!engine.active_runs(topic)?.is_empty());
    session.close().await
}

/// Wait up to nine seconds for `f` to observe a value.
async fn until<T>(seen: &Seen, mut f: impl FnMut(&Seen) -> Option<T>) -> Result<T> {
    tokio::time::timeout(Duration::from_secs(9), async {
        loop {
            if let Some(v) = f(seen) {
                return v;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .context("timed out")
}

impl Mcp<'_> {
    /// Call a tool that must succeed.
    async fn ok(&self, name: &str, arguments: Value) -> Result<Value> {
        let (failed, value) = self.tool(name, arguments.clone()).await?;
        anyhow::ensure!(!failed, "{name} {arguments} failed: {value}");
        Ok(value)
    }
    /// Call a tool that must return a tool error, and return its message.
    async fn refused(&self, name: &str, arguments: Value) -> Result<String> {
        let (failed, value) = self.tool(name, arguments.clone()).await?;
        anyhow::ensure!(failed, "{name} {arguments} should fail: {value}");
        Ok(value.as_str().unwrap_or_default().to_owned())
    }
}

#[tokio::test]
async fn topic_tools_change_the_topic_through_commands_and_only_read_other_topics() -> Result<()> {
    let s = Session::open("work").await?;
    let (t, mcp) = (s.t, s.mcp());
    let engine = s.h.server.engine();

    let topic = mcp.ok("get_topic", json!({})).await?;
    assert_eq!(topic["counts"]["tasks_in_progress"], 1, "the setup run");
    assert!(topic.get("follow_ups").is_none());
    // Read tools reach topics shared with the account, and no others.
    let other = mcp.ok("get_topic", json!({"topic":s.shared})).await?;
    assert_eq!(other["name"], "Billing");
    let denied = mcp
        .refused("get_topic", json!({"topic":s.stranger}))
        .await?;
    assert!(denied.contains("not shared"), "{denied}");
    mcp.refused("list_facts", json!({"topic":"not-a-uuid"}))
        .await?;
    let listed = mcp.ok("list_topics", json!({})).await?;
    let ids: Vec<_> = listed
        .as_array()
        .unwrap()
        .iter()
        .map(|t| t["id"].as_str().unwrap().to_owned())
        .collect();
    assert_eq!(ids, [t.to_string(), s.shared.to_string()]);

    // Goals.
    let goal = mcp
        .ok(
            "add_goal",
            json!({"text":"Weekly saved-page opens","target":{"current":120,"target":200,"unit":"opens"}}),
        )
        .await?;
    let updated = mcp
        .ok(
            "update_goal_progress",
            json!({"goal":goal["id"],"current":150}),
        )
        .await?;
    assert_eq!(
        updated["progress"],
        json!({"Target":{"current":150.0,"target":200.0,"unit":"opens"}})
    );
    let band = mcp
        .ok(
            "add_goal",
            json!({"text":"Error rate","guardrail":{"current":0.5,"low":0,"high":1,"unit":"%"}}),
        )
        .await?;
    mcp.refused(
        "update_goal_progress",
        json!({"goal":band["id"],"current":2,"target":3}),
    )
    .await?;
    let bare = mcp.ok("add_goal", json!({"text":"Happy users"})).await?;
    mcp.refused(
        "update_goal_progress",
        json!({"goal":bare["id"],"current":1}),
    )
    .await?;
    mcp.refused(
        "update_goal_progress",
        json!({"goal":Uuid::new_v4(),"current":1}),
    )
    .await?;

    // Rules: the agent can tighten policy, never loosen it.
    let ask = mcp
        .ok(
            "add_rule",
            json!({"text":"Ask before Slack replies","effect":"ask","action_kind":"slack-reply"}),
        )
        .await?;
    let skip = mcp
        .ok(
            "add_rule",
            json!({"text":"Skip bot chatter","effect":"skip","connection":"slack","channel":"#bots"}),
        )
        .await?;
    let refusal = mcp
        .refused(
            "add_rule",
            json!({"text":"Always reply","effect":"allow","action_kind":"slack-reply"}),
        )
        .await?;
    assert!(refusal.contains("Only the person"), "{refusal}");
    mcp.refused("add_rule", json!({"text":"Ask","effect":"ask"}))
        .await?;
    mcp.refused("add_rule", json!({"text":"Skip","effect":"skip"}))
        .await?;
    mcp.refused("remove_rule", json!({"rule":ask["id"]}))
        .await?;
    mcp.ok("remove_rule", json!({"rule":skip["id"]})).await?;
    let rules = engine.topic(t)?.topic.rules;
    assert_eq!(rules.len(), 1);
    assert_eq!(rules[0].text, "Ask before Slack replies");

    for effect in ["ask", "deny"] {
        mcp.ok(
            "add_rule",
            json!({"text":"Review follow-ups","effect":effect,"action_kind":"start-follow-up"}),
        )
        .await?;
    }

    // Facts carry the run's provenance.
    let fact = mcp
        .ok("add_fact", json!({"text":"Saved pages launched in May"}))
        .await?;
    mcp.refused("add_fact", json!({"text":"  "})).await?;
    let facts = mcp.ok("list_facts", json!({})).await?;
    assert_eq!(facts[0]["text"], "Saved pages launched in May");
    assert_eq!(facts[0]["provenance"]["author"], "Meep agent");
    assert!(
        facts[0]["provenance"]["via"]
            .as_str()
            .unwrap()
            .starts_with("PostHog task "),
        "{facts}"
    );
    let corrected = mcp
        .ok(
            "supersede_fact",
            json!({"fact":fact["id"],"text":"Saved pages launched in June"}),
        )
        .await?;
    mcp.refused(
        "supersede_fact",
        json!({"fact":fact["id"],"text":"Saved pages launched in July"}),
    )
    .await?;
    let all = mcp
        .ok("list_facts", json!({"include_retired":true}))
        .await?;
    assert_eq!(all.as_array().unwrap().len(), 2);
    assert_eq!(all[0]["superseded_by"], corrected["id"]);
    mcp.ok("remove_fact", json!({"fact":corrected["id"]}))
        .await?;
    mcp.refused("remove_fact", json!({"fact":corrected["id"]}))
        .await?;
    assert_eq!(mcp.ok("list_facts", json!({})).await?, json!([]));

    // Sources.
    mcp.ok("watch_sources", json!({"keys":["42"]})).await?;
    assert_eq!(
        mcp.ok("unwatch_sources", json!({"keys":["42"]})).await?,
        json!([])
    );
    let missing = mcp
        .refused("unwatch_sources", json!({"keys":["42"]}))
        .await?;
    assert!(missing.contains("does not watch"), "{missing}");

    // Writes never reach another topic, and the shared topic stays untouched.
    for (tool, args) in [
        ("add_fact", json!({"text":"Leaked","topic":s.shared})),
        (
            "set_mission",
            json!({"mission":"Taken over","topic":s.shared}),
        ),
        ("add_task", json!({"title":"Foreign","topic":s.stranger})),
    ] {
        let message = mcp.refused(tool, args).await?;
        assert!(message.contains("read-only"), "{tool}: {message}");
    }
    let untouched = engine.topic(s.shared)?;
    assert!(untouched.topic.facts.is_empty());
    assert_eq!(untouched.topic.mission, "Look after Billing");

    // Every change is an ordinary topic revision that devices receive.
    let snapshot: meep_wire::TopicSnapshot =
        s.h.request(Method::GET, &format!("topics/{t}"))
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
    let topic = snapshot.state.topic;
    assert_eq!(topic.goals.len(), 3);
    assert_eq!(topic.rules.len(), 3);
    assert_eq!(topic.facts.len(), 2);
    assert!(topic.watches().next().is_none());
    s.close().await
}

#[tokio::test]
async fn inbox_task_and_file_tools_leave_approval_with_the_person() -> Result<()> {
    let s = Session::open("work").await?;
    let (t, mcp) = (s.t, s.mcp());
    let engine = s.h.server.engine();

    // Bind an existing workflow, run it, and let it ask the inbox a question.
    let initial = engine.topic(t)?.tasks;
    let bound = mcp
        .ok("bind_routine", json!({"flow_id":EXISTING_FLOW}))
        .await?;
    assert_eq!(engine.topic(t)?.tasks.len(), initial.len());
    assert!(
        initial
            .iter()
            .any(|task| task.id.to_string() == bound["task"].as_str().unwrap())
    );
    assert_eq!(bound["routine"], "signup-digest");
    assert_eq!(bound["status"], "awaiting_approval");
    assert!(engine.routine_secret(t, "signup-digest").is_err());
    engine
        .approve(
            t,
            serde_json::from_value(bound["task"].clone())?,
            None,
            false,
        )
        .await?;
    engine.tick_topic(t).await?;
    let again = mcp
        .refused("bind_routine", json!({"flow_id":EXISTING_FLOW}))
        .await?;
    assert!(again.contains("already bound"), "{again}");
    mcp.refused("bind_routine", json!({"flow_id":Uuid::new_v4()}))
        .await?;
    let run = mcp
        .ok("run_routine", json!({"routine":"signup-digest"}))
        .await?;
    assert_eq!(run["status"], "awaiting_approval");
    assert!(s.seen.dispatches.lock().is_empty());
    engine
        .approve(t, serde_json::from_value(run["task"].clone())?, None, false)
        .await?;
    engine.tick_topic(t).await?;
    assert_eq!(
        s.seen.dispatches.lock()[0].0.to_string(),
        EXISTING_FLOW,
        "the routine ran in PostHog"
    );
    mcp.refused("run_routine", json!({"routine":"missing"}))
        .await?;
    let secret = engine.routine_secret(t, "signup-digest")?;
    let rejected = s.h.client.post(format!("{}/v1/routines/{t}/signup-digest/callback", s.h.origin))
        .header("idempotency-key", Uuid::new_v4().to_string())
        .json(&json!({"secret":secret,"op":{"kind":"Ask","text":"Signups dropped 20%. Tell the team?"}}))
        .send().await?;
    assert!(!rejected.status().is_success());
    assert!(
        mcp.ok("list_threads", json!({}))
            .await?
            .as_array()
            .unwrap()
            .is_empty()
    );

    // Files are revisioned and refuse stale writes.
    let path = "notes/plan.md";
    let first = mcp
        .ok(
            "write_file",
            json!({"path":path,"text":"v1","expected_revision":0}),
        )
        .await?;
    assert_eq!(first["revision"], 1);
    let stale = mcp
        .refused(
            "write_file",
            json!({"path":path,"text":"v1b","expected_revision":0}),
        )
        .await?;
    assert!(stale.contains("Read it again"), "{stale}");
    mcp.ok(
        "write_file",
        json!({"path":path,"text":"v2","expected_revision":1}),
    )
    .await?;
    let read = mcp.ok("read_file", json!({"path":path})).await?;
    assert_eq!(
        (read["text"].as_str(), read["revision"].as_u64()),
        (Some("v2"), Some(2))
    );
    let earlier = mcp
        .ok("read_file", json!({"path":path,"revision":1}))
        .await?;
    assert_eq!(earlier["text"], "v1");
    assert_eq!(
        mcp.ok("list_files", json!({})).await?,
        json!([{"path":path,"revision":2,"bytes":2}])
    );
    mcp.refused("read_file", json!({"path":"../secrets"}))
        .await?;
    mcp.refused("read_file", json!({"path":path,"topic":s.shared}))
        .await?;
    mcp.refused(
        "write_file",
        json!({"path":path,"text":"x","expected_revision":0,"topic":s.shared}),
    )
    .await?;
    assert!(engine.blobs().names(s.shared)?.is_empty());
    s.close().await
}

#[tokio::test]
async fn workspace_tools_start_topic_setup_and_views_and_every_task_is_attributed() -> Result<()> {
    // The view worker uses the account named posthog.
    let s = Session::open("posthog").await?;
    let mcp = s.mcp();
    let engine = s.h.server.engine();

    let created = mcp
        .ok(
            "create_topic",
            json!({"name":"Pricing","mission":"Keep pricing pages converting"}),
        )
        .await?;
    assert_eq!(created["setup"], "starting");
    let id: TopicId = serde_json::from_value(created["id"].clone())?;
    let marker = format!("[meep topic:{id}]\n");
    until(&s.seen, |seen| {
        seen.descriptions
            .lock()
            .iter()
            .any(|d| d.starts_with(&marker))
            .then_some(())
    })
    .await?;
    let state = engine.topic(id)?;
    assert_eq!(state.topic.mission, "Keep pricing pages converting");
    assert_eq!(state.threads[0].messages[0].author, "Meep");
    assert!(
        state
            .tasks
            .iter()
            .any(|t| t.title == meep_engine::SETUP_TITLE)
    );
    mcp.refused("create_topic", json!({"name":"","mission":"x"}))
        .await?;
    mcp.refused("create_topic", json!({"name":"x"})).await?;

    let view = mcp
        .ok("create_view", json!({"prompt":"Chart weekly signups"}))
        .await?;
    let view_marker = format!("[meep view:{}]\n", view["id"].as_str().unwrap());
    until(&s.seen, |seen| {
        seen.descriptions
            .lock()
            .iter()
            .any(|d| d.starts_with(&view_marker))
            .then_some(())
    })
    .await?;
    let views = mcp.ok("list_views", json!({})).await?;
    assert_eq!(views[0]["id"], view["id"]);
    assert_eq!(views[0]["latest_request"], "Chart weekly signups");
    mcp.refused("create_view", json!({"prompt":" "})).await?;

    engine.add_task(s.t, "Summarize pricing tests").await?;
    until(&s.seen, |seen| {
        seen.descriptions
            .lock()
            .iter()
            .filter(|d| d.starts_with("[meep topic:"))
            .filter_map(|d| context(d).ok())
            .any(|c| c["task"]["title"] == "Summarize pricing tests" && c["setup"].is_null())
            .then_some(())
    })
    .await?;

    // One setup per topic, even after more work and a moment to settle.
    tokio::time::sleep(Duration::from_millis(400)).await;
    let descriptions = s.seen.descriptions.lock().clone();
    for topic in [s.t, s.shared, id] {
        let setups = descriptions
            .iter()
            .filter(|d| d.starts_with(&format!("[meep topic:{topic}]\n")))
            .filter_map(|d| context(d).ok())
            .filter(|c| c["setup"] == true)
            .count();
        assert_eq!(setups, 1, "one setup for {topic}");
    }
    // Every PostHog task Meep created carries its marker and the Meep skill, and no origin.
    assert!(descriptions.len() >= 5, "{}", descriptions.len());
    for d in &descriptions {
        let (marker, rest) = d.split_once('\n').unwrap();
        assert!(
            marker.starts_with("[meep topic:") || marker.starts_with("[meep view:"),
            "{marker}"
        );
        assert!(rest.starts_with(meep_engine::MEEP_SKILL.trim_end()));
    }
    assert!(s.seen.origins.lock().iter().all(Option::is_none));
    s.close().await
}

#[tokio::test]
async fn chat_creates_a_manual_source_flow_reports_its_observation_and_returns_the_watch()
-> Result<()> {
    let session = Session::open("work").await?;
    let mcp = session.mcp();
    let topic = session.t;
    mcp.ok("watch_sources", json!({"keys":["42"]})).await?;
    let before = session
        .h
        .server
        .engine()
        .topic(topic)?
        .topic
        .watches()
        .next()
        .unwrap()
        .clone();
    let created = mcp.ok("create_routine", json!({
        "name":"Review source","trigger":{"type":"source","keys":["42"]},
        "steps":[{"name":"Record outcome","kind":"report_to_topic","config":{"op":"drop","reason":"Already reviewed"}}]
    })).await?;
    if created["status"] == "awaiting_approval" {
        session
            .h
            .server
            .engine()
            .approve(
                topic,
                serde_json::from_value(created["task"].clone())?,
                None,
                false,
            )
            .await?;
        session.h.server.engine().tick_topic(topic).await?;
    }
    assert_eq!(created["routine"]["id"], "review-source");
    assert_eq!(created["routine"]["watches"], json!([before]));
    assert_eq!(
        session.seen.flows.lock().last().unwrap()["actions"][0]["config"]["type"],
        "manual"
    );
    let mut body = session
        .seen
        .patches
        .lock()
        .iter()
        .rev()
        .find_map(|v| {
            v["actions"][1]["config"]["inputs"]["body"]["value"]
                .as_object()
                .cloned()
        })
        .context("callback body")?;
    assert_eq!(body["op"]["observation"], "{variables.observation}");
    let event = meep_ingest::Event {
        connection: before.connection.clone(),
        kind: before.kind.clone(),
        channel: before.key.clone(),
        external_id: "sample".into(),
        thread_hint: None,
        at: chrono::Utc::now(),
        author: "Fixture".into(),
        text: "Observed update".into(),
        attributes: Value::Null,
    };
    let engine = session.h.server.engine();
    let initial_threads = engine.topic(topic)?.threads.len();
    engine.ingest(event.clone()).await?;
    engine.ingest(event).await?;
    let vars = session
        .seen
        .dispatches
        .lock()
        .last()
        .context("source dispatch")?
        .1["variables"]
        .clone();
    assert_eq!(vars["text"], "Observed update");
    assert_eq!(vars["channel"], "42");
    assert_eq!(vars["author"], "Fixture");
    assert!(
        session.seen.flows.lock().last().unwrap()["variables"]
            .as_array()
            .unwrap()
            .contains(&json!({"key":"confidence","type":"number","default":0}))
    );
    body.get_mut("op").unwrap()["observation"] = vars["observation"].clone();
    session
        .h
        .client
        .post(format!(
            "{}/v1/routines/{topic}/review-source/callback",
            session.h.origin
        ))
        .header("Idempotency-Key", Uuid::new_v4().to_string())
        .json(&body)
        .send()
        .await?
        .error_for_status()?;
    assert_eq!(engine.topic(topic)?.threads.len(), initial_threads);
    let list = mcp.ok("list_routines", json!({})).await?;
    let item = list
        .as_array()
        .context("routine list")?
        .iter()
        .find(|r| r["routine"] == "review-source")
        .context("source routine")?;
    assert_eq!(
        item["observations"][0]["outcome"]["Dropped"]["reason"],
        "Already reviewed"
    );
    let moved = mcp
        .ok(
            "set_routine_sources",
            json!({"routine":"review-source","keys":[]}),
        )
        .await?;
    assert_eq!(moved["watches"], json!([]));
    assert!(
        engine
            .topic(topic)?
            .topic
            .routines
            .iter()
            .find(|r| r.binding.id == "review-source")
            .unwrap()
            .binding
            .watches
            .is_empty()
    );
    session.close().await
}

#[tokio::test]
async fn server_without_public_callback_records_the_failure_without_an_inbox_item() -> Result<()> {
    let h = Host::open_with_base(tempfile::tempdir()?, None).await?;
    let topic = Uuid::new_v4().into();
    h.commands(vec![create(topic)]).await?;
    let engine = h.server.engine();
    engine
        .bind_routine(
            topic,
            meep_topic::RoutineBinding {
                id: "remote".into(),
                name: "Remote".into(),
                backend: "posthog".into(),
                trigger: "Source event".into(),
                external_id: Uuid::new_v4().to_string(),
                watches: vec![meep_topic::Watch {
                    id: Uuid::new_v4().into(),
                    connection: "slack".into(),
                    kind: "channel".into(),
                    key: "C1".into(),
                    label: "fixture".into(),
                }],
            },
        )
        .await?;
    engine
        .ingest(meep_ingest::Event {
            connection: "slack".into(),
            kind: "channel".into(),
            channel: "C1".into(),
            external_id: "offline".into(),
            thread_hint: None,
            author: "Fixture".into(),
            text: "New update".into(),
            attributes: Value::Null,
            at: chrono::Utc::now(),
        })
        .await?;
    engine.sort_pending(topic).await?;
    let state = engine.topic(topic)?;
    assert!(state.threads.is_empty());
    assert!(
        matches!(&state.topic.routines[0].observations[0].outcome,meep_topic::ObservationOutcome::Failed {reason} if reason.contains("MEEP_PUBLIC_BASE_URL"))
    );
    h.close().await?;
    Ok(())
}

#[tokio::test]
async fn workflow_details_reports_manual_run_capability() -> Result<()> {
    let session = Session::open("work").await?;
    let engine = session.h.server.engine();
    let topic = session.t;
    engine
        .bind_routine(
            topic,
            meep_topic::RoutineBinding {
                id: "manual-fixture".into(),
                name: "Manual fixture".into(),
                trigger: "Manual".into(),
                backend: "posthog".into(),
                external_id: EXISTING_FLOW.into(),
                watches: vec![],
            },
        )
        .await?;
    let details: meep_wire::WorkflowDetails = session
        .h
        .request(Method::GET, &format!("routines/{topic}/manual-fixture"))
        .send()
        .await?
        .error_for_status()?
        .json()
        .await?;
    assert_eq!(details.manual_run_allowed, Some(true));
    session.close().await
}

#[tokio::test]
async fn default_workflow_fetches_only_its_pending_item_and_reports_each_branch_once() -> Result<()>
{
    use meep_topic::ObservationOutcome;
    let session = Session::open("work").await?;
    let engine = session.h.server.engine();
    let topic = session.t;
    let routine = "explicit-source";
    let watch = meep_topic::Watch {
        id: Uuid::new_v4().into(),
        connection: "work".into(),
        kind: "channel".into(),
        key: "test-sort".into(),
        label: "Workflow fixture".into(),
    };
    engine
        .bind_routine(
            topic,
            meep_topic::RoutineBinding {
                id: routine.into(),
                name: "Explicit source".into(),
                trigger: "Source event".into(),
                backend: "posthog".into(),
                external_id: EXISTING_FLOW.into(),
                watches: vec![watch.clone()],
            },
        )
        .await?;
    let secret = engine.routine_secret(topic, routine)?;
    let path = format!("{}/v1/routines/{topic}/{routine}", session.h.origin);
    for category in ["inbox", "drop", "investigate", "needs_you"] {
        let text = format!("Source evidence for {category} {}", "🐾".repeat(2000));
        engine
            .ingest(meep_ingest::Event {
                connection: watch.connection.clone(),
                kind: watch.kind.clone(),
                channel: watch.key.clone(),
                external_id: category.into(),
                thread_hint: None,
                at: chrono::Utc::now(),
                author: "Fixture".into(),
                text: text.clone(),
                attributes: Value::Null,
            })
            .await?;
        let vars = session
            .seen
            .dispatches
            .lock()
            .last()
            .context("missing dispatch")?
            .1["variables"]
            .clone();
        assert!(vars["observation"].is_string());
        let observation = &vars["observation"];
        let fetch = session.h.client.post(format!("{path}/sort-context"));
        let request = json!({"observation":observation,"secret":secret});
        assert!(
            !fetch
                .try_clone()
                .unwrap()
                .json(&json!({"observation":observation,"secret":"wrong"}))
                .send()
                .await?
                .status()
                .is_success()
        );
        let context: Value = fetch
            .try_clone()
            .unwrap()
            .json(&request)
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        assert!(
            context["context"]
                .as_str()
                .unwrap()
                .contains("Track releases")
        );
        assert!(
            context["context"]
                .as_str()
                .unwrap()
                .contains(&format!("Source evidence for {category}"))
        );
        assert!(context.to_string().len() < 4096);
        let report = session.h.client.post(format!("{path}/callback")).header("Idempotency-Key",Uuid::new_v4().to_string()).json(&json!({"secret":secret,"op":{"kind":"Classified","category":category,"observation":observation}}));
        if category == "needs_you" {
            assert!(!report.send().await?.status().is_success());
            assert!(
                engine.topic(topic)?.threads.iter().all(|thread| !matches!(
                    thread.state,
                    meep_topic::ThreadState::NeedsYou { .. }
                ))
            );
            continue;
        }
        report
            .try_clone()
            .unwrap()
            .send()
            .await?
            .error_for_status()?;
        report.send().await?.error_for_status()?;
        assert!(!fetch.json(&request).send().await?.status().is_success());
        let state = engine.topic(topic)?;
        let info = state
            .topic
            .routines
            .iter()
            .find(|r| r.binding.id == routine)
            .unwrap();
        let result = &info
            .observations
            .iter()
            .find(|o| json!(o.key) == *observation)
            .unwrap()
            .outcome;
        match (category, result) {
            ("investigate", ObservationOutcome::Task(id)) => {
                let task = state.tasks.iter().find(|t| t.id == *id).unwrap();
                assert_eq!(
                    task.assignment,
                    Some(meep_topic::InboxAssignment::Investigate)
                );
                assert!(task.log.iter().any(|l| l.text == text));
            }
            ("inbox", ObservationOutcome::Inboxed(_))
            | ("drop", ObservationOutcome::Dropped { .. }) => {}
            unexpected => panic!("unexpected outcome {unexpected:?}"),
        }
    }
    session.close().await
}

#[tokio::test]
async fn template_catalog_and_creation_build_the_documented_graphs() -> Result<()> {
    let s = Session::open("work").await?;
    let path = format!("topics/{}/routines", s.t);
    let catalog: Vec<Value> =
        s.h.request(Method::GET, "routine-templates")
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
    assert_eq!(
        s.mcp().ok("list_routine_templates", json!({})).await?,
        json!(catalog)
    );
    assert_eq!(catalog.len(), 4);
    assert!(
        catalog
            .iter()
            .all(|entry| entry["id"] != "sort-inbox" && entry["id"] != "urgent-only")
    );
    let rejected = s.h.request(Method::POST, &path).json(&json!({"name":"Obsolete sorter","trigger":{"type":"source","keys":[]},"steps":[{"name":"Sort","kind":"system1_sort","config":{}}]})).send().await?;
    assert_eq!(rejected.status(), StatusCode::UNPROCESSABLE_ENTITY);
    let obs = "{variables.observation}";
    for (id, expected) in [
        ("scout", vec![]),
        ("daily-brief", vec![]),
        ("weekly-goals", vec![]),
        (
            "digest-then-drop",
            vec![
                json!({"kind":"Note","text":"{variables.text}"}),
                json!({"kind":"Drop","reason":"Recorded in activity","observation":obs}),
            ],
        ),
    ] {
        let sources = if id == "urgent-only" {
            vec!["42"]
        } else {
            vec![]
        };
        let binding: Value =
            s.h.request(Method::POST, &path)
                .json(&json!({"template":id,"sources":sources}))
                .send()
                .await?
                .error_for_status()?
                .json()
                .await?;
        assert_eq!(binding["backend"], "posthog");
        assert_eq!(binding["watches"].as_array().unwrap().len(), sources.len());
        let flow = s.seen.flows.lock().last().cloned().unwrap();
        assert_eq!(
            flow["actions"][0]["config"]["type"],
            if matches!(id, "scout" | "daily-brief" | "weekly-goals") {
                "schedule"
            } else {
                "manual"
            }
        );
        if expected.is_empty() {
            let agent = &flow["actions"][1];
            assert_eq!(
                agent["config"]["template_id"],
                "template-posthog-create-task"
            );
            assert!(
                agent["config"]["inputs"]["prompt"]["value"]
                    .as_str()
                    .unwrap()
                    .contains(&templates_text(id))
            );
            assert_eq!(
                flow["actions"][2]["config"]["inputs"]["body"]["value"]["op"]["kind"],
                "Report"
            );
            continue;
        }
        assert_eq!(
            flow["actions"].as_array().unwrap().len(),
            expected.len() + 2
        );
        for (i, op) in expected.iter().enumerate() {
            assert_eq!(
                &flow["actions"][i + 1]["config"]["inputs"]["body"]["value"]["op"],
                op
            );
        }
    }
    let schedules = s.seen.schedules.lock().clone();
    // Scout runs an hour before the brief, so the brief can mention its findings.
    assert_eq!(
        schedules[0]["rrule"],
        "FREQ=DAILY;BYHOUR=8;BYMINUTE=0;BYSECOND=0"
    );
    assert_eq!(
        schedules[1]["rrule"],
        "FREQ=DAILY;BYHOUR=9;BYMINUTE=0;BYSECOND=0"
    );
    assert_eq!(
        schedules[2]["rrule"],
        "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0;BYSECOND=0"
    );
    assert!(schedules.iter().all(|s| s["timezone"] == "UTC"));
    let created = s
        .mcp()
        .ok("create_routine", json!({"template":"daily-brief"}))
        .await?;
    assert_eq!(created["status"], "awaiting_approval");
    s.close().await
}

#[tokio::test]
async fn an_approved_event_flow_dispatches_only_matching_moves_and_audits_the_key() -> Result<()> {
    use meep_topic::{Column, Command};
    let s = Session::open("work").await?;
    let e = s.h.server.engine();
    let address = "https://events.example.test/tunnel";
    let setting = s.h.request(Method::PUT, "settings/public-base-url");
    assert_eq!(
        setting
            .try_clone()
            .unwrap()
            .json(&json!({"public_base_url":"http://example.test"}))
            .send()
            .await?
            .status(),
        StatusCode::BAD_REQUEST
    );
    setting
        .json(&json!({"public_base_url":address}))
        .send()
        .await?
        .error_for_status()?;
    let settings: Value =
        serde_json::from_slice(&std::fs::read(s.h.dir.path().join("settings.json"))?)?;
    assert_eq!(settings["public_base_url"], address);
    let created = s.mcp().ok("create_routine", json!({
        "name":"Record completion",
        "trigger":{"type":"event","on":"task_moved","filter":{"to":"done","title":"Publish"}},
        "steps":[{"name":"Record","kind":"report_to_topic","config":{"op":"note","text":"Completed {variables.title}"}}]
    })).await?;
    let draft = s.seen.flows.lock().last().unwrap().clone();
    assert_eq!(
        draft["actions"][1]["config"]["inputs"]["url"]["value"],
        format!("{address}/v1/routines/{}/record-completion/callback", s.t)
    );
    let trigger = &draft["actions"][0]["config"];
    assert_eq!(trigger["template_id"], "template-source-webhook");
    assert_eq!(
        trigger["inputs"],
        json!({"event":{"value":"$workflow_triggered"},"distinct_id":{"value":"{request.body.user_id}"},"method":{"value":"POST"}})
    );
    let task = Uuid::new_v4().into();
    s.h.commands(vec![support::envelope(
        s.t,
        Command::AddConfiguredTask {
            untitled: false,
            id: task,
            title: "Publish".into(),
            start: false,
            model: None,
            reasoning_effort: None,
            billing: None,
            instructions: None,
        },
    )])
    .await?;
    e.move_task(s.t, task, Column::Done).await?;
    e.approve(
        s.t,
        serde_json::from_value(created["task"].clone())?,
        None,
        false,
    )
    .await?;
    e.tick_topic(s.t).await?;
    e.move_task(s.t, task, Column::NeedsYou).await?;
    assert!(s.seen.dispatches.lock().is_empty());
    let finish = support::envelope(
        s.t,
        Command::MoveTask {
            task,
            column: Column::Done,
        },
    );
    s.h.commands(vec![finish.clone(), finish]).await?;
    e.tick_topic(s.t).await?;
    let state = e.topic(s.t)?;
    assert_eq!(state.usage.today(chrono::Utc::now()).routine_dispatches, 1);
    let routine = state
        .topic
        .routines
        .iter()
        .find(|r| r.binding.id == "record-completion")
        .unwrap();
    assert_eq!(routine.observations.len(), 1);
    let sent = s.seen.dispatches.lock();
    assert_eq!(sent.len(), 1);
    let body = &sent[0].1;
    let vars = &body["variables"];
    assert_eq!(vars["observation"], routine.observations[0].key.to_string());
    assert_eq!(vars["event"], "task_moved");
    assert_eq!(vars["from"], "needsYou");
    assert_eq!(vars["to"], "done");
    assert_eq!(vars["task"], task.to_string());
    for key in vars.as_object().unwrap().keys() {
        assert!(
            draft["variables"]
                .as_array()
                .unwrap()
                .contains(&json!({"key":key,"type":"string","default":""}))
        );
    }
    Ok(())
}

/// The brief a template's task step carries, read from the shipped catalogue.
fn templates_text(id: &str) -> String {
    let all: Value = serde_json::from_str(include_str!("../src/routine_templates.json")).unwrap();
    all.as_array()
        .unwrap()
        .iter()
        .find(|t| t["id"] == id)
        .unwrap()["steps"][0]["config"]["text"]
        .as_str()
        .unwrap()
        .to_owned()
}
