mod support;
use anyhow::{Context, Result};
use chrono::Utc;
use meep_topic::{Command, RoutineBinding, TopicId, Watch};
use meep_wire::*;
use reqwest::{Method, StatusCode};
use serde_json::json;
use support::{Host, create, envelope};
use uuid::Uuid;

async fn wait_for_posthog(h: &Host) -> Result<()> {
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            if h.request(Method::GET, "health")
                .send()
                .await?
                .json::<ServerHealth>()
                .await?
                .posthog
            {
                return anyhow::Ok(());
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await?
}

#[tokio::test]
async fn all_device_routes_require_auth_and_every_error_has_a_wire_body() -> Result<()> {
    let h = Host::new().await?;
    let t = Uuid::new_v4();
    for (method, p) in [
        (Method::GET, "health".into()),
        (Method::PUT, "settings/public-base-url".into()),
        (Method::DELETE, "connections/foo/credentials".into()),
        (Method::POST, "commands".into()),
        (Method::GET, "changes".into()),
        (Method::GET, format!("topics/{t}")),
        (Method::GET, "stream".into()),
        (Method::GET, "needs-you".into()),
        (Method::GET, "search?q=a".into()),
        (Method::GET, format!("topics/{t}/files/a")),
        (Method::PUT, format!("topics/{t}/files/a")),
        (Method::GET, "connections".into()),
        (Method::GET, "sources".into()),
        (Method::GET, format!("topics/{t}/files")),
        (Method::GET, format!("routines/{t}/review")),
        (Method::PUT, format!("connections/posthog/topics/{t}")),
        (Method::PUT, "connections/build".into()),
    ] {
        let res = h
            .client
            .request(method, format!("{}/v1/{p}", h.origin))
            .send()
            .await?;
        assert_eq!(res.status(), StatusCode::UNAUTHORIZED, "{p}");
        assert_eq!(res.json::<ApiError>().await?.code, "unauthorized");
    }
    for p in ["changes?cursor=invalid", "topics/invalid", "missing"] {
        let res = h.request(Method::GET, p).send().await?;
        assert!(res.status().is_client_error());
        assert!(!res.json::<ApiError>().await?.message.is_empty());
    }
    let health = h
        .request(Method::GET, "health")
        .send()
        .await?
        .json::<ServerHealth>()
        .await?;
    assert_eq!(health.cursor, 0);
    assert!(!health.posthog);
    h.close().await?;
    Ok(())
}

#[tokio::test]
async fn command_batches_preserve_order_retries_and_independent_rejections_across_restart()
-> Result<()> {
    let h = Host::new().await?;
    let t = Uuid::new_v4().into();
    let first = create(t);
    let task = Uuid::new_v4().into();
    let add = envelope(
        t,
        Command::AddTask {
            id: task,
            title: "Review release notes".into(),
        },
    );
    let results = h
        .commands(vec![first.clone(), create(t), add.clone(), add.clone()])
        .await?
        .results;
    assert_eq!(results.len(), 4);
    assert_eq!(
        results[0],
        CommandResult::Applied {
            id: first.id,
            topic: t,
            revision: 1
        }
    );
    assert!(matches!(results[1], CommandResult::Rejected { .. }));
    assert_eq!(
        results[2],
        CommandResult::Applied {
            id: add.id,
            topic: t,
            revision: 2
        }
    );
    assert_eq!(results[2], results[3]);
    let h = Host::open(h.close().await?).await?;
    assert_eq!(h.commands(vec![add]).await?.results[0], results[2]);
    let snapshot = h
        .request(Method::GET, &format!("topics/{t}"))
        .send()
        .await?
        .json::<TopicSnapshot>()
        .await?;
    assert_eq!(snapshot.state.tasks.len(), 1);
    assert_eq!(snapshot.revision, 2);
    let hits = h
        .request(Method::GET, "search?q=release&limit=1")
        .send()
        .await?
        .json::<SearchResults>()
        .await?
        .hits;
    assert_eq!(hits.len(), 1);
    let hits = h
        .request(Method::GET, "search?q=notes")
        .send()
        .await?
        .json::<SearchResults>()
        .await?
        .hits;
    assert_eq!(
        (hits[0].topic, hits[0].id.as_str()),
        (t, task.to_string().as_str())
    );
    h.close().await?;
    Ok(())
}

async fn event(response: &mut reqwest::Response, buf: &mut String) -> Result<StreamEvent> {
    loop {
        if let Some(end) = buf.find("\n\n") {
            let packet = buf.drain(..end + 2).collect::<String>();
            if let Some(line) = packet.lines().find_map(|line| line.strip_prefix("data:")) {
                return Ok(serde_json::from_str(line.trim())?);
            }
        } else {
            let bytes = response.chunk().await?.context("stream closed")?;
            buf.push_str(std::str::from_utf8(&bytes)?);
        }
    }
}

#[tokio::test]
async fn bounded_change_pages_and_live_stream_resume_at_the_last_delivered_revision() -> Result<()>
{
    let h = Host::new().await?;
    let mut live = h.request(Method::GET, "stream?cursor=0").send().await?;
    let mut data = String::new();
    assert!(matches!(
        event(&mut live, &mut data).await?,
        StreamEvent::Heartbeat { .. }
    ));
    let a = Uuid::new_v4().into();
    let b = Uuid::new_v4().into();
    h.commands(vec![
        create(a),
        envelope(
            a,
            Command::SetMission {
                mission: "New mission".into(),
            },
        ),
        create(b),
    ])
    .await?;
    assert_eq!(
        event(&mut live, &mut data).await?,
        StreamEvent::Topic {
            topic: a,
            revision: 1,
            cursor: 1
        }
    );
    drop(live);
    let mut resumed = h
        .request(Method::GET, "stream?cursor=1")
        .header("Last-Event-ID", "2")
        .send()
        .await?;
    assert_eq!(
        event(&mut resumed, &mut String::new()).await?,
        StreamEvent::Topic {
            topic: b,
            revision: 1,
            cursor: 3
        }
    );
    let page = h
        .request(Method::GET, "changes?cursor=0&limit=2")
        .send()
        .await?
        .json::<ChangePage>()
        .await?;
    assert_eq!((page.cursor, page.more, page.topics.len()), (2, true, 1));
    assert_eq!(page.topics[0].revision, 2);
    let page = h
        .request(Method::GET, "changes?cursor=2")
        .send()
        .await?
        .json::<ChangePage>()
        .await?;
    assert_eq!(
        (page.cursor, page.more, page.topics[0].state.topic.id),
        (3, false, b)
    );
    assert!(
        h.request(Method::GET, "changes?cursor=3")
            .send()
            .await?
            .json::<ChangePage>()
            .await?
            .topics
            .is_empty()
    );
    h.close().await?; // An open SSE connection must not hold shutdown open.
    Ok(())
}

#[tokio::test]
async fn binary_files_keep_named_revisions_scoped_to_their_topic() -> Result<()> {
    let h = Host::new().await?;
    let t = Uuid::new_v4().into();
    let other = Uuid::new_v4().into();
    h.commands(vec![create(t), create(other)]).await?;
    let path = format!("topics/{t}/files/folder/notes%20one");
    for (rev, body) in [("1", vec![0, 255, 3]), ("2", vec![1, 0])] {
        let response = h
            .request(Method::PUT, &path)
            .body(body.clone())
            .send()
            .await?
            .error_for_status()?;
        assert_eq!(response.headers()["x-meep-revision"], rev);
        assert_eq!(response.bytes().await?.as_ref(), body);
    }
    assert_eq!(
        h.request(Method::PUT, &path)
            .header("x-meep-base-revision", "10")
            .body("rejected")
            .send()
            .await?
            .status(),
        StatusCode::BAD_REQUEST
    );
    let missing = format!("topics/{}/files/notes", Uuid::new_v4());
    assert_eq!(
        h.request(Method::PUT, &missing)
            .body("rejected")
            .send()
            .await?
            .status(),
        StatusCode::NOT_FOUND
    );
    let old = h
        .request(Method::GET, &format!("{path}?revision=1"))
        .send()
        .await?
        .error_for_status()?;
    assert_eq!(old.headers()["x-meep-revision"], "1");
    assert_eq!(old.bytes().await?.as_ref(), [0, 255, 3]);
    assert_eq!(
        h.request(Method::GET, &path)
            .send()
            .await?
            .bytes()
            .await?
            .as_ref(),
        [1, 0]
    );
    assert_eq!(
        h.request(
            Method::GET,
            &format!("topics/{other}/files/folder/notes%20one")
        )
        .send()
        .await?
        .status(),
        404
    );
    h.close().await?;
    Ok(())
}

#[tokio::test]
async fn webhook_authentication_and_topic_grants_survive_partial_credential_updates() -> Result<()>
{
    let h = Host::new().await?;
    let t = Uuid::new_v4().into();
    let ungranted = Uuid::new_v4().into();
    let watch = Watch {
        id: Uuid::new_v4().into(),
        connection: "builds".into(),
        kind: "project".into(),
        key: "desktop".into(),
        label: "Desktop".into(),
    };
    for topic in [t, ungranted] {
        h.commands(vec![
            create(topic),
            envelope(
                topic,
                Command::SetWatch {
                    watches: vec![watch.clone()],
                },
            ),
        ])
        .await?;
    }
    let config = json!({"watch":watch,"auth":{"kind":"shared_secret","header":"x-build-token"},"mapping":{"id":"/id","author":"/actor","timestamp":"/at","text":"/text"}});
    let mut grant = json!({"kind":"webhook","label":"Builds","account":null,"grants":[t,t],
        "secrets":{"webhook_secret":"private-build-key","config":config.to_string()}});
    // A credential store outage must be retryable with the same registration.
    let secrets = h.dir.path().join("secrets");
    let backup = h.dir.path().join("saved-secrets");
    std::fs::rename(&secrets, &backup)?;
    let failed = h
        .request(Method::PUT, "connections/builds")
        .json(&grant)
        .send()
        .await?;
    assert_eq!(failed.status(), 500);
    let error: meep_wire::ApiError = failed.json().await?;
    assert_eq!(error.code, "internal");
    assert!(!error.message.contains("private-build-key"));
    std::fs::rename(backup, secrets)?;
    let first = h
        .request(Method::PUT, "connections/builds")
        .json(&grant)
        .send()
        .await?
        .error_for_status()?
        .json::<ConnectionInfo>()
        .await?;
    assert_eq!(first.grants, [t]);
    grant["label"] = json!("Build service");
    grant["secrets"] = json!({});
    let response = h
        .request(Method::PUT, "connections/builds")
        .json(&grant)
        .send()
        .await?
        .error_for_status()?
        .text()
        .await?;
    assert!(!response.contains("private-build-key"));
    let h = Host::open(h.close().await?).await?;
    let public = h
        .request(Method::GET, "connections")
        .send()
        .await?
        .text()
        .await?;
    assert!(!public.contains("private-build-key") && !public.contains("secrets"));
    assert_eq!(
        serde_json::from_str::<Connections>(&public)?.connections[0].label,
        "Build service"
    );
    let payload = json!({"id":"build-1","actor":"CI","at":Utc::now(),"text":"Please approve the desktop release"});
    for key in ["wrong", h.token.as_str()] {
        assert_eq!(
            h.request(Method::POST, "ingest/builds")
                .header("x-build-token", key)
                .json(&payload)
                .send()
                .await?
                .status(),
            401
        );
    }
    h.commands(vec![envelope(t, Command::SetWatch { watches: vec![] })])
        .await?;
    h.request(Method::POST, "ingest/builds")
        .header("x-build-token", "private-build-key")
        .json(&payload)
        .send()
        .await?
        .error_for_status()?;
    let accounts = h
        .request(Method::GET, "connections")
        .send()
        .await?
        .json::<Connections>()
        .await?;
    assert_eq!(accounts.connections[0].unrouted, 1);
    h.commands(vec![envelope(
        t,
        Command::SetWatch {
            watches: vec![watch],
        },
    )])
    .await?;
    for _ in 0..2 {
        assert_eq!(
            h.client
                .post(format!("{}/v1/ingest/builds", h.origin))
                .header("x-build-token", "private-build-key")
                .json(&payload)
                .send()
                .await?
                .status(),
            204
        );
    }
    assert!(h.server.engine().topic(ungranted)?.threads.is_empty());
    assert_eq!(h.server.engine().source_observations(t, 10)?.len(), 1);
    h.server.engine().sort_pending(t).await?;
    let needs = h
        .request(Method::GET, "needs-you")
        .send()
        .await?
        .json::<NeedsYou>()
        .await?;
    assert!(needs.items.is_empty(), "{:?}", needs.items);
    assert_eq!(
        h.server.engine().topic(t)?.topic.fallback.observations[0].outcome,
        meep_topic::ObservationOutcome::Finished {
            reason: "Recorded source observation".into(),
        }
    );
    let signed_out = h
        .request(Method::DELETE, "connections/builds/credentials")
        .send()
        .await?
        .error_for_status()?
        .json::<ConnectionInfo>()
        .await?;
    assert_eq!(signed_out.health, "signed_out");
    let h = Host::open(h.close().await?).await?;
    let stored = h
        .request(Method::GET, "connections")
        .send()
        .await?
        .json::<Connections>()
        .await?;
    assert_eq!(stored.connections[0].health, "signed_out");
    assert!(
        !h.request(Method::POST, "ingest/builds")
            .header("x-build-token", "private-build-key")
            .json(&payload)
            .send()
            .await?
            .status()
            .is_success()
    );
    h.close().await?;
    Ok(())
}
#[tokio::test]
async fn only_the_current_routine_secret_can_change_its_bound_topic() -> Result<()> {
    let h = Host::new().await?;
    let t: TopicId = Uuid::new_v4().into();
    h.commands(vec![create(t)]).await?;
    let binding = RoutineBinding {
        watches: vec![],
        id: "weekly".into(),
        name: "Weekly".into(),
        trigger: "Manual".into(),
        backend: "posthog".into(),
        external_id: Uuid::new_v4().to_string(),
    };
    let secret = h.server.engine().bind_routine(t, binding).await?;
    let path = format!("routines/{t}/weekly/callback");
    for key in ["wrong", h.token.as_str()] {
        assert_eq!(
            h.request(Method::POST, &path)
                .header("Idempotency-Key", Uuid::new_v4().to_string())
                .json(&json!({"secret":key,"op":{"kind":"AddFact","text":"bad"}}))
                .send()
                .await?
                .status(),
            401
        );
    }
    let effect = Uuid::new_v4().to_string();
    let invoke = || {
        h.client
            .post(format!("{}/v1/{path}", h.origin))
            .header("Idempotency-Key", &effect)
    };
    invoke()
        .json(&json!({"secret":secret,"op":{"kind":"AddFact","text":"Weekly report delivered"}}))
        .send()
        .await?
        .error_for_status()?;
    let result = invoke()
        .json(&json!({"secret":secret,"op":{"kind":"AddFact","text":"Weekly report delivered"}}))
        .send()
        .await?
        .error_for_status()?
        .json::<CallbackResult>()
        .await?;
    let snapshot = h
        .request(Method::GET, &format!("topics/{t}"))
        .send()
        .await?
        .text()
        .await?;
    assert!(!snapshot.contains(&secret));
    let saved = serde_json::from_str::<TopicSnapshot>(&snapshot)?;
    assert_eq!(saved.revision, result.revision);
    assert_eq!(saved.state.topic.facts.len(), 1);
    assert_eq!(saved.state.topic.facts[0].text, "Weekly report delivered");
    h.close().await?;
    Ok(())
}

#[tokio::test]
async fn failed_oauth_refresh_marks_the_account_expired_and_reports_a_problem_without_token_details()
-> Result<()> {
    use axum::{
        Json, Router,
        routing::{get, post},
    };
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    let h = Host::new().await?;
    let t = Uuid::new_v4().into();
    h.commands(vec![create(t)]).await?;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let origin = format!("http://{}", listener.local_addr()?);
    let root = origin.clone();
    let count = Arc::new(AtomicUsize::new(0));
    let calls = count.clone();
    let provider=Router::new()
        .route("/api/projects/7/tasks/",get(||async{StatusCode::UNAUTHORIZED}))
        .route("/.well-known/oauth-authorization-server",get(move ||async move {Json(json!({"issuer":root,"authorization_endpoint":format!("{root}/authorize"),"token_endpoint":format!("{root}/token")}))}))
        .route("/token",post(move |body:String|async move {
            assert!(body.contains("refresh_token=old-refresh") && body.contains("client_id=desktop-client"));
            calls.fetch_add(1,Ordering::SeqCst);
            (StatusCode::BAD_REQUEST,Json(json!({"error":"invalid_grant","error_description":"old-refresh"})))
        }));
    let mock = tokio::spawn(async move { axum::serve(listener, provider).await });
    let grant = json!({"kind":"posthog","label":"Analytics","account":"Work","secrets":{
        "access_token":"old-access","refresh_token":"old-refresh","region":origin,"config":json!({"mcp_endpoint":format!("{origin}/mcp")}).to_string(),"project_id":"7","client_id":"desktop-client"
    },"grants":[t]});
    h.request(Method::PUT, "connections/analytics")
        .json(&grant)
        .send()
        .await?
        .error_for_status()?;
    let info = tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let mut list = h
                .request(Method::GET, "connections")
                .send()
                .await?
                .json::<Connections>()
                .await?;
            if let Some(c) = list.connections.pop().filter(|c| c.health == "expired") {
                break anyhow::Ok(c);
            }
            tokio::time::sleep(std::time::Duration::from_millis(25)).await;
        }
    })
    .await??;
    assert!(info.summary.contains("Sign in") && !info.summary.contains("old-refresh"));
    assert_eq!(count.load(Ordering::SeqCst), 1);
    assert!(
        matches!(h.request(Method::GET,"needs-you").send().await?.json::<NeedsYou>().await?.items.as_slice(),[NeedsYouItem::Problem{topics,..}] if topics==&[t])
    );
    assert!(
        !h.request(Method::GET, "health")
            .send()
            .await?
            .json::<ServerHealth>()
            .await?
            .posthog
    );
    h.close().await?;
    mock.abort();
    Ok(())
}

#[tokio::test]
async fn refreshed_posthog_credentials_drive_granted_tasks_and_watches_and_survive_restart()
-> Result<()> {
    use axum::{
        Json, Router,
        http::HeaderMap,
        routing::{get, post},
    };
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    let h = Host::new().await?;
    let t = Uuid::new_v4().into();
    let other = Uuid::new_v4().into();
    let task = Uuid::new_v4();
    let run = Uuid::new_v4();
    h.commands(vec![create(t), create(other)]).await?;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let origin = format!("http://{}", listener.local_addr()?);
    let root = origin.clone();
    let calls = Arc::new(AtomicUsize::new(0));
    let refresh = calls.clone();
    let task_path = format!("/api/projects/7/tasks/{task}");
    let board_task = Uuid::new_v4().into();
    let resumed = Uuid::new_v4();
    let provider=Router::new()
        .route("/.well-known/oauth-authorization-server",get(move||async move {
            Json(json!({"issuer":root,"authorization_endpoint":format!("{root}/authorize"),"token_endpoint":format!("{root}/token")}))
        }))
        .route("/token",post(move|body:String|async move{
            assert!(body.contains("refresh_token=old-refresh"));
            refresh.fetch_add(1,Ordering::SeqCst);
            Json(json!({"access_token":"renewed","refresh_token":"rotated","token_type":"bearer"}))
        }))
        .route("/api/projects/7/tasks/",get(|h:HeaderMap|async move {
            if h["authorization"]=="Bearer renewed" {StatusCode::OK} else {StatusCode::UNAUTHORIZED}
        }).post(move |h:HeaderMap,Json(body):Json<serde_json::Value>|async move{
            assert_eq!(h["authorization"],"Bearer renewed");
            let prompt=body["description"].as_str().expect("agent context");
            // The topic's setup conversation is covered by tests/topic_mcp.rs.
            if prompt.contains(meep_engine::SETUP_TITLE) {
                return Json(json!({"id":Uuid::new_v4()}));
            }
            assert!(prompt.contains("Inspect signups") && prompt.contains("Use the signup report"));
            assert!(!prompt.contains("Unrelated"));
            Json(json!({"id":task}))
        }))
        .route("/api/projects/7/tasks/models/",get(||async {Json(json!({"models":[{"model":"claude-test","display_name":"Claude","runtime_adapter":"claude"},{"model":"codex-test","display_name":"Codex","runtime_adapter":"codex","supported_efforts":["high"]}]}))}))
        .route("/api/projects/7/tasks/@me/config/",get(||async {Json(json!({"resolved_ai_run_defaults":{"runtime":"acp","runtime_adapter":"claude","model":"claude-test","reasoning_effort":null}}))}))
        .route(&format!("{task_path}/run/"),post(move|Json(body):Json<serde_json::Value>|async move{
            let next=if body.get("resume_from_run_id").is_some(){assert_eq!(body["resume_from_run_id"],run.to_string()); assert_eq!(body["pending_user_message"],"Investigate further");assert_eq!(body["model"],"claude-test");assert_eq!(body["runtime_adapter"],"claude");resumed}else{assert_eq!(body["model"],"codex-test");assert_eq!(body["runtime_adapter"],"codex");assert_eq!(body["reasoning_effort"],"high");assert_eq!(body["codex_model_access"],"own-subscription");run};
            Json(json!({"run":{"id":next,"status":"queued"}}))
        }))
        .route(&format!("{task_path}/runs/{resumed}/"),get(move||async move{Json(json!({"id":resumed,"status":"queued"}))}))
        .route(&format!("{task_path}/runs/{resumed}/command/"),post(|Json(body):Json<serde_json::Value>|async move{
            assert_eq!(body["method"],"user_message");assert_eq!(body["params"]["content"],"Focus on this week");Json(json!({"result":{"queued":true}}))
        }))
        .route(&format!("{task_path}/runs/{run}/"),get(move||async move {Json(json!({"id":run,"status":"completed"}))}))
        .route(&format!("{task_path}/runs/{run}/session_logs/"),get(||async {
            Json(json!([{"notification":{"method":"session/update","params":{"update":{"sessionUpdate":"agent_message","content":{"type":"text","text":"Checked signups"}}}}}]))
        }))
        .route("/mcp",post(|h:HeaderMap,Json(body):Json<serde_json::Value>|async move{
            use axum::response::IntoResponse;
            assert_eq!(h["authorization"],"Bearer renewed");
            let result=match body["method"].as_str() {
                Some("initialize")=>json!({"protocolVersion":"2025-06-18","capabilities":{"tools":{}}}),
                Some("notifications/initialized")=>return StatusCode::ACCEPTED.into_response(),
                Some("tools/list")=>json!({"tools":[{"name":"execute-sql","inputSchema":{"type":"object"}}]}),
                Some("tools/call")=>{
                    assert_eq!(body["params"]["name"],"execute-sql");
                    json!({"content":[],"structuredContent":{"results":[[3]]},"isError":false})
                }
                _=>return StatusCode::BAD_REQUEST.into_response()
            };
            Json(json!({"jsonrpc":"2.0","id":body["id"],"result":result})).into_response()
        }));
    let mock = tokio::spawn(async move { axum::serve(listener, provider).await });
    let grant = json!({"kind":"posthog","label":"Analytics","account":"Work","secrets":{
        "access_token":"old","refresh_token":"old-refresh","region":origin,"config":json!({"mcp_endpoint":format!("{origin}/mcp")}).to_string(),"project_id":"7","client_id":"desktop-client","poll_interval_seconds":"1"
    },"grants":[t]});
    h.request(Method::PUT, "connections/work")
        .json(&grant)
        .send()
        .await?
        .error_for_status()?;
    let watch = Watch {
        id: Uuid::new_v4().into(),
        connection: "work".into(),
        kind: "event".into(),
        key: "sign_up".into(),
        label: "Signups".into(),
    };
    h.commands(vec![
        envelope(
            t,
            Command::AddConfiguredTask {
                untitled: false,
                start: true,
                model: Some("codex-test".into()),
                reasoning_effort: Some("high".into()),
                billing: Some("own-subscription".into()),
                instructions: Some("Use the signup report".into()),
                id: board_task,
                title: "Inspect signups".into(),
            },
        ),
        envelope(
            other,
            Command::AddTask {
                id: Uuid::new_v4().into(),
                title: "Unrelated".into(),
            },
        ),
        envelope(
            t,
            Command::SetWatch {
                watches: vec![watch],
            },
        ),
    ])
    .await?;
    tokio::time::timeout(std::time::Duration::from_secs(9), async {
        loop {
            let s = h
                .request(Method::GET, &format!("topics/{t}"))
                .send()
                .await?
                .json::<TopicSnapshot>()
                .await?;
            if s.state
                .tasks
                .iter()
                .any(|t| t.result.as_deref() == Some("Checked signups"))
                && !s.state.topic.fallback.observations.is_empty()
            {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(30)).await;
        }
        anyhow::Ok(())
    })
    .await??;
    assert_eq!(
        h.server.engine().topic(other)?.tasks[0].column,
        meep_topic::Column::Todo
    );
    let h = Host::open(h.close().await?).await?;
    assert!(
        h.request(Method::GET, "health")
            .send()
            .await?
            .json::<ServerHealth>()
            .await?
            .posthog
    );
    let choice = h
        .request(Method::PUT, &format!("topics/{t}/models"))
        .json(&json!({"model":"codex-test","billing":"own-subscription"}))
        .send()
        .await?
        .error_for_status()?
        .json::<meep_wire::ChatModels>()
        .await?;
    assert_eq!(choice.billing.as_deref(), Some("own-subscription"));
    assert_eq!(choice.selected.as_deref(), Some("codex-test"));
    let path = format!("topics/{t}/tasks/{board_task}");
    let transcript = h
        .request(Method::GET, &format!("{path}/conversation"))
        .send()
        .await?
        .error_for_status()?
        .json::<meep_wire::TaskConversation>()
        .await?;
    assert_eq!(transcript.status, "completed");
    assert_eq!(transcript.messages.last().unwrap().text, "Checked signups");
    for message in [
        json!({"text":"Investigate further","model":"claude-test"}),
        json!({"text":"Focus on this week"}),
    ] {
        h.request(Method::POST, &format!("{path}/messages"))
            .json(&message)
            .send()
            .await?
            .error_for_status()?;
    }
    assert!(
        h.server
            .engine()
            .topic(t)?
            .tasks
            .iter()
            .find(|t| t.id == board_task)
            .unwrap()
            .log
            .iter()
            .any(|l| l.text == "Focus on this week")
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    let final_state = h.server.engine().topic(t)?;
    assert_eq!(
        not_setup(&final_state.threads).count(),
        0,
        "{:?}",
        final_state.threads
    );
    h.close().await?;
    mock.abort();
    Ok(())
}

#[tokio::test]
async fn restarting_resumes_remote_routine_status_polling_without_dispatching_twice() -> Result<()>
{
    use axum::{
        Json, Router,
        http::HeaderMap,
        routing::{get, post},
    };
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    let h = Host::new().await?;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let origin = format!("http://{}", listener.local_addr()?);
    let starts = Arc::new(AtomicUsize::default());
    let dispatch = starts.clone();
    let flow = Uuid::new_v4();
    let invocation = Uuid::new_v4();
    let key = Uuid::new_v4();
    let prefix = format!("/api/projects/7/hog_flows/{flow}");
    let checks = Arc::new(AtomicUsize::default());
    let poll = checks.clone();
    let provider = Router::new()
        .route("/api/projects/7/tasks/", get(|| async { StatusCode::OK }))
        .route(
            &format!("{prefix}/run/"),
            post(
                move |h: HeaderMap, Json(v): Json<serde_json::Value>| async move {
                    assert_eq!(h["idempotency-key"], key.to_string());
                    assert_eq!(h["authorization"], "Bearer current");
                    assert_eq!(v["variables"], json!({"week":5}));
                    dispatch.fetch_add(1, Ordering::SeqCst);
                    Json(json!({"invocation_id":invocation,"status":"queued"}))
                },
            ),
        )
        .route(
            &format!("{prefix}/invocation_results/{invocation}/"),
            get(move || async move {
                poll.fetch_add(1, Ordering::SeqCst);
                Json(json!({"invocation_id":invocation,"status":"completed","duration_ms":10}))
            }),
        )
        .route(
            &format!("{prefix}/invocation_results/"),
            get(|| async { Json(json!([])) }),
        );
    let mock = tokio::spawn(async move { axum::serve(listener, provider).await });
    let t = Uuid::new_v4().into();
    h.commands(vec![create(t)]).await?;
    let grant = json!({"kind":"posthog","label":"Analytics","secrets":{"access_token":"current","region":origin,"config":json!({"mcp_endpoint":format!("{origin}/mcp")}).to_string(),"project_id":"7"},"grants":[t]});
    h.request(Method::PUT, "connections/work")
        .json(&grant)
        .send()
        .await?
        .error_for_status()?;
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        while !h
            .request(Method::GET, "health")
            .send()
            .await?
            .json::<ServerHealth>()
            .await?
            .posthog
        {
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        anyhow::Ok(())
    })
    .await??;
    let routine = RoutineBinding {
        watches: vec![],
        id: "weekly".into(),
        name: "Weekly".into(),
        trigger: "Manual".into(),
        backend: "posthog".into(),
        external_id: flow.to_string(),
    };
    let mut start = envelope(
        t,
        Command::StartRoutine {
            routine: "weekly".into(),
            variables: serde_json::from_value(json!({"week":5}))?,
        },
    );
    start.id = key.into();
    let results = h
        .commands(vec![
            envelope(t, Command::SetRoutine { routine }),
            start.clone(),
        ])
        .await?;
    assert!(
        results
            .results
            .iter()
            .all(|r| matches!(r, CommandResult::Applied { .. }))
    );
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        while starts.load(Ordering::SeqCst) == 0 {
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
        h.server
            .engine()
            .start_routine(t, "weekly", serde_json::from_value(json!({"week":5}))?, key)
            .await?;
        anyhow::Ok(())
    })
    .await??;
    let h = Host::open(h.close().await?).await?;
    h.commands(vec![start]).await?;
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let receipt = h
                .server
                .engine()
                .start_routine(t, "weekly", serde_json::from_value(json!({"week":5}))?, key)
                .await?;
            if receipt.status == "completed" {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        anyhow::Ok(())
    })
    .await??;
    assert_eq!(starts.load(Ordering::SeqCst), 1);
    assert!(checks.load(Ordering::SeqCst) > 0);
    h.close().await?;
    mock.abort();
    Ok(())
}

#[tokio::test]
async fn replying_to_another_topic_delivers_once_per_command_across_restart() -> Result<()> {
    let h = Host::new().await?;
    let (a, b) = (TopicId(Uuid::new_v4()), TopicId(Uuid::new_v4()));
    h.commands(vec![create(a), create(b)]).await?;
    h.server
        .engine()
        .send_to_topic(a, b, "Which version?", 1)
        .await?;
    let thread = h.server.engine().topic(b)?.threads[0].id;
    let reply = || {
        envelope(
            b,
            Command::Reply {
                thread,
                text: "Version two".into(),
            },
        )
    };
    let first = reply();
    h.commands(vec![first.clone(), first.clone()]).await?;
    let h = Host::open(h.close().await?).await?;
    h.commands(vec![first, reply()]).await?;
    let messages: Vec<_> = h
        .server
        .engine()
        .topic(a)?
        .threads
        .into_iter()
        .flat_map(|t| t.messages)
        .collect();
    assert_eq!(messages.len(), 2);
    assert!(
        messages
            .iter()
            .all(|m| m.text == "Version two"
                && m.reply_target() == Some(meep_topic::Source::Topic(b)))
    );
    h.close().await?;
    Ok(())
}

#[tokio::test]
async fn startup_completes_a_reply_interrupted_on_either_side_of_the_receivers_commit() -> Result<()>
{
    use meep_connectors::{StateStore, StoreState};
    for already_delivered in [false, true] {
        let h = Host::new().await?;
        let (from, to) = (TopicId(Uuid::new_v4()), TopicId(Uuid::new_v4()));
        h.commands(vec![create(from), create(to)]).await?;
        let id = Uuid::new_v4();
        if already_delivered {
            h.server
                .engine()
                .send_to_topic(from, to, "Ready", 1)
                .await?;
        }
        let dir = h.close().await?;
        let journal = StoreState::new(meep_store::Connection::open(
            dir.path().join("checkpoints.sqlite"),
        )?)?;
        journal.commit(
            "\0topics/reply-in-flight",
            None,
            &json!({"command":id,"from":from,"to":to,"text":"Ready","previous":[]}),
        )?;
        drop(journal);
        let h = Host::open(dir).await?;
        let received: Vec<_> = h
            .server
            .engine()
            .topic(to)?
            .threads
            .into_iter()
            .flat_map(|t| t.messages)
            .collect();
        assert_eq!(received.len(), 1);
        assert_eq!(received[0].text, "Ready");
        h.close().await?;
    }
    Ok(())
}

#[tokio::test]
async fn chat_creates_a_linked_posthog_task_without_a_gateway_call() -> Result<()> {
    let h = Host::new().await?;
    let t = Uuid::new_v4().into();
    h.commands(vec![create(t)]).await?;
    h.server.engine().chat(t, "Investigate the release").await?;
    h.server.engine().tick_topic(t).await?;
    let state = h.server.engine().topic(t)?;
    assert_eq!(state.usage.today(Utc::now()).system_one, 0);
    let thread = not_setup(&state.threads).next().context("chat thread")?;
    assert!(
        state
            .tasks
            .iter()
            .any(|task| task.from_thread == Some(thread.id))
    );
    h.close().await?;
    Ok(())
}

#[tokio::test]
async fn oversized_command_batches_fail_before_the_first_mutation() -> Result<()> {
    let h = Host::new().await?;
    let command = create(Uuid::new_v4().into());
    let batch = CommandBatch {
        commands: vec![command; 65],
    };
    let response = h
        .request(Method::POST, "commands")
        .json(&batch)
        .send()
        .await?;
    assert!(response.status().is_client_error());
    assert!(h.server.engine().topics().is_empty());
    h.close().await?;
    Ok(())
}

#[tokio::test]
async fn replaying_a_file_write_after_an_intervening_edit_returns_its_original_revision()
-> Result<()> {
    let h = Host::new().await?;
    let t = Uuid::new_v4().into();
    h.commands(vec![create(t)]).await?;
    let path = format!("topics/{t}/files/test");
    let key = Uuid::new_v4().to_string();
    for (key, body, rev) in [
        (&key, "old", "1"),
        (&Uuid::new_v4().to_string(), "new", "2"),
        (&key, "old", "1"),
    ] {
        let r = h
            .request(Method::PUT, &path)
            .header("Idempotency-Key", key)
            .body(body)
            .send()
            .await?
            .error_for_status()?;
        assert_eq!(r.headers()["x-meep-revision"], rev);
    }
    let conflict = h
        .request(Method::PUT, &path)
        .header("Idempotency-Key", &key)
        .body("different")
        .send()
        .await?;
    assert_eq!(conflict.status(), StatusCode::CONFLICT);
    assert_eq!(
        conflict.json::<ApiError>().await?.code,
        "file_operation_conflict"
    );
    assert_eq!(h.server.engine().blobs().history(t, "test")?.len(), 2);
    h.close().await?;
    Ok(())
}

#[tokio::test]
async fn file_lists_can_be_read_in_bounded_pages_without_skipping_entries() -> Result<()> {
    let h = Host::new().await?;
    let t = Uuid::new_v4().into();
    h.commands(vec![create(t)]).await?;
    for n in ["a", "b", "c"] {
        h.server.engine().blobs().put(t, n, b"x")?;
    }
    let path = format!("topics/{t}/files?limit=2");
    let page = h
        .request(Method::GET, &path)
        .send()
        .await?
        .error_for_status()?;
    assert_eq!(
        page.headers()
            .get("x-meep-next-offset")
            .and_then(|v| v.to_str().ok()),
        Some("2")
    );
    assert_eq!(page.json::<Vec<String>>().await?, ["a", "b"]);
    assert_eq!(
        h.request(Method::GET, &format!("{path}&offset=2"))
            .send()
            .await?
            .json::<Vec<String>>()
            .await?,
        ["c"]
    );
    h.close().await?;
    Ok(())
}

#[tokio::test]
async fn replies_use_the_granted_source_workflow_and_replay_never_dispatches_twice() -> Result<()> {
    use axum::{
        Json, Router,
        http::HeaderMap,
        routing::{get, post},
    };
    use std::sync::{Arc, Mutex};
    let h = Host::open_with_base(tempfile::tempdir()?, Some("https://meep.example.test")).await?;
    let (topic, _) = h.server.engine().create_topic("Support", "").await?;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let origin = format!("http://{}", listener.local_addr()?);
    let flow = Uuid::new_v4();
    let sort_flow = Uuid::new_v4();
    let records = Arc::new(Mutex::new(vec![]));
    let calls = records.clone();
    let api = Router::new()
        .route(
            &format!("/api/projects/7/hog_flows/{sort_flow}/run/"),
            post(|| async { Json(json!({"invocation_id":Uuid::new_v4(),"status":"queued"})) }),
        )
        .route("/api/projects/7/tasks/", get(|| async { StatusCode::OK }))
        .route(
            &format!("/api/projects/7/hog_flows/{flow}/run/"),
            post(
                move |headers: HeaderMap, Json(body): Json<serde_json::Value>| async move {
                    calls.lock().expect("fixture").push((
                        headers["idempotency-key"].to_str().expect("key").to_owned(),
                        body,
                    ));
                    Json(json!({"invocation_id":Uuid::new_v4(),"status":"queued"}))
                },
            ),
        );
    let upstream = tokio::spawn(async move { axum::serve(listener, api).await });
    for (id, grant) in [
        (
            "work",
            json!({"kind":"posthog","label":"Work","grants":[topic],"secrets":{"access_token":"fixture","region":origin,"project_id":"7"}}),
        ),
        (
            "build",
            json!({"kind":"webhook","label":"Build","grants":[topic],"secrets":{"webhook_secret":"fixture-hook","reply_workflow":flow.to_string(),"reply_account":"work"}}),
        ),
    ] {
        h.request(Method::PUT, &format!("connections/{id}"))
            .json(&grant)
            .send()
            .await?
            .error_for_status()?;
    }
    wait_for_posthog(&h).await?;
    let binding = RoutineBinding {
        id: "source-sort".into(),
        name: "Sort".into(),
        trigger: "Source event".into(),
        backend: "posthog".into(),
        external_id: sort_flow.to_string(),
        watches: vec![Watch {
            id: Uuid::new_v4().into(),
            connection: "build".into(),
            kind: "channel".into(),
            key: "builds".into(),
            label: "Builds".into(),
        }],
    };
    let secret = h
        .server
        .engine()
        .bind_routine(topic, binding.clone())
        .await?;
    h.request(Method::POST,"ingest/build").header("x-meep-secret","fixture-hook").json(&json!({"connection":"build","kind":"channel","channel":"builds","external_id":"42","thread_hint":"42","author":"CI","at":Utc::now(),"text":"Ready?","attributes":null})).send().await?.error_for_status()?;
    let observation = serde_json::from_value(
        h.server.engine().source_observations(topic, 1)?[0]["observation"].clone(),
    )?;
    h.server
        .engine()
        .routine_callback_once(
            topic,
            &binding.id,
            &secret,
            Uuid::new_v4(),
            meep_engine::RoutineOp::Classified {
                observation,
                category: "inbox".into(),
            },
        )
        .await?;
    let thread = not_setup(&h.server.engine().topic(topic)?.threads)
        .next()
        .context("source thread")?
        .id;
    let reply = envelope(
        topic,
        Command::Reply {
            thread,
            text: "Ready".into(),
        },
    );
    let outcome = h.commands(vec![reply.clone(), reply.clone()]).await?;
    assert_eq!(
        records.lock().expect("fixture").len(),
        1,
        "{outcome:?} {:?}",
        h.server.engine().topic(topic)?.activity
    );
    assert_eq!(
        records.lock().expect("fixture").as_slice(),
        [(
            reply.id.to_string(),
            json!({"variables":{"source":"build","channel":"builds","external_id":"42","text":"Ready"}})
        )]
    );
    h.close().await?;
    upstream.abort();
    Ok(())
}

#[tokio::test]
async fn shutdown_finishes_a_token_rotation_after_the_issuer_has_accepted_it() -> Result<()> {
    use axum::{
        Json, Router,
        http::HeaderMap,
        routing::{get, post},
    };
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    let h = Host::new().await?;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let origin = format!("http://{}", listener.local_addr()?);
    let issuer = origin.clone();
    let calls = Arc::new(AtomicUsize::new(0));
    let requested = Arc::new(tokio::sync::Notify::new());
    let release = Arc::new(tokio::sync::Notify::new());
    let api=Router::new()
        .route("/api/projects/7/tasks/",get(|headers:HeaderMap| async move {
            if headers["authorization"]=="Bearer rotated" {StatusCode::OK} else {StatusCode::UNAUTHORIZED}
        }))
        .route("/.well-known/oauth-authorization-server",get(move||async move {
            Json(json!({"issuer":issuer,"authorization_endpoint":format!("{issuer}/authorize"),"token_endpoint":format!("{issuer}/token")}))
        }))
        .route("/token",post({
            let first=requested.clone(); let wait=release.clone(); let calls=calls.clone();
            move || { let first=first.clone(); let wait=wait.clone(); let calls=calls.clone(); async move {
                if calls.fetch_add(1,Ordering::SeqCst)==0 {first.notify_one();wait.notified().await;}
                Json(json!({"access_token":"rotated","refresh_token":"new-refresh","token_type":"bearer"}))
            }}
        }));
    let upstream = tokio::spawn(async move { axum::serve(listener, api).await });
    h.request(Method::PUT,"connections/work").json(&json!({"kind":"posthog","label":"Work","grants":[],"secrets":{"region":origin,"project_id":"7","access_token":"initial","refresh_token":"old-refresh","client_id":"desktop"}})).send().await?.error_for_status()?;
    tokio::time::timeout(std::time::Duration::from_secs(5), requested.notified()).await?;
    let close = h.close();
    tokio::pin!(close);
    assert!(
        tokio::time::timeout(std::time::Duration::from_millis(150), &mut close)
            .await
            .is_err(),
        "server returned while the accepted refresh was outstanding"
    );
    release.notify_one();
    let h = Host::open(close.await?).await?;
    wait_for_posthog(&h).await?;
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    h.close().await?;
    upstream.abort();
    Ok(())
}

#[tokio::test]
async fn an_oversized_mapped_webhook_applies_none_of_its_events() -> Result<()> {
    let h = Host::new().await?;
    let (topic, _) = h.server.engine().create_topic("Builds", "").await?;
    let watch = Watch {
        id: Uuid::new_v4().into(),
        connection: "ci".into(),
        kind: "channel".into(),
        key: "release".into(),
        label: "Release".into(),
    };
    h.server
        .engine()
        .set_watch(topic, vec![watch.clone()])
        .await?;
    let config = json!({"watch":watch,"mapping":{"id":"/id","author":"/author","timestamp":"/at","text":"/text"}});
    h.request(Method::PUT, "connections/ci").json(&json!({"kind":"webhook","label":"CI","grants":[topic],"secrets":{"webhook_secret":"fixture","config":config.to_string()}})).send().await?.error_for_status()?;
    let events: Vec<_> = (0..65)
        .map(|i| json!({"id":i.to_string(),"author":"CI","at":Utc::now(),"text":"update"}))
        .collect();
    let response = h
        .request(Method::POST, "ingest/ci")
        .header("x-meep-secret", "fixture")
        .json(&events)
        .send()
        .await?;
    assert_eq!(response.status(), StatusCode::PAYLOAD_TOO_LARGE);
    assert!(h.server.engine().topic(topic)?.threads.is_empty());
    h.close().await?;
    Ok(())
}

#[tokio::test]
async fn a_retryable_command_does_not_block_an_independent_edit() -> Result<()> {
    let h = Host::new().await?;
    let topic = Uuid::new_v4().into();
    h.commands(vec![create(topic)]).await?;
    let other = Uuid::new_v4().into();
    h.commands(vec![create(other)]).await?;
    let batch = CommandBatch {
        commands: ["first", "second"]
            .map(|mission| {
                envelope(
                    if mission == "first" { topic } else { other },
                    Command::SetMission {
                        mission: mission.into(),
                    },
                )
            })
            .to_vec(),
    };
    let db = meep_store::Connection::open(h.dir.path().join("topics.sqlite"))?;
    db.execute_batch(&format!("CREATE TRIGGER transient_failure BEFORE INSERT ON records
        WHEN new.kind='engine/command' AND new.id='{}' BEGIN SELECT RAISE(ABORT,'interrupted'); END;", batch.commands[0].id))?;
    let response = h
        .request(Method::POST, "commands")
        .json(&batch)
        .send()
        .await?;
    assert!(matches!(
        response
            .error_for_status()?
            .json::<CommandResults>()
            .await?
            .results
            .as_slice(),
        [CommandResult::Retry { .. }, CommandResult::Applied { .. }]
    ));
    assert_eq!(h.server.engine().topic(other)?.topic.mission, "second");
    assert_eq!(
        h.server.engine().topic(topic)?.topic.mission,
        "Track releases"
    );
    db.execute_batch("DROP TRIGGER transient_failure")?;
    h.commands(batch.commands).await?;
    assert_eq!(h.server.engine().topic(topic)?.topic.mission, "first");
    h.close().await?;
    Ok(())
}

/// Threads other than the setup conversation a granted topic opens.
fn not_setup(threads: &[meep_topic::Thread]) -> impl Iterator<Item = &meep_topic::Thread> {
    threads
        .iter()
        .filter(|t| t.messages.first().is_none_or(|m| m.author != "Meep"))
}

#[tokio::test]
async fn sign_in_after_sign_out_restores_only_matching_topic_grants() -> Result<()> {
    let mut h = Host::new().await?;
    let topic = Uuid::new_v4().into();
    h.commands(vec![create(topic)]).await?;
    let user = Uuid::new_v4();
    let upstream = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let region = format!("http://{}", upstream.local_addr()?);
    let provider = axum::Router::new().route(
        "/api/users/@me/",
        axum::routing::get(move || async move { axum::Json(json!({"uuid":user})) }),
    );
    let serving = tokio::spawn(async move { axum::serve(upstream, provider).await });
    let grant = json!({"kind":"posthog","label":"PostHog","grants":[topic],
        "secrets":{"access_token":"fixture","region":region,"project_id":"7","user_uuid":user}});
    for (field, value, restore, legacy) in [
        ("access_token", "fresh-token".to_owned(), true, true),
        ("access_token", "fresh-token".to_owned(), true, false),
        ("project_id", "8".to_owned(), false, false),
        ("user_uuid", Uuid::new_v4().to_string(), false, false),
        ("region", "http://127.0.0.1:2".to_owned(), false, false),
    ] {
        let mut old = grant.clone();
        if legacy {
            old["secrets"].as_object_mut().unwrap().remove("user_uuid");
        }
        h.request(Method::PUT, "connections/posthog")
            .json(&old)
            .send()
            .await?
            .error_for_status()?;
        h.request(Method::DELETE, "connections/posthog/credentials")
            .send()
            .await?
            .error_for_status()?;
        h = Host::open(h.close().await?).await?;
        let mut next = grant.clone();
        next["grants"] = json!([]);
        next["secrets"][field] = json!(value);
        let info: ConnectionInfo = h
            .request(Method::PUT, "connections/posthog?preserve_grants=true")
            .json(&next)
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        assert_eq!(info.grants.contains(&topic), restore, "{field}");
    }
    serving.abort();
    h.close().await?;
    Ok(())
}

#[tokio::test]
async fn broken_service_watch_does_not_block_other_services() -> Result<()> {
    use axum::{
        Json, Router,
        routing::{get, post},
    };
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    let h = Host::new().await?;
    let (topic, _) = h
        .server
        .engine()
        .create_topic("Service watches", "")
        .await?;
    let bad = Uuid::from_u128(1);
    let good = Uuid::from_u128(2);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let origin = format!("http://{}", listener.local_addr()?);
    let calls = Arc::new(AtomicUsize::new(0));
    let count = calls.clone();
    let flag_calls = Arc::new(AtomicUsize::new(0));
    let reads = flag_calls.clone();
    let api = Router::new()
        .route("/api/projects/7/tasks/", get(|| async { StatusCode::OK }))
        .route("/mcp", post(move |Json(body): Json<serde_json::Value>| {
            let reads = reads.clone();
            async move {
                use axum::response::IntoResponse;
                let result = match body["method"].as_str() {
                    Some("initialize") => json!({"protocolVersion":"2025-06-18","capabilities":{"tools":{}}}),
                    Some("notifications/initialized") => return StatusCode::ACCEPTED.into_response(),
                    Some("tools/list") => json!({"tools":[{"name":"feature-flag-get-definition","inputSchema":{"type":"object"}}]}),
                    Some("tools/call") => {
                        assert_eq!(body["params"]["name"], "feature-flag-get-definition");
                        assert_eq!(body["params"]["arguments"]["id"], 42);
                        let active = reads.fetch_add(1, Ordering::SeqCst) == 0;
                        json!({"content":[],"structuredContent":{"active":active,"filters":{}},"isError":false})
                    }
                    _ => return StatusCode::BAD_REQUEST.into_response(),
                };
                Json(json!({"jsonrpc":"2.0","id":body["id"],"result":result})).into_response()
            }
        }))
        .route("/api/projects/7/mcp_server_installations/available_tools/", get(move || async move {
            Json(json!({"servers":[{"installation_id":good,"name":"Healthy","slug":"healthy","tools":[{"name":"list_items","description":"Read","annotations":{"readOnlyHint":true},"input_schema":{"type":"object"},"approval_state":"approved"}]}]}))
        }))
        .route(&format!("/api/projects/7/mcp_server_installations/{good}/call_tool/"), post(move || { let count = count.clone(); async move {
            let revision = count.fetch_add(1, Ordering::SeqCst).min(1);
            Json(json!({"is_error":false,"content":[],"structured_content":{"items":[revision]}}))
        }}));
    let upstream = tokio::spawn(async move { axum::serve(listener, api).await });
    let mut watches: Vec<Watch> = [bad, good]
        .into_iter()
        .map(|key| Watch {
            id: Uuid::new_v4().into(),
            connection: "work".into(),
            kind: "service".into(),
            key: key.to_string(),
            label: key.to_string(),
        })
        .collect();
    watches.push(Watch {
        id: Uuid::new_v4().into(),
        connection: "work".into(),
        kind: "flag".into(),
        key: "42".into(),
        label: "Fixture flag".into(),
    });
    h.server.engine().set_watch(topic, watches).await?;
    h.request(Method::PUT, "connections/work").json(&json!({"kind":"posthog","label":"Work","grants":[topic],"secrets":{"access_token":"fixture","region":origin,"project_id":"7","poll_interval_seconds":"1"}})).send().await?.error_for_status()?;
    tokio::time::timeout(std::time::Duration::from_secs(8), async {
        while calls.load(Ordering::SeqCst) < 2 || flag_calls.load(Ordering::SeqCst) < 2 {
            tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        }
    })
    .await?;
    tokio::time::timeout(std::time::Duration::from_secs(8), async {
        loop {
            let observations = h.server.engine().source_observations(topic, 10)?;
            if observations
                .iter()
                .any(|item| item.to_string().contains("Fixture flag"))
                && observations
                    .iter()
                    .any(|item| item.to_string().contains("Healthy · list_items changed"))
            {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        }
        anyhow::Ok(())
    })
    .await??;
    let connection = h
        .request(Method::GET, "connections")
        .send()
        .await?
        .error_for_status()?
        .json::<serde_json::Value>()
        .await?;
    assert!(connection.to_string().contains("failing"), "{connection}");
    h.close().await?;
    upstream.abort();
    Ok(())
}
