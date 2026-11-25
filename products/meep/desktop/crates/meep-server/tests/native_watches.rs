#[allow(dead_code)]
mod support;

use anyhow::Result;
use axum::{
    Json, Router,
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
};
use meep_topic::{Command, RoutineBinding, Watch};
use reqwest::Method;
use serde_json::{Value, json};
use std::sync::{
    Arc,
    atomic::{AtomicBool, AtomicUsize, Ordering},
};
use support::{Host, envelope};
use uuid::Uuid;

#[tokio::test]
async fn partial_native_failure_keeps_healthy_delivery_and_failing_health() -> Result<()> {
    let h = Host::new().await?;
    let (topic, _) = h.server.engine().create_topic("Native watches", "").await?;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let origin = format!("http://{}", listener.local_addr()?);
    let calls = Arc::new(AtomicUsize::new(0));
    let counter = calls.clone();
    let project_up = Arc::new(AtomicBool::new(true));
    let check_up = project_up.clone();
    let starts = Arc::new(AtomicUsize::new(0));
    let dispatches = starts.clone();
    let flow = Uuid::new_v4();
    let api = Router::new()
        .route("/api/projects/7/tasks/", get(move || {
            let check_up = check_up.clone();
            async move { if check_up.load(Ordering::SeqCst) { StatusCode::OK } else { StatusCode::SERVICE_UNAVAILABLE } }
        }))
        .route(&format!("/api/projects/7/hog_flows/{flow}/"), get(|| async { Json(json!({"status":"active","name":"Fixture workflow","actions":[],"edges":[]})) }))
        .route(&format!("/api/projects/7/hog_flows/{flow}/run/"), post(move || {
            let dispatches = dispatches.clone();
            async move { dispatches.fetch_add(1, Ordering::SeqCst); Json(json!({"invocation_id":Uuid::new_v4(),"status":"queued"})) }
        }))
        .route("/mcp", post(move |Json(body): Json<Value>| {
            let counter = counter.clone();
            async move {
                let result = match body["method"].as_str() {
                    Some("initialize") => json!({"protocolVersion":"2025-06-18","capabilities":{"tools":{}}}),
                    Some("notifications/initialized") => return StatusCode::ACCEPTED.into_response(),
                    Some("tools/list") => json!({"tools":[{"name":"feature-flag-get-definition","inputSchema":{"type":"object"}}]}),
                    Some("tools/call") => {
                        if body["params"]["arguments"]["id"] == 1 {
                            json!({"content":[],"structuredContent":{"found":false},"isError":false})
                        } else {
                            assert_eq!(body["params"]["arguments"]["id"], 2);
                            let active = counter.fetch_add(1, Ordering::SeqCst) == 0;
                            json!({"content":[],"structuredContent":{"active":active,"filters":{}},"isError":false})
                        }
                    }
                    _ => return StatusCode::BAD_REQUEST.into_response(),
                };
                Json(json!({"jsonrpc":"2.0","id":body["id"],"result":result})).into_response()
            }
        }));
    let upstream = tokio::spawn(async move { axum::serve(listener, api).await });
    let watches: Vec<_> = [1, 2]
        .into_iter()
        .map(|n| Watch {
            id: Uuid::new_v4().into(),
            connection: "work".into(),
            kind: "flag".into(),
            key: n.to_string(),
            label: format!("Flag {n}"),
        })
        .collect();
    h.server.engine().set_watch(topic, watches).await?;
    h.request(Method::PUT, "connections/work").json(&json!({"kind":"posthog","label":"Work","grants":[topic],"secrets":{"access_token":"fixture","region":origin,"project_id":"7","poll_interval_seconds":"1"}})).send().await?.error_for_status()?;
    tokio::time::timeout(std::time::Duration::from_secs(12), async {
        loop {
            if calls.load(Ordering::SeqCst) >= 2
                && !h.server.engine().source_observations(topic, 10)?.is_empty()
            {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        }
        anyhow::Ok(())
    })
    .await??;
    let connections = h
        .request(Method::GET, "connections")
        .send()
        .await?
        .error_for_status()?
        .json::<Value>()
        .await?;
    let work = connections["connections"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["id"] == "work")
        .unwrap();
    assert_eq!(work["health"], "failing");
    assert!(work["summary"].as_str().unwrap().contains("flag 1"));
    let binding = RoutineBinding {
        id: "fixture".into(),
        name: "Fixture".into(),
        trigger: "Manual".into(),
        backend: "posthog".into(),
        external_id: flow.to_string(),
        watches: vec![],
    };
    let results = h
        .commands(vec![envelope(
            topic,
            Command::SetRoutine { routine: binding },
        )])
        .await?;
    assert!(matches!(
        results.results[0],
        meep_wire::CommandResult::Applied { .. }
    ));
    let details = format!("routines/{topic}/fixture");
    let response = h.request(Method::GET, &details).send().await?;
    assert_eq!(
        response.status(),
        StatusCode::OK,
        "routine details remain available during a source failure"
    );
    let start = h
        .commands(vec![envelope(
            topic,
            Command::StartRoutine {
                routine: "fixture".into(),
                variables: Default::default(),
            },
        )])
        .await?;
    assert!(
        matches!(start.results[0], meep_wire::CommandResult::Applied { .. }),
        "{start:?}"
    );
    tokio::time::timeout(std::time::Duration::from_secs(10), async {
        while starts.load(Ordering::SeqCst) == 0 {
            tokio::time::sleep(std::time::Duration::from_millis(25)).await;
        }
    })
    .await?;
    project_up.store(false, Ordering::SeqCst);
    tokio::time::timeout(std::time::Duration::from_secs(12), async {
        loop {
            let value = h
                .request(Method::GET, "connections")
                .send()
                .await?
                .json::<Value>()
                .await?;
            if value["connections"].as_array().unwrap().iter().any(|c| {
                c["id"] == "work"
                    && c["summary"]
                        .as_str()
                        .unwrap_or_default()
                        .contains("Could not reach the PostHog project")
            }) {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        }
        anyhow::Ok(())
    })
    .await??;
    assert_eq!(
        h.request(Method::GET, &details).send().await?.status(),
        StatusCode::SERVICE_UNAVAILABLE,
        "a failed project check must still block workflows"
    );
    h.request(Method::DELETE, "connections/work/credentials")
        .send()
        .await?
        .error_for_status()?;
    assert_eq!(
        h.request(Method::GET, &details).send().await?.status(),
        StatusCode::BAD_REQUEST,
        "signed-out credentials must not grant workflow access"
    );
    h.close().await?;
    upstream.abort();
    Ok(())
}
