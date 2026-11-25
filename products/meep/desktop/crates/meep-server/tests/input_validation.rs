#[allow(dead_code)]
mod support;

use anyhow::Result;
use axum::{
    Json, Router,
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
};
use reqwest::Method;
use serde_json::json;
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};
use support::{Host, create};
use uuid::Uuid;

#[tokio::test]
async fn bad_message_and_model_choices_are_client_errors_but_provider_failures_are_not()
-> Result<()> {
    let failed = Arc::new(AtomicBool::new(false));
    let provider_failed = failed.clone();
    let provider = Router::new()
        .route(
            "/mcp",
            post(|Json(body): Json<serde_json::Value>| async move {
                let result = match body["method"].as_str() {
                    Some("initialize") => {
                        json!({"protocolVersion":"2025-06-18","capabilities":{"tools":{}}})
                    }
                    Some("notifications/initialized") => {
                        return StatusCode::ACCEPTED.into_response();
                    }
                    Some("tools/list") => json!({"tools":[]}),
                    _ => return StatusCode::BAD_REQUEST.into_response(),
                };
                Json(json!({"jsonrpc":"2.0","id":body["id"],"result":result})).into_response()
            }),
        )
        .route(
            "/api/projects/7/tasks/@me/config/",
            get(|| async { Json(json!({"resolved_ai_run_defaults":{"runtime":"acp","runtime_adapter":"claude","model":"claude-test","reasoning_effort":null}})) }),
        )
        .route(
            "/api/projects/7/tasks/models/",
            get(move || {
                let failed = provider_failed.clone();
                async move {
                    if failed.load(Ordering::SeqCst) {
                        return StatusCode::SERVICE_UNAVAILABLE.into_response();
                    }
                    Json(json!({"models":[
                        {"model":"claude-test","display_name":"Claude","runtime_adapter":"claude"},
                        {"model":"codex-test","display_name":"Codex","runtime_adapter":"codex"}
                    ]}))
                    .into_response()
                }
            }),
        )
        .fallback(|| async { Json(json!({"results":[]})) });
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let origin = format!("http://{}", listener.local_addr()?);
    let mock = tokio::spawn(async move { axum::serve(listener, provider).await });
    let h = Host::new().await?;
    let topic = Uuid::new_v4().into();
    h.commands(vec![create(topic)]).await?;
    h.request(Method::PUT, "connections/posthog")
        .json(
            &json!({"kind":"posthog","label":"Fixture","grants":[topic],"secrets":{
                "region":origin,"project_id":"7","access_token":"fixture"
            }}),
        )
        .send()
        .await?
        .error_for_status()?;

    tokio::time::timeout(std::time::Duration::from_secs(15), async {
        loop {
            let health = h
                .request(Method::GET, "health")
                .send()
                .await?
                .json::<meep_wire::ServerHealth>()
                .await?;
            if health.posthog {
                break anyhow::Ok(());
            }
            tokio::time::sleep(std::time::Duration::from_millis(30)).await;
        }
    })
    .await??;

    let models = format!("topics/{topic}/models");
    let valid = h
        .request(Method::PUT, &models)
        .json(&json!({"model":"claude-test"}))
        .send()
        .await?;
    let status = valid.status();
    let valid_body = valid.text().await?;
    assert_eq!(status, StatusCode::OK, "{valid_body}");
    for input in [
        json!({"model":"missing-model"}),
        json!({"model":"claude-test","billing":"own-subscription"}),
    ] {
        let response = h.request(Method::PUT, &models).json(&input).send().await?;
        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
        assert_eq!(
            response.json::<meep_wire::ApiError>().await?.code,
            "invalid_request"
        );
    }
    let selected = h
        .request(Method::GET, &models)
        .send()
        .await?
        .json::<meep_wire::ChatModels>()
        .await?;
    assert_eq!(selected.selected.as_deref(), Some("claude-test"));

    let task = Uuid::new_v4();
    let messages = format!("topics/{topic}/tasks/{task}/messages");
    for text in ["", " \n\t "] {
        let response = h
            .request(Method::POST, &messages)
            .json(&json!({"text":text}))
            .send()
            .await?;
        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
        let error = response.json::<meep_wire::ApiError>().await?;
        assert_eq!(error.code, "invalid_request");
        assert_eq!(error.message, "Enter a message");
    }
    failed.store(true, Ordering::SeqCst);
    let response = h
        .request(Method::PUT, &models)
        .json(&json!({"model":"claude-test"}))
        .send()
        .await?;
    assert_eq!(response.status(), StatusCode::BAD_GATEWAY);
    assert_eq!(
        response.json::<meep_wire::ApiError>().await?.code,
        "chat_models"
    );
    mock.abort();
    h.close().await?;
    Ok(())
}

#[tokio::test]
async fn manual_callback_accepts_empty_event_header_and_rejects_bad_nonempty_header() -> Result<()>
{
    use meep_topic::RoutineBinding;
    let h = Host::new().await?;
    let topic = Uuid::new_v4().into();
    h.commands(vec![create(topic)]).await?;
    let secret = h
        .server
        .engine()
        .bind_routine(
            topic,
            RoutineBinding {
                watches: vec![],
                id: "manual".into(),
                name: "Manual".into(),
                trigger: "Manual".into(),
                backend: "posthog".into(),
                external_id: Uuid::new_v4().to_string(),
            },
        )
        .await?;
    let path = format!("{}/v1/routines/{topic}/manual/callback", h.origin);
    let callback = |header: &str| {
        h.client
            .post(&path)
            .header("Idempotency-Key", Uuid::new_v4().to_string())
            .header("X-Meep-Event-Observation", header)
            .json(&json!({"secret":secret,"op":{"kind":"AddFact","text":"Fixture result"}}))
    };
    let bad = callback("invalid").send().await?;
    assert_eq!(bad.status(), StatusCode::BAD_REQUEST);
    assert_eq!(
        bad.json::<meep_wire::ApiError>().await?.code,
        "invalid_request"
    );
    let manual = callback("").send().await?;
    assert_eq!(manual.status(), StatusCode::OK);
    assert_eq!(h.server.engine().topic(topic)?.topic.facts.len(), 1);
    h.close().await?;
    Ok(())
}
