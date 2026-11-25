//! All accounts, inbox examples and native preview fixtures live in this test module.
use super::*;
use ::gpui;
use anyhow::Context as _;
use axum::{
    Json, Router,
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
};
use core::prelude::v1::test;
use gpui::{TestAppContext, VisualTestContext};
use meep_client::HttpTransport;
use meep_engine::{DirBlobs, SqliteStore};
use meep_server::{Connectors, DeviceTokens, FileSecrets, Server};
use serde_json::{Value, json};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use tempfile::TempDir;
use tokio::net::TcpListener;

struct Lab {
    runtime: Arc<Runtime>,
    backend: Backend,
    server: Server,
    origin: String,
    upstream: Arc<Upstream>,
    shutdown: Option<tokio::sync::oneshot::Sender<()>>,
    serving: tokio::task::JoinHandle<Result<()>>,
    _dir: TempDir,
}
impl Lab {
    fn open() -> Result<Self> {
        Self::with_snapshots([])
    }
    fn with_snapshots(snapshots: impl IntoIterator<Item = TopicState>) -> Result<Self> {
        let runtime = Arc::new(Runtime::new()?);
        let dir = tempfile::tempdir()?;
        let root = dir.path();
        let upstream = Arc::new(Upstream {
            active: AtomicBool::new(true),
            ..Default::default()
        });
        let (backend, server, origin, shutdown, serving) = runtime.block_on(async {
            let ph = TcpListener::bind("127.0.0.1:0").await?;
            let origin = format!("http://{}", ph.local_addr()?);
            let api = posthog(upstream.clone(), origin.clone());
            tokio::spawn(async move {
                let _ = axum::serve(ph, api).await;
            });
            let store = SqliteStore::open(root)?;
            for state in snapshots {
                use meep_engine::{Store, StoredTopic};
                // A restored review snapshot holds its board at the observed instant.
                // A live worker may still process new commands and incoming messages.
                let held: BTreeMap<_, _> = state
                    .tasks
                    .iter()
                    .filter(|t| matches!(t.column, Column::Todo | Column::InProgress))
                    .map(|t| (t.id.to_string(), "Stopped"))
                    .collect();
                let mut snapshot = serde_json::to_value(state)?;
                snapshot["runs"] = json!(held);
                let mut saved: StoredTopic = serde_json::from_value(snapshot)?;
                saved.revision = 1;
                store.save(0, &saved, None, &[])?;
            }
            let fixture_gateway = meep_ai::Gateway::new(
                meep_ai::Config {
                    base_url: origin.clone(),
                    ..Default::default()
                },
                Arc::new("test-session".to_owned()),
            )?;
            let server = Server::with_fixture_sorter(
                Arc::new(store),
                Arc::new(DirBlobs::open(root.join("files"))?),
                Arc::new(meep_connectors::StoreState::new(
                    meep_store::Connection::open(root.join("checkpoints"))?,
                )?),
                Box::new(FileSecrets::open(root.join("secrets"))?),
                Arc::new(DeviceTokens::open(root)?),
                Arc::new(Connectors),
                Arc::new(meep_engine::ModelSorter::new(
                    Arc::new(fixture_gateway),
                    0.75,
                )?),
            )
            .await?
            // These UI fixtures seed their own topics. Setup is covered in meep-server.
            .without_topic_setup()
            .with_public_base("https://topics.example.test/tunnel")?;
            let listener = TcpListener::bind("127.0.0.1:0").await?;
            let address = format!("http://{}", listener.local_addr()?);
            let (shutdown, stopped) = tokio::sync::oneshot::channel();
            let serving = tokio::spawn(server.clone().serve(listener, async {
                let _ = stopped.await;
            }));
            let device = std::fs::read_to_string(root.join("device-token"))?;
            let client = Client::open(
                root.join("replica.sqlite"),
                Arc::new(HttpTransport::new(&address, device.trim())?),
            )?;
            client
                .register_connection("posthog", &registration(&origin))
                .await?;
            client.set_preference(
                "posthog-project",
                &json!({"label":"Design","email":"design@example.test","region":"Us","project":7}),
            )?;
            client.set_preference("signed-in", &true)?;
            Ok::<_, anyhow::Error>((
                Backend {
                    direct: None,
                    client,
                    credentials: address.clone(),
                    server: address,
                    root: root.to_owned(),
                },
                server,
                origin,
                shutdown,
                serving,
            ))
        })?;
        Ok(Self {
            runtime,
            backend,
            server,
            origin,
            upstream,
            shutdown: Some(shutdown),
            serving,
            _dir: dir,
        })
    }
    fn disconnect(&mut self) -> Result<()> {
        self.shutdown
            .take()
            .context("server already stopped")?
            .send(())
            .ok();
        self.runtime.block_on(&mut self.serving)??;
        Ok(())
    }
    /// Deliver an inbox observation to the loopback sorter's controlled gateway.
    async fn gateway_event(&self, mode: &str, text: &str) -> Result<()> {
        self.server
            .engine()
            .ingest(meep_ingest::Event {
                connection: "slack".into(),
                kind: "channel".into(),
                channel: "design".into(),
                external_id: mode.into(),
                thread_hint: Some(mode.into()),
                author: "Maya Chen".into(),
                at: chrono::Utc::now(),
                text: text.into(),
                attributes: json!({"gateway":mode}),
            })
            .await?;
        Ok(())
    }
    fn publish_sample_reports(&self, topic: TopicId) -> Result<Vec<ThreadId>> {
        self.runtime.block_on(async {
            let engine = self.server.engine();
            self.upstream.hold_task_runs.store(true, Ordering::SeqCst);
            engine.add_task(topic, "Publish fixture reports").await?;
            engine.tick_topic(topic).await?;
            let run = tokio::time::timeout(std::time::Duration::from_secs(10), async {
                loop {
                    if let Some(run) = engine.active_runs(topic)?.pop() {
                        break Ok::<_, anyhow::Error>(run);
                    }
                    tokio::time::sleep(std::time::Duration::from_millis(20)).await;
                }
            })
            .await??;
            let mut ids = vec![];
            for (title, body) in [
                (
                    "Navigation migration",
                    "Five components still use the old navigation.",
                ),
                (
                    "Pilot feedback",
                    "Pilot teams want search to remain in the sidebar.",
                ),
            ] {
                let report = engine
                    .publish_task_report(
                        topic,
                        &run,
                        title,
                        body,
                        vec!["Design review notes, 23 November".into()],
                    )
                    .await?;
                ids.push(report);
            }
            self.backend.client.sync_once().await?;
            Ok(ids)
        })
    }
    fn seed(&self) -> Result<TopicId> {
        self.seed_with_label("Slack")
    }
    fn seed_with_label(&self, service: &str) -> Result<TopicId> {
        let id = TopicId(Uuid::new_v4());
        let c = &self.backend.client;
        c.create_topic(
            id,
            "New web".into(),
            "Simplify the new web navigation.".into(),
            "posthog",
        )?;
        c.issue(
            id,
            Command::SetWatch {
                watches: vec![Watch {
                    id: WatchId(Uuid::new_v4()),
                    connection: "slack".into(),
                    kind: "channel".into(),
                    key: "design".into(),
                    label: "Design".into(),
                }],
            },
        )?;
        c.issue(
            id,
            Command::AddGoal {
                goal: Goal {
                    id: GoalId(Uuid::new_v4()),
                    text: "Migrate the navigation components".into(),
                    progress: Some(Progress::Target {
                        current: 3.,
                        target: 5.,
                        unit: "components".into(),
                    }),
                },
            },
        )?;
        c.issue(
            id,
            Command::SetRoutine {
                routine: RoutineBinding {
                    watches: vec![],
                    id: "review".into(),
                    name: "Weekly review".into(),
                    trigger: "Every Monday".into(),
                    backend: "posthog".into(),
                    external_id: Uuid::new_v4().to_string(),
                },
            },
        )?;
        self.server
            .engine()
            .add_connection(meep_connections::Connection {
                unrouted: 0,
                id: "slack".into(),
                kind: "slack".into(),
                label: service.into(),
                account: "Design".into(),
                health: meep_connections::Health::Ok {
                    checked_at: chrono::Utc::now(),
                },
                grants: vec![id],
            })?;
        self.runtime.block_on(async {
            c.sync_once().await?;
            for (key, text, attributes) in [
                (
                    "rail",
                    "Pushback on five rail items",
                    json!({"needs_decision":true, "summary":"The team has six candidates for five rail slots.", "reason":"Choose which rail item the team can move into More.", "draft":"Which item would the sixth replace?"}),
                ),
                (
                    "migration",
                    "Five components left to migrate",
                    json!({"summary":"The remaining work is isolated to the five legacy components.", "fact":"Five navigation components still use the old layout."}),
                ),
            ] {
                self.server
                    .engine()
                    .ingest(meep_ingest::Event {
                        connection: "slack".into(),
                        kind: "channel".into(),
                        channel: "design".into(),
                        thread_hint: Some(key.into()),
                        external_id: key.into(),
                        author: "Design".into(),
                        at: chrono::Utc::now(),
                        text: text.into(),
                        attributes,
                    })
                    .await?;
            }
            self.server.engine().sort_pending(id).await?;
            c.put_file(id, "notes/review.md", b"Navigation review notes".to_vec())
                .await?;
            c.sync_once().await?;
            c.refresh_files(id).await?;
            tokio::time::timeout(std::time::Duration::from_secs(4), async {
                loop {
                    if c.refresh_workflow(id, "review").await.is_ok() {
                        break;
                    }
                    tokio::time::sleep(std::time::Duration::from_millis(25)).await;
                }
            })
            .await?;
            Ok::<_, anyhow::Error>(())
        })?;
        Ok(id)
    }
}

const GITHUB_INSTALLATION: &str = "00000000-0000-4000-8000-000000000006";
const INSTALLATION: &str = "00000000-0000-4000-8000-000000000005";

fn routine_run_times(flow: Uuid) -> [chrono::DateTime<chrono::Utc>; 3] {
    use chrono::{Datelike, Duration, Local, TimeZone, Utc, Weekday};

    let now = Local::now();
    let (hour, minute) = match flow.as_u128() {
        11 => (9, 0),
        13 => (16, 30),
        _ => return [46, 70, 94].map(|h| now.to_utc() - Duration::hours(h)),
    };
    let mut times = std::iter::successors(Some(now.date_naive()), |d| d.pred_opt())
        .filter(|d| {
            if flow.as_u128() == 13 {
                d.weekday() == Weekday::Fri
            } else {
                d.weekday().num_days_from_monday() < 5
            }
        })
        .filter_map(|d| {
            Local
                .from_local_datetime(&d.and_hms_opt(hour, minute, 0)?)
                .earliest()
        })
        .filter(|at| *at <= now)
        .map(|at| at.with_timezone(&Utc));
    std::array::from_fn(|_| times.next().unwrap())
}

fn registration(origin: &str) -> meep_wire::ConnectionGrant {
    meep_wire::ConnectionGrant {
        account: Some("Design".into()),
        kind: "posthog".into(),
        label: "PostHog".into(),
        grants: vec![],
        secrets: [
            ("access_token", "test-session"),
            ("client_id", "test-client"),
            ("refresh_token", "test-refresh"),
            ("region", origin),
            ("project_id", "7"),
            ("poll_interval_seconds", "1"),
        ]
        .into_iter()
        .map(|(k, v)| (k.to_owned(), v.to_owned()))
        .collect(),
    }
}

/// The fixture's only task run with artifacts.
const ARTIFACT_RUN: Uuid = Uuid::from_u128(0xa27);

#[derive(Default)]
struct Upstream {
    store: std::sync::Mutex<store::Fixture>,
    active: AtomicBool,
    deleted_flows: std::sync::Mutex<Vec<Uuid>>,
    refuse_delete: AtomicBool,
    preview_catalog: AtomicBool,
    reads: AtomicUsize,
    prompts: std::sync::Mutex<Vec<String>>,
    view_runs: std::sync::Mutex<Vec<(Uuid, Value)>>,
    /// Every run start body, in arrival order.
    runs: std::sync::Mutex<Vec<Value>>,
    finish_views: AtomicBool,
    hold_task_runs: AtomicBool,
}

fn posthog(state: Arc<Upstream>, origin: String) -> Router {
    async fn tasks() -> Json<Value> {
        Json(json!({"results":[]}))
    }
    async fn create_task(
        State(state): State<Arc<Upstream>>,
        Json(body): Json<Value>,
    ) -> Json<Value> {
        let prompt = body["description"].as_str().expect("task description");
        // Every Meep task carries the Meep skill after its attribution line. Record topic
        // runs as the attribution line followed by their JSON run context.
        let (marker, rest) = prompt.split_once('\n').expect("attribution line");
        assert!(
            rest.starts_with(meep_engine::MEEP_SKILL.trim_end()),
            "task without the Meep skill"
        );
        let prompt = match rest.split_once(&format!("\n{}\n", meep_engine::RUN_CONTEXT_HEADING)) {
            Some((_, context)) => format!("{marker}\n{context}"),
            None => prompt.to_owned(),
        };
        state.prompts.lock().expect("recorded prompts").push(prompt);
        Json(json!({"id":Uuid::new_v4()}))
    }
    async fn run(State(state): State<Arc<Upstream>>, Json(body): Json<Value>) -> Json<Value> {
        let id = Uuid::new_v4();
        state.runs.lock().unwrap().push(body.clone());
        // Topic runs import the meep-topic MCP. Only authoring runs import meep-view.
        if body["imported_mcp_servers"][0]["name"] == "meep-view" {
            state.view_runs.lock().unwrap().push((id, body));
        }
        Json(json!({"run":{"id":id,"status":"queued"}}))
    }
    async fn task_status(
        State(state): State<Arc<Upstream>>,
        axum::extract::Path((_, run)): axum::extract::Path<(Uuid, Uuid)>,
    ) -> Json<Value> {
        let working = state.hold_task_runs.load(Ordering::SeqCst)
            || state
                .view_runs
                .lock()
                .unwrap()
                .iter()
                .any(|(id, _)| *id == run)
                && !state.finish_views.load(Ordering::SeqCst);
        Json(json!({"id":run,"status":if working{"in_progress"}else{"completed"}}))
    }
    async fn logs(
        State(state): State<Arc<Upstream>>,
        axum::extract::Path((_, run)): axum::extract::Path<(Uuid, Uuid)>,
    ) -> Json<Value> {
        if state
            .view_runs
            .lock()
            .unwrap()
            .iter()
            .any(|(id, _)| *id == run)
        {
            let entry = |update: Value| json!({"notification":{"method":"session/update","params":{"update":update}}});
            return Json(json!([
                entry(
                    json!({"sessionUpdate":"agent_message","content":{"type":"text","text":"I found the navigation team’s rollout tasks. I’m grouping them by status so the review queue is easy to find."}})
                ),
                entry(
                    json!({"sessionUpdate":"tool_call","toolCallId":"read","title":"Read topic tasks","status":"completed"})
                ),
                entry(
                    json!({"sessionUpdate":"tool_call","toolCallId":"write","title":"Update launch tracker","status":if state.finish_views.load(Ordering::SeqCst){"completed"}else{"in_progress"}})
                )
            ]));
        }
        Json(
            json!([{"notification":{"method":"session/update","params":{"update":{"sessionUpdate":"agent_message","content":{"type":"text","text":"The navigation review is ready."}}}}}]),
        )
    }
    async fn services(State(state): State<Arc<Upstream>>) -> Json<Value> {
        let mut services = vec![
            json!({"installation_id": INSTALLATION, "name":"Design chat","slug":"chat",
            "tools":[{"name":"list_recent","description":"Recent observations","input_schema":{},"annotations":{"readOnlyHint":true},"approval_state":"approved"}]}),
        ];
        if state.preview_catalog.load(Ordering::SeqCst) {
            services[0]["name"] = json!("Slack");
            let mut github = services[0].clone();
            github["installation_id"] = json!(GITHUB_INSTALLATION);
            github["name"] = json!("GitHub");
            github["slug"] = json!("github");
            services.push(github);
        }
        Json(json!({"servers":services}))
    }
    async fn call(State(state): State<Arc<Upstream>>, Json(body): Json<Value>) -> Json<Value> {
        assert_eq!(body["tool_name"], "list_recent");
        let observation = if state.active.load(Ordering::SeqCst) {
            "First observation"
        } else {
            "New observation"
        };
        state.reads.fetch_add(1, Ordering::SeqCst);
        Json(json!({"content":[],"structuredContent":{"data": [observation]}}))
    }
    async fn flow(
        State(state): State<Arc<Upstream>>,
        axum::extract::Path(flow): axum::extract::Path<Uuid>,
    ) -> Json<Value> {
        let status = if state.active.load(Ordering::SeqCst) {
            "active"
        } else {
            "draft"
        };
        let step = |id: &str, kind: &str, name: &str, config: Value| json!({"id": id, "type": kind, "name": name, "config": config});
        let next = |from: &str, to: &str| json!({"from": from, "to": to, "type": "continue"});
        let branch = |from: &str, to: &str, index: u64| json!({"from": from, "to": to, "type": "branch", "index": index});
        let callback = json!({"template_id": "template-webhook"});
        let body = match flow.as_u128() {
            11 => json!({
                "status": status, "name": "Pilot pulse",
                "actions": [
                    step("t", "trigger", "Weekday morning", json!({"type": "schedule"})),
                    step("a", "function", "Read saved page opens", callback.clone()),
                    step("b", "function", "Compare pilot and baseline", callback.clone()),
                    // Four paths, one condition left unnamed, one path two steps long.
                    step("c", "conditional_branch", "Did opens change?", json!({"conditions": [{"name": "Opens fell more than 5%"}, {"name": "Opens rose more than 5%"}, {}]})),
                    step("d", "function", "Post to #web-nav", json!({"template_id": "template-slack"})),
                    step("d2", "function", "Open a task to investigate", callback.clone()),
                    step("f", "function", "Note the rise", callback.clone()),
                    step("g", "random_cohort_branch", "Sample the follow-up", json!({"cohorts": [{"percentage": 50}, {"percentage": 50}]})),
                    step("g1", "function", "Skip this reading", callback.clone()),
                    step("g2", "function", "Note it for Friday", callback.clone()),
                    step("e", "function", "Write pilot-cohorts.csv", callback.clone()),
                    step("x", "exit", "Exit", json!({})),
                ],
                "edges": [next("t","a"), next("a","b"), next("b","c"), branch("c","d",0), next("d","d2"), branch("c","f",1), branch("c","g",2), branch("g","g1",0), branch("g","g2",1), next("c","e"), next("d2","x"), next("f","x"), next("g1","x"), next("g2","x"), next("e","x")],
            }),
            12 => json!({
                "status": status, "name": "Rollout check",
                "actions": [
                    step("t", "trigger", "Flag changed", json!({"type": "event", "filters": {"events": [{"name": "web-nav-v2 changed"}]}})),
                    step("w", "delay", "Let exposure settle", json!({"delay_duration": "1h"})),
                    step("a", "function", "Read flag exposure", callback.clone()),
                    step("b", "function", "Check the rollout guardrail", callback.clone()),
                ],
                "edges": [next("t","w"), next("w","a"), next("a","b")],
            }),
            13 => json!({
                "status": "draft", "name": "Friday handoff",
                "actions": [
                    step("t", "trigger", "Friday afternoon", json!({"type": "schedule"})),
                    step("a", "function", "Collect the week’s decisions", callback.clone()),
                    step("b", "function", "Write the review notes", callback),
                ],
                "edges": [next("t","a"), next("a","b")],
            }),
            14 => {
                json!({"status":status,"actions":[step("t","trigger","Trigger",json!({"type":"manual"})),step("a","function","Sort source",callback)],"edges":[next("t","a")]})
            }
            _ => json!({"status": status, "actions": [{"name": "Review flagged observations"}]}),
        };
        Json(body)
    }
    async fn flow_metrics(
        axum::extract::Path(flow): axum::extract::Path<Uuid>,
        axum::extract::Query(q): axum::extract::Query<std::collections::BTreeMap<String, String>>,
    ) -> Json<Value> {
        // Seven days of outcomes for one step, steady with the odd failure.
        let step = q.get("instance_id").cloned().unwrap_or_default();
        let base = (flow.as_u128() as u64 % 5) + 3 + step.len() as u64;
        let fail = u64::from(matches!(step.as_str(), "a" | "g1") && flow.as_u128() == 11);
        Json(json!({"labels": [], "series": [
            {"name": "success", "values": [base, base, base + 1, base, base - 1, base, base]},
            {"name": "failure", "values": [0, 0, fail, 0, 0, 0, 0]},
        ]}))
    }
    async fn flow_totals(axum::extract::Path(flow): axum::extract::Path<Uuid>) -> Json<Value> {
        let n = flow.as_u128() as u64 % 5 + 5;
        Json(json!({"totals": {"success": n * 7, "failure": u64::from(flow.as_u128() == 11)}}))
    }
    async fn toggle(State(state): State<Arc<Upstream>>, Json(body): Json<Value>) -> Json<Value> {
        state
            .active
            .store(body["status"] == "active", Ordering::SeqCst);
        Json(json!({"status": body["status"]}))
    }
    async fn system_one(Json(body): Json<Value>) -> Response {
        match body["state"]["event"]["attributes"]["gateway"].as_str() {
            Some("unavailable") => return StatusCode::SERVICE_UNAVAILABLE.into_response(),
            Some("sorting") => return std::future::pending().await,
            _ => {}
        }
        assert_eq!(body["model"], "posthog/hogference/jevk5-fp8-0.2");
        let mut answers = serde_json::Map::new();
        for (id, q) in body["questions"].as_object().expect("questions") {
            let answer = match id.as_str() {
                k if k.starts_with("memory:") => {
                    let verdict = if k != "memory:empty"
                        && body["state"]["changed"]["fact"]["text"]
                            == "Only two navigation components remain."
                    {
                        "review"
                    } else {
                        "independent"
                    };
                    json!({"type":"choice","choice":verdict,"confidence":1.0})
                }
                "intent" => {
                    json!({"type":"choice","choice":"question","probabilities":{"question":1.0}})
                }
                "disposition" => {
                    assert!(body["state"]["mission"].is_string());
                    assert!(body["state"]["rules"].is_array());
                    let k = if body["state"]["event"]["attributes"]["gateway"]
                        == "held-investigation"
                    {
                        "investigate"
                    } else if body["state"]["event"]["attributes"]["needs_decision"] == true {
                        "ask"
                    } else {
                        "handle"
                    };
                    json!({"type":"choice","choice":k,"probabilities":{k:1.0}})
                }
                "speaks_for_person" => {
                    json!({"type":"noul","noul": if body["state"]["event"]["attributes"]["gateway"] == "held-investigation" {1.0} else {0.0}})
                }
                "poll_tool" => json!({"type":"choice","choice":"0","probabilities":{"0":1.0}}),
                _ if q["type"] == "score" => {
                    json!({"type":"score","score": if id=="1"{2.0}else{0.0}})
                }
                _ => panic!("unexpected question {id}"),
            };
            answers.insert(id.clone(), answer);
        }
        Json(json!({"model":body["model"],"answers":answers,"usage":{}})).into_response()
    }
    let storage = origin.clone();
    Router::new()
        .merge(store::routes())
        .route("/v1/systemone",post(system_one))
        .route("/.well-known/oauth-authorization-server", get(move || {let origin=origin.clone(); async move {
            Json(json!({"issuer":origin,"authorization_endpoint":format!("{origin}/authorize"), "registration_endpoint":format!("{origin}/register"), "token_endpoint":format!("{origin}/token")}))
        }}))
        .route("/register",post(|Json(request):Json<Value>|async move {
            assert_eq!(request["token_endpoint_auth_method"],"none");
            assert!(!request["scope"].as_str().expect("scopes").split_whitespace().any(|s|s=="llm_gateway:read"));
            Json(json!({"client_id":"native-client","scope":request["scope"]}))
        }))
        .route("/token",post(|body:String|async move {
            assert!(body.contains("code_verifier=") && (body.contains("client_id=native-client") || body.contains("client_id=fixture-provisioned")));
            Json(json!({"access_token":"signed-in-access","refresh_token":"signed-in-refresh","token_type":"bearer"}))
        }))
        .route("/api/users/@me/",get(|headers:axum::http::HeaderMap|async move {
            assert_eq!(headers["authorization"],"Bearer signed-in-access");
            Json(json!({"email":"design@example.test","uuid":"afa73ea4-07c2-4677-99d3-80d8cb46004f"}))
        }))
        .route("/api/projects/@current/",get(|headers:axum::http::HeaderMap|async move {
            assert_eq!(headers["authorization"],"Bearer signed-in-access");
            Json(json!({"id":7,"name":"Navigation team"}))
        }))
        .route("/api/projects/7/tasks/", get(tasks).post(create_task))
        .route("/api/projects/7/tasks/@me/config/", get(|| async {
            Json(json!({"resolved_ai_run_defaults":{"runtime":"acp","runtime_adapter":"claude","model":"claude-test","reasoning_effort":null}}))
        }))
        // Runs carrying a Meep MCP ask for the account's Claude runtime model.
        .route(
            "/api/projects/7/tasks/models/",
            get(|| async {
                Json(json!({"models":[
                    {"model":"claude-test","display_name":"Claude","runtime_adapter":"claude"},
                    {"model":"claude-deep","display_name":"Claude Deep","runtime_adapter":"claude"},
                    {"model":"claude-haiku-4-5","display_name":"Claude Haiku 4.5","runtime_adapter":"claude"},
                    {"model":"codex-test","display_name":"Codex","runtime_adapter":"codex"}
                ]}))
            }),
        )
        .route("/api/projects/7/tasks/{id}/run/", post(run))
        // What a task's runs produced: one run file beside an input, one living document.
        .route(
            "/api/projects/7/tasks/{id}/runs/",
            get(|| async {
                Json(json!({"next":null,"results":[{"id":ARTIFACT_RUN,"artifacts":[
                    {"id":"out-1","name":"cohorts.csv","type":"output","size":24,"content_type":"text/csv"},
                    {"id":"att-1","name":"brief.pdf","type":"user_attachment","size":9}
                ]}]}))
            }),
        )
        .route(
            "/api/projects/7/tasks/{id}/runs/{run}/living_artifacts/",
            get(|| async {
                Json(json!({"artifacts":[{
                    "id":"doc-1","task_id":"","run_id":ARTIFACT_RUN.to_string(),"team_id":7,
                    "name":"Findings.md","artifact_type":"document","adapter":"document_connector",
                    "status":"active","location":{},"metadata":{},"current_version":2,
                    "versions":[{"version":1},{"version":2,"size":32,"content_type":"text/markdown"}]
                }]}))
            }),
        )
        .route(
            "/api/projects/7/tasks/{id}/runs/{run}/living_artifacts/doc-1/versions/{version}/",
            get(|axum::extract::Path((_, _, version)): axum::extract::Path<(Uuid, Uuid, u64)>| async move {
                format!("# Findings v{version}\nOld nav: 5 components.")
            }),
        )
        .route(
            "/api/projects/7/tasks/{id}/runs/{run}/artifacts/out-1/download/",
            get(move || async move {
                axum::response::Redirect::to(&format!("{storage}/storage/out-1")).into_response()
            }),
        )
        .route("/storage/out-1", get(|| async { "cohort,users\nnew-nav,128\n" }))
        .route("/api/projects/7/tasks/{id}/runs/{run}/", get(task_status))
        .route(
            "/api/projects/7/tasks/{id}/runs/{run}/session_logs/",
            get(logs),
        )
        .route(
            "/api/projects/7/mcp_server_installations/available_tools/",
            get(services),
        )
        .route(
            "/api/projects/7/mcp_server_installations/{id}/call_tool/",
            post(call),
        )
        .route("/api/projects/7/hog_flows/{flow}/", get(flow).patch(toggle).delete(|State(state): State<Arc<Upstream>>, axum::extract::Path(flow): axum::extract::Path<Uuid>| async move {
                if state.refuse_delete.load(Ordering::SeqCst) { return StatusCode::SERVICE_UNAVAILABLE; }
                state.deleted_flows.lock().unwrap().push(flow);
                StatusCode::NO_CONTENT
            }))
        .route("/api/projects/7/hog_flows/{flow}/metrics/", get(flow_metrics))
        .route("/api/projects/7/hog_flows/{flow}/metrics/totals/", get(flow_totals))
        .route(
            "/api/projects/7/hog_flows/{flow}/invocation_results/",
            get(|axum::extract::Path(flow): axum::extract::Path<Uuid>| async move {
                let [latest, previous, oldest] = routine_run_times(flow);
                Json(json!([
                    {"invocation_id": Uuid::from_u128(701), "status":"success", "duration_ms":4200, "started_at":latest},
                    {"invocation_id": Uuid::from_u128(702), "status":"success", "duration_ms":3700, "started_at":previous},
                    {"invocation_id": Uuid::from_u128(703), "status":"failed", "duration_ms":5400, "scheduled_at":oldest, "error_message":"The source connection timed out."}
                ]))
            }),
        )
        .route("/api/projects/7/hog_flows/{flow}/logs/", get(|
            axum::extract::Path(flow): axum::extract::Path<Uuid>,
            axum::extract::Query(query): axum::extract::Query<BTreeMap<String, String>>| async move {
            assert_eq!(query["level"], "LOG");
            assert_eq!(query["limit"], "1");
            let run = Uuid::parse_str(&query["instance_id"]).unwrap();
            let output = match (run.as_u128(), flow.as_u128()) {
                (701, 11) => "Wrote pilot-cohorts.csv",
                (701, 12) => "Recorded the rollout guardrail",
                (701, 13) => "Wrote notes/review.md",
                (701, _) => "Filed the review",
                (702, _) => "Sent 1 message",
                _ => return Json(json!({"results":[]})),
            };
            Json(json!({"results":[{"instance_id":run,"message":output}]}))
        }))
        .route(
            "/api/projects/7/hog_flows/{flow}/run/",
            post(|| async { Json(json!({"invocation_id":Uuid::new_v4(),"status":"running"})) }),
        )
        .route("/mcp", post(mcp))
        .with_state(state)
}

async fn mcp(State(state): State<Arc<Upstream>>, Json(body): Json<Value>) -> Response {
    let result = match body["method"].as_str() {
        Some("initialize") => {
            json!({"protocolVersion":"2025-11-25","capabilities":{"tools":{}},"serverInfo":{"name":"test","version":"1"}})
        }
        Some("notifications/initialized") => return StatusCode::ACCEPTED.into_response(),
        Some("tools/list") => {
            json!({"tools":[{"name":"insights-list","inputSchema":{"type":"object","properties":{}}},{"name":"feature-flag-get-all","inputSchema":{"type":"object","properties":{}}}]})
        }
        Some("tools/call") => {
            let rows = match body["params"]["name"].as_str() {
                Some("insights-list") if state.preview_catalog.load(Ordering::SeqCst) => {
                    json!([{"id":31,"name":"Saved page opens"},{"id":78,"name":"First-session retention"}])
                }
                Some("feature-flag-get-all") if state.preview_catalog.load(Ordering::SeqCst) => {
                    json!([{"key":"rail","name":"web-nav-v2"}])
                }
                Some("insights-list") => json!([{"id":31,"name":"Navigation usage"}]),
                Some("feature-flag-get-all") => json!([{"id":7,"key":"rail","name":"New rail"}]),
                _ => return StatusCode::BAD_REQUEST.into_response(),
            };
            json!({"content":[],"structuredContent":{"results":rows}})
        }
        _ => return StatusCode::BAD_REQUEST.into_response(),
    };
    Json(json!({"jsonrpc":"2.0","id":body["id"],"result":result})).into_response()
}

fn draw(ui: &mut VisualTestContext) {
    ui.run_until_parked();
    ui.update(|w, cx| {
        w.refresh();
        w.draw(cx).clear(cx);
    });
}
#[track_caller]
fn center(ui: &mut VisualTestContext, id: &str) -> Point<Pixels> {
    draw(ui);
    let key = format!("{:?}]", ElementId::from(SharedString::from(id.to_owned())));
    // Unnamed children share their parent's id; the control is the outermost
    // element of the last group that carries it.
    let found: Vec<_> = ui.update(|w, _| {
        w.visual_elements()
            .iter()
            .filter(|e| e.element_id.ends_with(&key))
            .map(|e| e.bounds)
            .collect()
    });
    let Some(mut best) = found.last().copied() else {
        panic!("missing control {id}");
    };
    for b in found.iter().rev().skip(1) {
        if b.contains(&best.origin) && b.contains(&(best.bottom_right() - point(px(0.5), px(0.5))))
        {
            best = *b;
        }
    }
    best.center()
}
/// Open an Overview section in place, then go to all of it.
#[track_caller]
fn open_section(ui: &mut VisualTestContext, tab: &str) {
    let all: &'static str = Box::leak(format!("overview-all-{tab}").into_boxed_str());
    if ui.debug_bounds(all).is_none() {
        click(ui, &format!("overview-{tab}"));
    }
    click(ui, all);
}

#[track_caller]
fn click(ui: &mut VisualTestContext, id: &str) {
    let point = center(ui, id);
    ui.simulate_mouse_move(point, None, Modifiers::default());
    draw(ui);
    ui.simulate_click(point, Modifiers::default());
    draw(ui)
}
fn drag(ui: &mut VisualTestContext, source: &str, target: &str) {
    let from = center(ui, source);
    let to = center(ui, target);
    let modifiers = Modifiers::default();
    ui.simulate_mouse_move(from, None, modifiers);
    ui.simulate_mouse_down(from, MouseButton::Left, modifiers);
    ui.simulate_mouse_move(from + point(px(7.), px(2.)), MouseButton::Left, modifiers);
    draw(ui);
    ui.simulate_mouse_move(to, MouseButton::Left, modifiers);
    draw(ui);
    ui.simulate_mouse_up(to, MouseButton::Left, modifiers);
    draw(ui);
}
fn fixture<'a>(
    lab: &Lab,
    cx: &'a mut TestAppContext,
) -> (Entity<Desktop>, &'a mut VisualTestContext) {
    cx.background_executor.allow_parking();
    cx.update(gpui_kit::init);
    // Tests never advance time: transitions settle at once, as with reduced motion.
    cx.update(|cx| cx.set_reduce_motion(true));
    let mut view = None;
    let (_, ui) = cx.add_window_view(|w, cx| {
        w.set_visual_inspection_enabled(true);
        let v = cx.new(|cx| Desktop::new(lab.backend.clone(), lab.runtime.clone(), None, w, cx));
        view = Some(v.clone());
        gpui_kit::base::Root::new(v, w, cx)
    });
    (view.expect("created desktop"), ui)
}

#[gpui::test]
fn create_choose_watches_search_and_restore_local_layout(cx: &mut TestAppContext) {
    let lab = Lab::open().unwrap();
    let (v, ui) = fixture(&lab, cx);
    click(ui, "welcome-field");
    // The goal is focused first; the name follows it in the same card.
    ui.simulate_input("Keep the release calendar honest");
    ui.update(|w, cx| {
        v.update(cx, |s, cx| {
            s.name
                .update(cx, |e, cx| e.set_value("Release watch", w, cx))
        })
    });
    click(ui, "submit-sheet");
    let id = ui.update(|_, cx| v.read(cx).topic_id().unwrap());
    ui.update(|_, cx| {
        let desktop = v.read(cx);
        // A new topic opens on its conversation, ready to write in.
        assert!(desktop.on_chat());
        assert!(desktop.composer.read(cx).value().is_empty());
    });
    click(ui, "plus");
    click(ui, "new-section");
    ui.simulate_input("Product");
    ui.simulate_keystrokes("enter");
    assert!(
        lab.backend
            .client
            .preference::<Layout>("sidebar")
            .unwrap()
            .unwrap()
            .sections
            .iter()
            .any(|s| s.name == "Product")
    );
    ui.simulate_keystrokes("cmd-k");
    ui.simulate_input("release");
    ui.simulate_keystrokes("down enter");
    ui.update(|_, cx| assert_eq!(v.read(cx).page, Page::Topic(id, Tab::Chat, None)));
    lab.runtime
        .block_on(lab.backend.client.sync_once())
        .unwrap();
    assert_eq!(
        lab.server.engine().topic(id).unwrap().topic.name,
        "Release watch"
    );
    assert_eq!(
        lab.backend.client.connections().unwrap().connections[0].grants,
        vec![id]
    );
}

#[gpui::test]
fn decision_creates_editable_draft_and_approval_learns_only_on_request(cx: &mut TestAppContext) {
    let mut lab = Lab::open().unwrap();
    let id = lab.seed().unwrap();
    // Inspect the local approval and standing-rule offer before delivery is attempted.
    lab.disconnect().unwrap();
    let (v, ui) = fixture(&lab, cx);
    assert!(
        labels(ui)
            .iter()
            .any(|line| line == "Choose which rail item the team can move into More.")
    );
    click(ui, &format!("attention-row-{id}-0"));
    ui.simulate_keystrokes("cmd-[");
    ui.update(|_, cx| assert_eq!(v.read(cx).page, Page::Needs));
    click(ui, &format!("attention-row-{id}-0"));
    click(ui, "answer-0");
    // The task opens as its own page in the topic.
    click(ui, "outcome-0");
    ui.update(|_, cx| {
        let d = v.read(cx);
        assert!(matches!(
            d.page,
            Page::Topic(_, Tab::Tasks, Some(Detail::Task(_)))
        ));
        assert!(d.chat_task().is_some());
    });
    let approved_at = center(ui, "approve");
    click(ui, "send-back");
    center(ui, "submit-note");
    click(ui, "cancel-note");
    assert_eq!(center(ui, "approve"), approved_at);
    ui.update(|w, cx| {
        v.read(cx)
            .draft
            .clone()
            .update(cx, |d, cx| d.set_value("Which item can we replace?", w, cx));
    });
    click(ui, "approve");
    let state = lab.backend.client.topic(id).unwrap().unwrap();
    assert_eq!(state.tasks[0].column, Column::Done);
    assert_eq!(
        state.tasks[0].draft.as_deref(),
        Some("Which item can we replace?")
    );
    assert!(state.topic.rules.is_empty());
    click(ui, "always-do-it");
    assert!(matches!(
        lab.backend.client.topic(id).unwrap().unwrap().topic.rules[0].effect,
        RuleEffect::Allow(_)
    ));
}

#[gpui::test]
fn sidebar_sections_group_rename_drag_and_ungroup_like_view(cx: &mut TestAppContext) {
    use super::sidebar::topic_key;
    let lab = Lab::open().unwrap();
    let id = lab.seed().unwrap();
    let (_view, ui) = fixture(&lab, cx);
    let layout = || {
        lab.backend
            .client
            .preference::<Layout>("sidebar")
            .unwrap()
            .unwrap()
    };
    // No forced default section: the topic starts loose.
    assert!(ui.update(|_, cx| _view.read(cx).layout.sections.is_empty()));
    // "New section…" from the topic's menu holds it and names it in place.
    click(ui, &format!("topic-actions-{id}"));
    click_label(ui, "New section…");
    ui.simulate_input("Launch");
    ui.simulate_keystrokes("enter");
    let saved = layout();
    assert_eq!(saved.sections[0].name, "Launch");
    assert_eq!(saved.sections[0].items, [topic_key(id)]);
    let section = saved.sections[0].id;
    // Rename from the section's menu, inline.
    click(ui, &format!("section-actions-{section}"));
    click_label(ui, "Rename section…");
    ui.simulate_input("Launches");
    ui.simulate_keystrokes("enter");
    assert_eq!(layout().sections[0].name, "Launches");
    // Take it out from the menu, then drag it back onto the header.
    click(ui, &format!("topic-actions-{id}"));
    click_label(ui, "Section");
    click_label(ui, "Take out of Launches");
    assert!(layout().sections[0].items.is_empty());
    assert_eq!(layout().loose, [topic_key(id)]);
    drag(
        ui,
        &format!("topic-{id}"),
        &format!("section-toggle-{section}"),
    );
    assert_eq!(layout().sections[0].items, [topic_key(id)]);
    // Removing a section ungroups it: the topic stays, loose.
    click(ui, &format!("section-actions-{section}"));
    click_label(ui, "Remove section");
    let saved = layout();
    assert!(saved.sections.is_empty());
    assert_eq!(saved.loose, [topic_key(id)]);
    center(ui, &format!("topic-{id}"));
}

#[gpui::test]
fn running_a_bound_workflow_updates_its_detail_through_the_server(cx: &mut TestAppContext) {
    let lab = Lab::open().unwrap();
    let id = lab.seed().unwrap();
    let (view, ui) = fixture(&lab, cx);
    ui.update(|w, cx| {
        view.update(cx, |s, cx| {
            s.go(Page::Topic(id, Tab::Routines, None), w, cx)
        })
    });
    assert!(!labels(ui).iter().any(|label| label == "Run now"));
    click(ui, "routine-review");
    click(ui, "enable-routine");
    assert!(
        !lab.backend
            .client
            .cached_workflow(id, "review")
            .unwrap()
            .unwrap()
            .enabled
    );
    lab.runtime
        .block_on(lab.backend.client.sync_once())
        .unwrap();
    draw(ui);
    assert_eq!(
        ui.update(|_, cx| view.read(cx).page.clone()),
        Page::Topic(id, Tab::Routines, Some(Detail::Routine("review".into())))
    );
    click(ui, "enable-routine");
    lab.runtime
        .block_on(async {
            let client = &lab.backend.client;
            client.sync_once().await?;
            let engine = lab.server.engine();
            let state = engine.topic(id)?;
            if let Some(request) = state.tasks.iter().find(|task| {
                task.column == Column::NeedsYou
                    && task.action.as_ref().is_some_and(|action| {
                        action.kind.0 == "routine-activate" && action.payload["routine"] == "review"
                    })
            }) {
                engine.approve(id, request.id, None, false).await?;
            }
            tokio::time::timeout(std::time::Duration::from_secs(4), async {
                while !lab.upstream.active.load(Ordering::SeqCst) {
                    tokio::time::sleep(std::time::Duration::from_millis(10)).await;
                }
            })
            .await
            .with_context(|| {
                format!(
                    "Activation never reached the provider: {:?}",
                    engine
                        .topic(id)
                        .unwrap()
                        .tasks
                        .iter()
                        .map(|t| (&t.title, &t.result))
                        .collect::<Vec<_>>()
                )
            })?;
            client.refresh_workflow(id, "review").await?;
            client.sync_once().await
        })
        .unwrap();
    draw(ui);

    assert!(
        lab.backend
            .client
            .cached_workflow(id, "review")
            .unwrap()
            .unwrap()
            .enabled
    );
    click(ui, "crumb-section");
    click(ui, "routine-review");
    click(ui, "run-now");
    lab.runtime
        .block_on(lab.backend.client.sync_once())
        .unwrap();
    let state = lab.server.engine().topic(id).unwrap();
    assert!(state.topic.routines[0].last_run.is_some());
    click(ui, "enable-routine");
    lab.runtime
        .block_on(lab.backend.client.sync_once())
        .unwrap();
    assert!(!lab.upstream.active.load(Ordering::SeqCst));
    let flow: Uuid = state.topic.routines[0].binding.external_id.parse().unwrap();
    lab.runtime.block_on(async {
        let engine = lab.server.engine();
        let client = &lab.backend.client;
        let mut alias = state.topic.routines[0].binding.clone();
        alias.id = "second-binding".into();
        engine.bind_routine(id, alias).await.unwrap();
        client
            .delete_workflow(id, "second-binding", flow)
            .await
            .unwrap();
        assert!(lab.upstream.deleted_flows.lock().unwrap().is_empty());
        assert!(
            client
                .delete_workflow(id, "review", Uuid::new_v4())
                .await
                .is_err()
        );
        lab.upstream.refuse_delete.store(true, Ordering::SeqCst);
        assert!(client.delete_workflow(id, "review", flow).await.is_err());
        assert!(engine.routine_secret(id, "review").is_ok());
        lab.upstream.refuse_delete.store(false, Ordering::SeqCst);
    });
    click(ui, "delete-routine");
    click(ui, "cancel-sheet");
    assert!(lab.upstream.deleted_flows.lock().unwrap().is_empty());
    click(ui, "delete-routine");
    click(ui, "confirm-delete-routine");
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
    while ui.update(|_, cx| view.read(cx).page != Page::Topic(id, Tab::Routines, None)) {
        assert!(
            std::time::Instant::now() < deadline,
            "Routine deletion did not finish"
        );
        std::thread::sleep(std::time::Duration::from_millis(10));
        draw(ui);
    }
    assert_eq!(*lab.upstream.deleted_flows.lock().unwrap(), [flow]);
    assert!(
        lab.backend
            .client
            .cached_workflow(id, "review")
            .unwrap()
            .is_none()
    );
    assert!(lab.server.engine().routine_secret(id, "review").is_err());
    assert!(labels(ui).iter().any(|s| s == "No routines yet."));
}

#[gpui::test]
fn resolving_from_the_inbox_row_moves_the_report_behind_the_closed_line(cx: &mut TestAppContext) {
    let lab = Lab::open().unwrap();
    let id = lab.seed().unwrap();
    let report = lab.publish_sample_reports(id).unwrap()[0];
    let (_, ui) = fixture(&lab, cx);
    click(ui, &format!("topic-{id}"));
    open_section(ui, "Inbox");
    let row = center(ui, &format!("thread-{report}"));
    ui.simulate_mouse_move(row, None, Modifiers::default());
    draw(ui);
    click(ui, &format!("quick-resolve-{report}"));
    let state = lab.backend.client.topic(id).unwrap().unwrap();
    let thread = state.threads.iter().find(|t| t.id == report).unwrap();
    let verdict = thread
        .report_sources
        .as_ref()
        .unwrap()
        .verdict
        .as_ref()
        .unwrap();
    assert_eq!(verdict.outcome, meep_topic::ReportOutcome::Resolved);
    // Still in the inbox, not opened by the click.
    center(ui, "show-closed-reports");
}

#[gpui::test]
fn investigating_a_report_is_a_queued_turn_in_the_conversation(cx: &mut TestAppContext) {
    let lab = Lab::open().unwrap();
    let id = lab.seed().unwrap();
    let report = lab.publish_sample_reports(id).unwrap()[0];
    let before = lab.backend.client.topic(id).unwrap().unwrap().tasks.len();
    let (view, ui) = fixture(&lab, cx);
    click(ui, &format!("topic-{id}"));
    open_section(ui, "Inbox");
    click(ui, &format!("thread-{report}"));
    click(ui, "report-investigate");
    let state = lab.backend.client.topic(id).unwrap().unwrap();
    // No separate agent: the ask goes to the topic's agent, with the report attached.
    assert!(
        state.tasks.iter().all(|t| t.from_thread != Some(report)),
        "no task linked to the report"
    );
    assert!(
        state.tasks.len() <= before + 1,
        "at most the conversation itself"
    );
    let ask = state
        .threads
        .iter()
        .filter(|t| t.is_topic_chat())
        .flat_map(|t| &t.messages)
        .find(|m| m.text.starts_with("Investigate the report"))
        .expect("the ask is in the chat");
    assert!(ask.text.contains("find its root"));
    assert!(
        ask.text.contains(&format!("Report {report}")),
        "names the report"
    );
    ui.update(|_, cx| assert_eq!(view.read(cx).page, Page::Topic(id, Tab::Chat, None)));
}

#[gpui::test]
fn files_browse_what_a_topics_task_runs_produced_and_cache_what_was_opened(
    cx: &mut TestAppContext,
) {
    let lab = Lab::open().unwrap();
    let id = lab.seed().unwrap();
    let report = lab.publish_sample_reports(id).unwrap()[0];
    let (view, ui) = fixture(&lab, cx);
    click(ui, &format!("topic-{id}"));
    let started = TaskId(Uuid::new_v4());
    lab.backend
        .client
        .issue(
            id,
            Command::AddConfiguredTask {
                start: true,
                id: started,
                title: "Investigate: navigation".into(),
                untitled: false,
                model: None,
                reasoning_effort: None,
                instructions: Some(format!("Look into report {report}")),
                billing: None,
            },
        )
        .unwrap();
    let engine = lab.server.engine();
    lab.runtime
        .block_on(async {
            tokio::time::timeout(std::time::Duration::from_secs(5), async {
                while !engine
                    .task_runs(id)
                    .unwrap()
                    .iter()
                    .any(|(t, _)| *t == started)
                {
                    tokio::time::sleep(std::time::Duration::from_millis(10)).await;
                }
            })
            .await
        })
        .expect("the investigation never started");
    let task = engine
        .topic(id)
        .unwrap()
        .tasks
        .into_iter()
        .find(|t| t.id == started)
        .unwrap();
    let wait = |ui: &mut VisualTestContext, done: &dyn Fn(&Desktop) -> bool| {
        for _ in 0..500 {
            ui.run_until_parked();
            if ui.update(|_, cx| done(view.read(cx))) {
                return draw(ui);
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        panic!("Files never settled");
    };
    ui.update(|w, cx| view.update(cx, |s, cx| s.go(Page::Topic(id, Tab::Files, None), w, cx)));
    wait(ui, &|s| matches!(s.artifacts.get(&id), Some(Ok(_))));
    // Task output sits in a folder named after its task; inputs stay out.
    let folder = format!("tasks/{}", task.title);
    let order = ui.update(|_, cx| {
        let s = view.read(cx);
        s.file_order(s.states.iter().find(|t| t.topic.id == id).unwrap())
    });
    let findings = format!("{folder}/Findings.md");
    let cohorts = format!("{folder}/cohorts.csv");
    assert!(
        order.contains(&findings) && order.contains(&cohorts),
        "{order:?}"
    );
    assert!(!order.iter().any(|p| p.ends_with("brief.pdf")), "{order:?}");
    // A living document opens at its current version; a run file through its download.
    for (path, text) in [(&findings, "# Findings v2"), (&cohorts, "new-nav,128")] {
        ui.update(|w, cx| {
            view.update(cx, |s, cx| {
                s.go(
                    Page::Topic(id, Tab::Files, Some(Detail::File(path.clone()))),
                    w,
                    cx,
                )
            })
        });
        wait(
            ui,
            &|s| matches!(&s.artifact_open, Some((_, Ok(b))) if String::from_utf8_lossy(b).contains(text)),
        );
    }
    assert!(
        labels(ui).iter().any(|l| l == "tasks"),
        "breadcrumb names the folder"
    );
    let artifacts = ui.update(|_, cx| view.read(cx).artifacts[&id].clone().unwrap());
    let doc = artifacts.iter().find(|a| a.id == "doc-1").unwrap();
    assert_eq!(doc.version, 2);
    // Opened versions come back from the device cache without a request.
    assert!(lab.backend.client.cached_artifact(doc).unwrap().is_some());
    assert!(lab.backend.client.artifact_cache_size().unwrap() > 0);
}

#[gpui::test]
fn asking_about_a_file_carries_its_cached_revision_into_chat(cx: &mut TestAppContext) {
    let lab = Lab::open().unwrap();
    let id = lab.seed().unwrap();
    let path = "notes/review.md";
    let (view, ui) = fixture(&lab, cx);
    click(ui, &format!("topic-{id}"));
    ui.update(|w, cx| {
        view.update(cx, |s, cx| {
            s.go(
                Page::Topic(id, Tab::Files, Some(Detail::File(path.into()))),
                w,
                cx,
            )
        })
    });
    ui.update(|_, cx| {
        let s = view.read(cx);
        assert_eq!(
            s.page,
            Page::Topic(id, Tab::Files, Some(Detail::File(path.into())))
        );
        assert_eq!(s.folder.as_deref(), Some("notes"));
        assert!(s.files);
    });
    click(ui, "chat-file");
    ui.simulate_input("What does it cover?");
    ui.simulate_keystrokes("enter");
    let state = lab.backend.client.topic(id).unwrap().unwrap();
    let message = state
        .threads
        .iter()
        .flat_map(|t| &t.messages)
        .find(|m| m.text.starts_with("What does it cover?"))
        .unwrap();
    assert!(message.text.contains("notes/review.md (revision 1)"));
    assert!(message.text.contains("Navigation review notes"));
}

#[test]
fn source_catalog_files_and_workflows_are_account_data_cached_in_the_replica() -> Result<()> {
    let lab = Lab::open()?;
    let id = lab.seed()?;
    let c = &lab.backend.client;
    lab.runtime.block_on(async {
        let sources = c.sources().await?;
        assert_eq!(
            sources.iter().map(|s| s.kind.as_str()).collect::<Vec<_>>(),
            ["service", "insight", "flag"]
        );
        assert_eq!(c.cached_sources()?.as_deref(), Some(sources.as_slice()));
        assert_eq!(sources[0].supported_modes, ["pull", "push"]);
        assert_eq!(sources[1].key, "31");
        let ranked = c.sources_for(id).await?;
        assert!(ranked.iter().any(|source| source.key == "31"));
        assert!(ranked.windows(2).all(|s| s[0].label <= s[1].label));
        assert_eq!(c.cached_sources_for(id)?.expect("ranked cache"), ranked);

        c.set_workflow_enabled(id, "review", false)?;
        c.sync_once().await?;
        let details = c
            .cached_workflow(id, "review")?
            .context("missing details")?;
        assert!(!details.enabled);
        assert_eq!(details.steps, ["Review flagged observations"]);
        assert_eq!(details.run_history.len(), 3);
        assert!(details.run_history.iter().all(|r| r.at.is_some()));
        assert_eq!(
            details.run_history[0].result.as_deref(),
            Some("Filed the review")
        );
        assert_eq!(
            details.run_history[1].result.as_deref(),
            Some("Sent 1 message")
        );
        assert_eq!(
            details.run_history[2].result.as_deref(),
            Some("The source connection timed out.")
        );
        assert_eq!(c.cached_files(id)?, ["notes/review.md"]);
        assert_eq!(
            c.get_file(id, "notes/review.md").await?.bytes,
            b"Navigation review notes"
        );
        Ok(())
    })
}

#[test]
fn browser_sign_in_registers_the_real_project_and_saves_a_local_credential_copy() -> Result<()> {
    use meep_connections::{MemorySecrets, SecretStore};
    let lab = Lab::open()?;
    lab.runtime.block_on(async {
        let mut secrets = MemorySecrets::default();
        for (region, configured) in [
            (Region::Us, false),
            (Region::Us, true),
            (Region::Local, true),
        ] {
            lab.backend.client.set_preference(
                "posthog-project",
                &json!({
                    "label":"Design", "email":"design@example.test", "region":region, "project":7
                }),
            )?;
            if configured {
                std::fs::write(
                    lab.backend.root.join(if region == Region::Local {
                        "posthog-local-client-id"
                    } else {
                        "posthog-us-client-id"
                    }),
                    "fixture-provisioned",
                )?;
            }
            let identity = lab
                .backend
                .login_with(
                    region,
                    &lab.origin,
                    meep_posthog::oauth::Callback::bind(0).await?,
                    &mut secrets,
                    |url| {
                        let params: BTreeMap<_, _> = url.query_pairs().collect();
                        assert!(
                            !params["scope"]
                                .split_whitespace()
                                .any(|s| s == "llm_gateway:read")
                        );
                        assert_eq!(params["code_challenge_method"], "S256");
                        let mut callback = reqwest::Url::parse(&params["redirect_uri"])?;
                        callback
                            .query_pairs_mut()
                            .append_pair("code", "approved")
                            .append_pair("state", &params["state"]);
                        tokio::spawn(async move {
                            reqwest::get(callback).await.expect("loopback callback");
                        });
                        Ok(())
                    },
                )
                .await?;
            assert_eq!(identity.label, "Navigation team");
            assert_eq!(identity.email.as_deref(), Some("design@example.test"));
            let saved: Value = serde_json::from_str(
                &secrets
                    .get(&lab.backend.server, "posthog")?
                    .context("missing local credentials")?,
            )?;
            assert_eq!(saved["refresh_token"], "signed-in-refresh");
            assert_eq!(
                saved["client_id"],
                if configured {
                    "fixture-provisioned"
                } else {
                    "native-client"
                }
            );
            assert_eq!(saved["project_id"], "7");
            assert_eq!(saved["region"], lab.origin);
            if region == Region::Local {
                let config: Value =
                    serde_json::from_str(saved["config"].as_str().context("missing MCP config")?)?;
                assert_eq!(config["mcp_endpoint"], "http://localhost:8787/mcp");
            } else {
                assert!(saved.get("config").is_none());
            }
            assert_eq!(
                lab.backend.client.connections()?.connections[0]
                    .account
                    .as_deref(),
                Some("Navigation team")
            );
        }
        Ok(())
    })
}

/// Optional end-to-end development check against a separately provisioned local PostHog.
#[test]
#[ignore = "requires a local PostHog, a fixture account, and a consent helper"]
fn local_posthog_browser_sign_in_registers_with_the_real_server() -> Result<()> {
    use meep_connections::{MemorySecrets, SecretStore};
    let server_data = std::env::var("MEEP_LIVE_SERVER_DATA")?;
    let client_file = std::env::var("MEEP_LIVE_OAUTH_CLIENT_ID_FILE")?;
    let helper = std::env::var("MEEP_LIVE_OAUTH_HELPER")?;
    let root = tempfile::tempdir()?;
    std::fs::copy(client_file, root.path().join("posthog-local-client-id"))?;
    let device_token =
        std::fs::read_to_string(std::path::Path::new(&server_data).join("device-token"))?;
    let port = std::env::var("MEEP_DEV_PORT").unwrap_or_else(|_| "47951".into());
    let address = format!("http://127.0.0.1:{port}");
    let address = address.as_str();
    let client = Client::open(
        root.path().join("replica.sqlite"),
        Arc::new(HttpTransport::new(address, device_token.trim())?),
    )?;
    let backend = Backend {
        direct: None,
        client,
        server: address.into(),
        root: root.path().to_owned(),
        credentials: "test-local".into(),
    };
    let runtime = Runtime::new()?;
    runtime.block_on(async {
        let mut keychain = MemorySecrets::default();
        let identity = backend
            .login_with(
                Region::Local,
                "http://localhost:8010",
                meep_posthog::oauth::Callback::bind(43180).await?,
                &mut keychain,
                |url| {
                    let state = url
                        .query_pairs()
                        .find(|(key, _)| key == "state")
                        .map(|(_, value)| value.into_owned())
                        .context("Missing OAuth state")?;
                    let mut callback = reqwest::Url::parse("http://127.0.0.1:43180/callback")?;
                    callback
                        .query_pairs_mut()
                        .append_pair("state", &state)
                        .append_pair("error", "fixture_helper_failed");
                    let target = format!(
                        "{}?{}",
                        callback.path(),
                        callback.query().context("Missing callback query")?
                    );
                    let mut child = std::process::Command::new(&helper)
                        .env("MEEP_LIVE_AUTHORIZE_URL", url.as_str())
                        .stdin(std::process::Stdio::null())
                        .stdout(std::process::Stdio::null())
                        .stderr(std::process::Stdio::inherit())
                        .spawn()?;
                    std::thread::spawn(move || {
                        if !child.wait().is_ok_and(|status| status.success()) {
                            eprintln!("Fixture consent helper failed; ending OAuth test");
                            use std::io::Write as _;
                            if let Ok(mut socket) = std::net::TcpStream::connect("127.0.0.1:43180")
                            {
                                let _ = write!(
                                    socket,
                                    "GET {target} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
                                );
                            }
                        }
                    });
                    Ok(())
                },
            )
            .await?;
        assert!(identity.region == Region::Local);
        let saved: Value = serde_json::from_str(
            &keychain
                .get("test-local", "posthog")?
                .context("missing sign-in")?,
        )?;
        assert_eq!(saved["region"], "http://localhost:8010");
        assert!(
            saved["refresh_token"]
                .as_str()
                .is_some_and(|s| !s.is_empty())
        );
        let config: Value =
            serde_json::from_str(saved["config"].as_str().context("missing MCP endpoint")?)?;
        assert_eq!(config["mcp_endpoint"], "http://localhost:8787/mcp");
        Ok(())
    })
}

#[test]
fn offline_workflow_switches_survive_reopen_and_coalesce_before_delivery() -> Result<()> {
    let lab = Lab::open()?;
    let id = lab.seed()?;
    let path = lab.backend.root.join("replica.sqlite");
    let unreachable = Arc::new(HttpTransport::new("http://127.0.0.1:1", "offline")?);
    let client = Client::open(&path, unreachable.clone())?;
    for enabled in [false, true, false] {
        client.set_workflow_enabled(id, "review", enabled)?;
    }
    assert!(matches!(
        client.status(),
        Status::Offline { pending: 1, .. }
    ));
    drop(client);
    let reopened = Client::open(path, unreachable)?;
    assert!(
        !reopened
            .cached_workflow(id, "review")?
            .context("cached state")?
            .enabled
    );
    assert!(lab.upstream.active.load(Ordering::SeqCst));
    lab.runtime.block_on(lab.backend.client.sync_once())?;
    assert!(!lab.upstream.active.load(Ordering::SeqCst));
    Ok(())
}

#[test]
fn polling_an_approved_gateway_read_emits_only_changes_and_sign_in_preserves_grants() -> Result<()>
{
    let lab = Lab::open()?;
    let id = lab.seed()?;
    let client = &lab.backend.client;
    lab.runtime.block_on(async {
        let grant = client
            .register_connection("posthog", &registration(&lab.origin))
            .await?;
        assert_eq!(grant.grants, [id]);
        let mut wrong = registration(&lab.origin);
        wrong.secrets.insert("project_id".into(), "8".into());
        assert!(client.register_connection("posthog", &wrong).await.is_err());
        client.issue(
            id,
            Command::SetWatch {
                watches: vec![Watch {
                    id: WatchId(Uuid::new_v4()),
                    connection: "posthog".into(),
                    kind: "service".into(),
                    key: INSTALLATION.into(),
                    label: "Design chat".into(),
                }],
            },
        )?;
        client.sync_once().await?;
        tokio::time::timeout(std::time::Duration::from_secs(6), async {
            while lab.upstream.reads.load(Ordering::SeqCst) == 0 {
                tokio::time::sleep(std::time::Duration::from_millis(20)).await;
            }
        })
        .await?;
        client.set_workflow_enabled(id, "review", false)?;
        client.sync_once().await?;
        tokio::time::timeout(std::time::Duration::from_secs(6), async {
            loop {
                client.sync_once().await?;
                let changed = client
                    .topic(id)?
                    .context("missing topic")?
                    .threads
                    .into_iter()
                    .flat_map(|t| t.messages)
                    .filter(|m| m.text.contains("New observation"))
                    .count();
                if changed > 0 {
                    assert_eq!(changed, 1);
                    break;
                }
                tokio::time::sleep(std::time::Duration::from_millis(60)).await;
            }
            Ok::<_, anyhow::Error>(())
        })
        .await??;
        Ok(())
    })
}

#[test]
fn a_chat_question_can_reference_only_topics_granted_to_the_same_account() -> Result<()> {
    let lab = Lab::open()?;
    let c = &lab.backend.client;
    let topic = lab.seed()?;
    c.create_topic(
        TopicId(Uuid::new_v4()),
        "Canvas".into(),
        "Understand drawing usage.".into(),
        "posthog",
    )?;
    c.issue(
        TopicId(Uuid::new_v4()),
        Command::CreateTopic {
            name: "Private".into(),
            mission: "Unshared project context.".into(),
        },
    )?;
    let message = MessageId(Uuid::new_v4());
    let answer = TaskId(Uuid::new_v4());
    c.issue(
        topic,
        Command::Chat {
            message_id: message,
            text: "Compare @Canvas and @Private?".into(),
            task_id: answer,
            queue: false,
        },
    )?;
    lab.runtime.block_on(async {
        tokio::time::timeout(std::time::Duration::from_secs(8),async {
            loop {
                c.sync_once().await?;
                let state = c.topic(topic)?.context("missing topic")?;
                if state.threads.iter().any(|t|t.id.0 == message.0 && t.outcomes.iter().any(|o|matches!(o,Outcome::Reply{text,..} if text=="The navigation review is ready."))) {
                    let task = state.tasks.iter().find(|t| t.id == answer).context("missing chat task")?;
                    assert_eq!(task.column, Column::Done);
                    assert_eq!(task.from_thread, Some(ThreadId(message.0)));
                    assert_eq!(task.assignment, Some(InboxAssignment::ChatAnswer));
                    break;
                }
                tokio::time::sleep(std::time::Duration::from_millis(75)).await;
            }
            Ok::<_,anyhow::Error>(())
        }).await??;
        anyhow::Ok(())
    })?;

    let prompts = lab.upstream.prompts.lock().expect("recorded prompts");
    let mut answers = Vec::new();
    for prompt in prompts.iter() {
        assert!(!prompt.contains("Unshared project context."));
        let (marker, body) = prompt.split_once('\n').context("attribution line")?;
        let context: Value = serde_json::from_str(body)?;
        if context["task"]["id"] == json!(answer) {
            answers.push((marker, context));
        }
    }
    assert_eq!(answers.len(), 1, "expected one prompt for the chat task");
    let (marker, context) = &answers[0];
    assert_eq!(*marker, format!("[meep topic:{topic}]"));
    assert_eq!(context["topic_name"], "New web");
    assert_eq!(context["mission"], "Simplify the new web navigation.");
    assert_eq!(context["task"]["title"], "Compare @Canvas and @Private?");
    assert!(
        context["routines"]
            .as_array()
            .context("missing bound routines")?
            .iter()
            .any(|r| r["id"] == "review")
    );
    Ok(())
}

#[test]
fn a_topic_chat_answers_on_the_model_chosen_in_its_composer() -> Result<()> {
    let lab = Lab::open()?;
    let c = &lab.backend.client;
    let topic = lab.seed()?;
    lab.runtime.block_on(async {
        let catalogue = c.chat_models(topic).await?;
        let ids: Vec<_> = catalogue.models.iter().map(|m| m.id.as_str()).collect();
        assert_eq!(
            ids,
            [
                "claude-test",
                "claude-deep",
                "claude-haiku-4-5",
                "codex-test"
            ]
        );
        assert_eq!(catalogue.selected, None);
        assert_eq!(
            catalogue
                .default_model
                .as_ref()
                .map(|m| (m.id.as_str(), m.runtime.as_deref())),
            Some(("claude-test", Some("claude")))
        );
        assert!(!catalogue.models[2].meep_tools);
        assert!(!catalogue.models[3].meep_tools);
        assert!(catalogue.models[1].meep_tools);
        c.set_chat_model(topic, Some("codex-test")).await?;
        let chosen = c.set_chat_model(topic, Some("claude-deep")).await?;
        assert_eq!(chosen.selected.as_deref(), Some("claude-deep"));
        assert_eq!(
            c.chat_models(topic).await?.selected.as_deref(),
            Some("claude-deep")
        );
        anyhow::Ok(())
    })?;
    let message = MessageId(Uuid::new_v4());
    c.issue(
        topic,
        Command::Chat {
            message_id: message,
            text: "What changed this week?".into(),
            task_id: TaskId(Uuid::new_v4()),
            queue: false,
        },
    )?;
    lab.runtime.block_on(async {
        tokio::time::timeout(std::time::Duration::from_secs(8), async {
            loop {
                c.sync_once().await?;
                let answered = lab
                    .upstream
                    .runs
                    .lock()
                    .unwrap()
                    .iter()
                    .any(|run| run["model"] == "claude-deep");
                if answered {
                    break;
                }
                tokio::time::sleep(std::time::Duration::from_millis(75)).await;
            }
            anyhow::Ok(())
        })
        .await??;
        // Restoring the default goes back to the account's first Claude model.
        assert_eq!(c.set_chat_model(topic, None).await?.selected, None);
        anyhow::Ok(())
    })
}

#[gpui::test]
fn missing_grant_can_be_restored_from_the_model_picker(cx: &mut TestAppContext) {
    let lab = Lab::open().unwrap();
    let topic = lab.seed().unwrap();
    let c = &lab.backend.client;
    lab.runtime.block_on(async {
        c.put_connection("posthog", &registration(&lab.origin)).await.unwrap();
        tokio::time::timeout(std::time::Duration::from_secs(8), async {
            loop {
                if c.chat_models(topic).await.is_err_and(|e| matches!(
                    e.downcast_ref::<meep_client::TransportError>(),
                    Some(meep_client::TransportError::Api {code, ..}) if code == "missing_topic_grant"
                )) { break; }
                tokio::time::sleep(std::time::Duration::from_millis(30)).await;
            }
        }).await.unwrap();
    });
    let (view, ui) = fixture(&lab, cx);
    ui.update(|w, cx| {
        view.update(cx, |s, cx| {
            s.go(Page::Topic(topic, Tab::Inbox, None), w, cx)
        })
    });
    click(ui, "crumb-topic");
    let result = lab.runtime.block_on(c.chat_models(topic));
    ui.update(|_, cx| view.update(cx, |s, cx| s.show_chat_models(result, cx)));
    click(ui, "model-picker");
    assert!(
        labels(ui)
            .iter()
            .any(|s| s == "Connect this topic to PostHog")
    );
    click(ui, "agent-picker-recover");
    for _ in 0..300 {
        draw(ui);
        if ui.update(|_, cx| !view.read(cx).catalogue.models.is_empty()) {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    assert_eq!(
        ui.update(|_, cx| view
            .read(cx)
            .catalogue
            .models
            .iter()
            .map(|model| model.id.clone())
            .collect::<Vec<_>>()),
        [
            "claude-test",
            "claude-deep",
            "claude-haiku-4-5",
            "codex-test"
        ]
    );
    assert_eq!(c.connections().unwrap().connections[0].grants, [topic]);
}

#[gpui::test]
fn files_attached_in_the_chat_composer_upload_into_the_topic_and_ride_with_the_message(
    cx: &mut TestAppContext,
) {
    let lab = Lab::open().unwrap();
    let id = lab.seed().unwrap();
    let (view, ui) = fixture(&lab, cx);
    ui.update(|w, cx| view.update(cx, |s, cx| s.go(Page::Topic(id, Tab::Inbox, None), w, cx)));
    click(ui, "crumb-topic");
    let picked = tempfile::tempdir().unwrap();
    let file = picked.path().join("brief.md");
    std::fs::write(&file, "Launch brief for the navigation rollout").unwrap();
    // A second file with the same name gets its own path instead of replacing the first.
    let again = picked.path().join("again");
    std::fs::create_dir(&again).unwrap();
    std::fs::write(again.join("brief.md"), "Second brief").unwrap();
    ui.update(|w, cx| {
        view.update(cx, |s, cx| {
            s.upload_chat_files(vec![file.clone(), again.join("brief.md")], w, cx)
        })
    });
    let mut attached = vec![];
    for _ in 0..200 {
        ui.run_until_parked();
        attached = ui.update(|_, cx| view.read(cx).chat_files.clone());
        if attached.len() == 2 {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    let second = attached
        .iter()
        .position(|p| p == "uploads/brief 2.md")
        .unwrap();
    attached.sort();
    assert_eq!(attached, ["uploads/brief 2.md", "uploads/brief.md"]);
    assert!(
        lab.backend
            .client
            .cached_files(id)
            .unwrap()
            .contains(&"uploads/brief.md".to_owned())
    );
    draw(ui);
    click(ui, &format!("remove-chat-file-{second}"));
    ui.update(|w, cx| {
        let composer = view.read(cx).composer.clone();
        composer.update(cx, |e, cx| e.focus(w, cx))
    });
    ui.simulate_input("Summarize the brief");
    ui.simulate_keystrokes("enter");
    let state = lab.backend.client.topic(id).unwrap().unwrap();
    let message = state
        .threads
        .iter()
        .flat_map(|t| &t.messages)
        .find(|m| m.text.starts_with("Summarize the brief"))
        .unwrap();
    assert!(
        message
            .text
            .contains("Launch brief for the navigation rollout")
    );
    assert!(!message.text.contains("Second brief"));
    assert!(ui.update(|_, cx| view.read(cx).chat_files.is_empty()));
}

#[gpui::test]
fn sending_chat_and_editing_the_mission_update_the_replica(cx: &mut TestAppContext) {
    let lab = Lab::open().unwrap();
    let id = lab.seed().unwrap();
    let (view, ui) = fixture(&lab, cx);
    ui.update(|w, cx| view.update(cx, |s, cx| s.go(Page::Topic(id, Tab::Inbox, None), w, cx)));
    click(ui, "crumb-topic");
    ui.simulate_input("Review the navigation rollout");
    ui.simulate_keystrokes("enter");
    assert!(
        lab.backend
            .client
            .topic(id)
            .unwrap()
            .unwrap()
            .threads
            .iter()
            .any(|t| t
                .messages
                .iter()
                .any(|m| m.text == "Review the navigation rollout"))
    );
    ui.update(|w, cx| view.update(cx, |s, cx| s.go(Page::Topic(id, Tab::Mission, None), w, cx)));
    click(ui, "mission-text");
    ui.simulate_keystrokes("cmd-a");
    ui.simulate_input("An abandoned edit");
    ui.simulate_keystrokes("escape");
    assert_eq!(
        lab.backend.client.topic(id).unwrap().unwrap().topic.mission,
        "Simplify the new web navigation."
    );
    click(ui, "edit-mission");
    ui.simulate_keystrokes("cmd-a");
    ui.simulate_input("Ship the redesigned navigation.");
    ui.simulate_keystrokes("enter");
    assert!(!ui.update(|_, cx| view.read(cx).editing));
    assert_eq!(
        lab.backend.client.topic(id).unwrap().unwrap().topic.mission,
        "Ship the redesigned navigation."
    );
}

#[gpui::test]
fn search_keys_move_the_highlight_open_its_destination_and_dismiss(cx: &mut TestAppContext) {
    let lab = Lab::open().unwrap();
    for name in ["Components", "Navigation", "Release"] {
        lab.backend
            .client
            .create_topic(
                TopicId(Uuid::new_v4()),
                name.into(),
                String::new(),
                "posthog",
            )
            .unwrap();
    }
    let (view, ui) = fixture(&lab, cx);
    ui.simulate_keystrokes("cmd-k down down up");
    let destination = ui.update(|_, cx| {
        let s = view.read(cx);
        assert_eq!(s.search_index, 1);
        s.hits(cx)[1].2.clone()
    });
    ui.simulate_keystrokes("enter");
    ui.update(|_, cx| {
        assert_eq!(view.read(cx).page, destination);
        assert!(view.read(cx).sheet.is_none());
    });
    ui.simulate_keystrokes("cmd-k down");
    ui.simulate_input("Release");
    ui.update(|_, cx| assert_eq!(view.read(cx).search_index, 0));
    ui.simulate_keystrokes("escape");
    ui.update(|_, cx| {
        assert_eq!(view.read(cx).page, destination);
        assert!(view.read(cx).sheet.is_none());
    });
}

#[gpui::test]
fn inbox_sources_use_the_service_behind_a_watch_and_keep_the_channel_in_details(
    cx: &mut TestAppContext,
) {
    let lab = Lab::open().unwrap();
    let id = lab.seed().unwrap();
    let (view, ui) = fixture(&lab, cx);
    ui.update(|_, cx| {
        let s = view.read(cx);
        let mut topic = s
            .states
            .iter()
            .find(|t| t.topic.id == id)
            .unwrap()
            .topic
            .clone();
        topic.default_watches_mut().push(Watch {
            id: WatchId(Uuid::new_v4()),
            kind: "service".into(),
            connection: "posthog".into(),
            key: "installation".into(),
            label: "GitHub".into(),
        });
        for (connection, channel, label) in [
            ("posthog", "installation", "GitHub"),
            ("posthog", "flag-1", "PostHog"),
            ("slack", "design", "Slack"),
        ] {
            let source = Source::Connection {
                connection: connection.into(),
                channel: channel.into(),
            };
            assert_eq!(s.source(&topic, &source), label);
        }
        assert_eq!(s.source(&topic, &Source::Topic(id)), "@New web");
        assert_eq!(s.source(&topic, &Source::User), "You");
    });
}

#[cfg(feature = "ui-previews")]
pub(crate) mod previews;

fn labels(ui: &mut VisualTestContext) -> Vec<String> {
    draw(ui);
    ui.update(|w, _| {
        w.visual_elements()
            .iter()
            .filter_map(|e| e.label.as_ref().map(ToString::to_string))
            .collect()
    })
}

fn click_label(ui: &mut VisualTestContext, label: &str) {
    draw(ui);
    let point = ui.update(|w, _| {
        w.visual_elements()
            .iter()
            .rev()
            .find(|e| e.label.as_deref() == Some(label))
            .unwrap_or_else(|| panic!("missing {label}"))
            .bounds
            .center()
    });
    ui.simulate_mouse_move(point, None, Modifiers::default());
    draw(ui);
    ui.simulate_click(point, Modifiers::default());
    draw(ui)
}

#[gpui::test]
fn a_topic_row_menu_renames_archives_restores_and_deletes(cx: &mut TestAppContext) {
    let lab = Lab::open().unwrap();
    let id = lab.seed().unwrap();
    let (_v, ui) = fixture(&lab, cx);
    let topic = |lab: &Lab| lab.backend.client.topic(id).unwrap();
    // The trigger sits inside its row, so hovering the row reveals it where it is clicked.
    let row = center(ui, &format!("topic-{id}"));
    let actions = center(ui, &format!("topic-actions-{id}"));
    assert!((row.y - actions.y).abs() < px(1.), "{row:?} {actions:?}");
    assert!(actions.x > row.x, "{row:?} {actions:?}");
    click(ui, &format!("topic-actions-{id}"));
    click_label(ui, "Rename…");
    ui.simulate_keystrokes("cmd-a");
    ui.simulate_input("Launch watch");
    ui.simulate_keystrokes("enter");
    assert_eq!(topic(&lab).unwrap().topic.name, "Launch watch");
    click(ui, &format!("topic-actions-{id}"));
    click_label(ui, "Archive");
    assert!(topic(&lab).unwrap().archived);
    // Archived topics move into a collapsed group when they are not open.
    click(ui, "archived-toggle");
    click(ui, &format!("topic-actions-{id}"));
    click_label(ui, "Restore from archive");
    assert!(!topic(&lab).unwrap().archived);
    click(ui, &format!("topic-actions-{id}"));
    click_label(ui, "Delete…");
    click(ui, "confirm-delete-topic");
    assert!(topic(&lab).is_none());
}

#[gpui::test]
fn both_navigation_key_pairs_follow_visible_inbox_board_and_routine_order(cx: &mut TestAppContext) {
    let mut lab = Lab::open().unwrap();
    let id = lab.seed().unwrap();
    lab.publish_sample_reports(id).unwrap();
    lab.disconnect().unwrap();
    let client = &lab.backend.client;
    let task = TaskId(Uuid::new_v4());
    let next = TaskId(Uuid::new_v4());
    for (id_task, title) in [(task, "Follow up"), (next, "Review draft")] {
        client
            .issue(
                id,
                Command::AddTask {
                    id: id_task,
                    title: title.into(),
                },
            )
            .unwrap();
    }
    client
        .issue(
            id,
            Command::MoveTask {
                task: next,
                column: Column::NeedsYou,
            },
        )
        .unwrap();
    client
        .issue(
            id,
            Command::SetRoutine {
                routine: RoutineBinding {
                    id: "digest".into(),
                    external_id: Uuid::new_v4().to_string(),
                    name: "Daily digest".into(),
                    trigger: "Daily".into(),
                    backend: "posthog".into(),
                    watches: vec![],
                },
            },
        )
        .unwrap();
    let state = client.topic(id).unwrap().unwrap();
    let threads = super::pages::ordered_threads(&state, false);
    let (v, ui) = fixture(&lab, cx);
    let visible_tasks = ui.update(|_, cx| v.read(cx).visible_tasks(&state));
    click(ui, &format!("topic-{id}"));
    for (tab, first, second) in [
        (
            Tab::Inbox,
            Detail::Thread(threads[0].id),
            Detail::Thread(threads[1].id),
        ),
        // The list leads with what needs you.
        (
            Tab::Tasks,
            Detail::Task(visible_tasks[0]),
            Detail::Task(visible_tasks[1]),
        ),
        (
            Tab::Routines,
            Detail::Routine("review".into()),
            Detail::Routine("digest".into()),
        ),
    ] {
        open_section(ui, &format!("{tab:?}"));
        // Only the two-item lists check that Down stops at the end.
        let stops = tab == Tab::Inbox;
        for (keys, selection) in [
            ("j", &first),
            ("down", &second),
            ("down", &second),
            ("k", &first),
            ("j", &second),
            ("up", &first),
        ]
        .into_iter()
        .enumerate()
        .filter(|(i, _)| stops || *i != 2)
        .map(|(_, step)| step)
        {
            ui.simulate_keystrokes(keys);
            ui.update(|_, cx| {
                assert_eq!(
                    v.read(cx).page,
                    Page::Topic(id, tab, Some(selection.clone()))
                )
            });
        }
        ui.simulate_keystrokes("escape");
        ui.update(|_, cx| assert_eq!(v.read(cx).page, Page::Topic(id, tab, None)));
    }
}

#[gpui::test]
fn dragging_a_card_between_columns_persists_the_move_and_the_board_order(cx: &mut TestAppContext) {
    let mut lab = Lab::open().unwrap();
    let id = lab.seed().unwrap();
    lab.disconnect().unwrap();
    let task = TaskId(Uuid::new_v4());
    lab.backend
        .client
        .issue(
            id,
            Command::AddTask {
                id: task,
                title: "Review navigation".into(),
            },
        )
        .unwrap();
    let (v, ui) = fixture(&lab, cx);
    click(ui, &format!("topic-{id}"));
    open_section(ui, "Tasks");
    click(ui, "tasks-board");
    assert!(ui.update(|_, cx| v.read(cx).task_board(id)));
    let card = format!("card-{task}");
    drag(ui, &card, "column-InProgress");
    assert_eq!(
        lab.backend.client.topic(id).unwrap().unwrap().tasks[0].column,
        Column::InProgress
    );
    drag(ui, &card, "column-Todo");
    let reopened = Client::open(
        lab.backend.root.join("replica.sqlite"),
        Arc::new(HttpTransport::new(&lab.backend.server, "offline").unwrap()),
    )
    .unwrap();
    assert_eq!(
        reopened.topic(id).unwrap().unwrap().tasks[0].column,
        Column::Todo
    );
}

mod table_records {
    use super::super::tables::read;
    use anyhow::Result;
    use core::prelude::v1::test;
    #[test]
    fn quoted_csv_keeps_commas_and_newlines_inside_cells() -> Result<()> {
        let table = read("results.csv", b"Name,Note\nRail,\"One, two\nand three\"\n")?;
        assert_eq!(table.columns, ["Name", "Note"]);
        assert_eq!(table.rows[0], ["Rail", "One, two\nand three"]);
        Ok(())
    }
    #[test]
    fn sparse_json_records_share_one_ordered_header() -> Result<()> {
        let t = read("results.json", br#"[{"a":1},{"b":2}]"#)?;
        assert_eq!(t.columns, ["a", "b"]);
        assert_eq!(t.rows, [["1", ""], ["", "2"]]);
        Ok(())
    }
    #[test]
    fn declared_columns_align_short_rows_and_reject_cells_without_a_header() -> Result<()> {
        let t = read(
            "grid.json",
            br#"{"columns":["State","Added by"],"rows":[["Done"],[]]}"#,
        )?;
        assert_eq!(t.rows, [["Done", ""], ["", ""]]);
        assert!(
            read(
                "bad.json",
                br#"{"columns":["State"],"rows":[["Done","Inbox"]]}"#
            )
            .is_err()
        );
        Ok(())
    }
}

#[test]
fn hosted_pairing_rejects_credentials_on_the_command_line() {
    let args = [
        "topics",
        "--server",
        "https://topics.test",
        "--token",
        "secret",
    ];
    assert!(Options::try_parse_from(args).is_err());
}

#[gpui::test]
fn approving_an_inbox_investigation_releases_its_start(cx: &mut TestAppContext) {
    let mut lab = Lab::open().unwrap();
    let topic = lab.seed().unwrap();
    lab.runtime
        .block_on(async {
            lab.gateway_event("held-investigation", "Inspect the checkout spike")
                .await?;
            lab.server.engine().sort_pending(topic).await?;
            lab.backend.client.sync_once().await
        })
        .unwrap();
    lab.disconnect().unwrap();
    let state = lab.backend.client.topic(topic).unwrap().unwrap();
    let task = state
        .tasks
        .iter()
        .find(|t| t.review_before_start)
        .unwrap()
        .id;
    let (_, ui) = fixture(&lab, cx);
    click(ui, &format!("topic-{topic}"));
    open_section(ui, "Tasks");
    ui.simulate_keystrokes("j");
    let screen = labels(ui);
    assert!(screen.iter().any(|s| s == "Sub-agent · PostHog Tasks"));
    assert!(screen.iter().any(|s| s == "Approve start"));
    click(ui, "approve");
    let state = lab.backend.client.topic(topic).unwrap().unwrap();
    assert_eq!(
        state.tasks.iter().find(|t| t.id == task).unwrap().column,
        Column::Todo
    );
}

mod source_activity;
mod store;

#[gpui::test]
fn a_person_resolves_an_ambiguous_fact_pair_from_context(cx: &mut TestAppContext) {
    let mut lab = Lab::open().unwrap();
    let topic = lab.seed().unwrap();
    let new = Fact {
        id: FactId(Uuid::new_v4()),
        text: "Only two navigation components remain.".into(),
        provenance: Provenance {
            origin: None,
            author: "Sam".into(),
            via: "Migration log".into(),
            at: chrono::Utc::now(),
            thread: None,
        },
        superseded_by: None,
        invalidated_by: None,
        withdrawn_at: None,
    };
    lab.runtime
        .block_on(async {
            lab.server.engine().add_fact(topic, new.clone()).await?;
            lab.server.engine().tick_topic(topic).await?;
            lab.backend.client.sync_once().await
        })
        .unwrap();
    lab.disconnect().unwrap();
    let state = lab.backend.client.topic(topic).unwrap().unwrap();
    let review = state
        .threads
        .iter()
        .find(|t| t.key.starts_with("fact-review/"))
        .unwrap()
        .id;
    let attention = NeedsYouItem::Decide {
        topic,
        thread: review.to_string(),
        title: "Fact conflict".into(),
        detail: "Review".into(),
    };
    assert_eq!(
        pages::attention(&attention, &state).unwrap().page,
        Page::Topic(topic, Tab::Facts, Some(Detail::Thread(review)))
    );
    let (view, ui) = fixture(&lab, cx);
    click(ui, &format!("topic-{topic}"));
    open_section(ui, "Facts");
    ui.simulate_keystrokes("j");
    ui.update(|_, cx| {
        assert_eq!(
            view.read(cx).page,
            Page::Topic(topic, Tab::Facts, Some(Detail::Thread(review)))
        )
    });
    ui.simulate_keystrokes("escape");
    click(ui, &format!("review-{review}"));
    let screen = labels(ui);
    for label in ["Keep A", "Keep B", "Keep both"] {
        assert!(screen.iter().any(|s| s == label));
    }
    assert!(screen.iter().any(|s| s.contains("Migration log")));
    click(ui, "answer-0");
    let state = lab.backend.client.topic(topic).unwrap().unwrap();
    assert_eq!(
        state
            .topic
            .facts
            .iter()
            .filter(|f| f.is_current())
            .map(|f| f.id)
            .collect::<Vec<_>>(),
        [new.id]
    );
    assert!(!state.needs_you().threads.contains(&review));
}

#[gpui::test]
fn a_proposed_fact_waits_in_the_native_inbox_until_the_person_saves_it(cx: &mut TestAppContext) {
    let mut lab = Lab::open().unwrap();
    let topic = lab.seed().unwrap();
    let text = "The navigation migration is complete.";
    lab.runtime
        .block_on(async {
            lab.server
                .engine()
                .ingest(meep_ingest::Event {
                    connection: "slack".into(),
                    kind: "channel".into(),
                    channel: "design".into(),
                    external_id: "evidence-review".into(),
                    thread_hint: Some("evidence-review".into()),
                    at: chrono::Utc::now(),
                    author: "Sam".into(),
                    text: "The changelog is ready.".into(),
                    attributes: json!({"fact":text,"needs_decision":true}),
                })
                .await?;
            lab.server.engine().sort_pending(topic).await?;
            lab.backend.client.sync_once().await
        })
        .unwrap();
    lab.disconnect().unwrap();
    let state = lab.backend.client.topic(topic).unwrap().unwrap();
    assert!(!state.topic.facts.iter().any(|f| f.text == text));
    let review = state
        .threads
        .iter()
        .find(|t| {
            t.messages
                .iter()
                .any(|m| m.external_id.as_deref() == Some("evidence-review"))
        })
        .unwrap()
        .id;
    let (view, ui) = fixture(&lab, cx);
    // Needs You opens the source evidence behind the pending decision.
    ui.update(|w, cx| {
        view.update(cx, |s, cx| {
            s.go(
                Page::Topic(topic, Tab::Facts, Some(Detail::Thread(review))),
                w,
                cx,
            )
        })
    });
    let screen = labels(ui);
    assert!(screen.iter().any(|s| s == "Save fact") && screen.iter().any(|s| s == text));
    assert!(screen.iter().any(|s| s == "Investigate"));
    click(ui, "answer-0");
    let state = lab.backend.client.topic(topic).unwrap().unwrap();
    let fact = state.topic.facts.iter().find(|f| f.text == text).unwrap();
    assert_eq!(fact.provenance.thread, Some(review));
    assert!(!state.needs_you().threads.contains(&review));
}

#[gpui::test]
fn retrying_a_failed_routine_from_its_card_queues_a_new_run(cx: &mut TestAppContext) {
    let now = chrono::DateTime::UNIX_EPOCH;
    let topic = TopicId(Uuid::new_v4());
    let task = TaskId(Uuid::new_v4());
    let mut state = TopicState::new(Topic::new(topic, "Stock", now));
    state
        .add_task(task, "Check stock", Actor::User, None, now)
        .unwrap();
    state.tasks[0].assignment = Some(InboxAssignment::Routine("stock".into()));
    state
        .work_needs_attention(task, "The inventory source was unavailable.".into(), now)
        .unwrap();
    let mut lab = Lab::with_snapshots([state]).unwrap();
    lab.runtime
        .block_on(lab.backend.client.sync_once())
        .unwrap();
    lab.disconnect().unwrap();
    let (_, ui) = fixture(&lab, cx);
    click(ui, &format!("topic-{topic}"));
    open_section(ui, "Tasks");
    click(ui, &format!("card-{task}"));
    // The run's own reason sits behind its disclosure.
    click(ui, "failure-details");
    let screen = labels(ui);
    for label in [
        "Mark done",
        "Retry routine",
        "The inventory source was unavailable.",
    ] {
        assert!(screen.iter().any(|s| s == label));
    }
    click(ui, "retry-routine");
    let state = lab.backend.client.topic(topic).unwrap().unwrap();
    assert_eq!(state.tasks[0].column, Column::Todo);
}

mod performance;
mod view_fixture;
