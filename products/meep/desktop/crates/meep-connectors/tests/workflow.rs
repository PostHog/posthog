use anyhow::{Context, Result};
use hmac::{Hmac, Mac};
use http::HeaderMap;
use meep_connectors::{
    ConnectorFactory, LiveConnector, StoreState, WatchMode, WebhookError, supported_modes,
};
use meep_ingest::Event;
use meep_store::Connection;
use serde_json::{Value, json};
use sha2::Sha256;
use std::{
    collections::BTreeMap,
    io::{Read, Write},
    net::TcpStream,
    path::Path,
    sync::Arc,
    thread,
};
use tiny_http::{Response, Server};

const SECRET: &str = "test workflow key";
const TOPIC: &str = "00000000-0000-4000-8000-000000000090";

fn payload() -> Value {
    json!({"topic_hint":TOPIC,"source":{"service":"slack","kind":"channel","key":"C123"},
        "author":"U1","text":"Ready","at":"2026-11-21T18:42:12.123Z","external_id":"run-178:slack-ev6",
        "thread_hint":"C123/ts1","attributes":{"fact":"The release is ready.","metric":5}})
}

fn build(path: &Path, kind: &str, config: Value) -> Result<Box<dyn LiveConnector>> {
    let factory = ConnectorFactory::new(Arc::new(StoreState::new(Connection::open(path)?)?));
    factory.build(
        kind,
        config,
        &BTreeMap::from([("secret".into(), SECRET.into())]),
    )
}

fn sign(data: &[u8]) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(SECRET.as_bytes()).unwrap();
    mac.update(data);
    format!("sha256={}", hex::encode(mac.finalize().into_bytes()))
}

fn post(addr: &str, header: &str, credential: &str, body: &str) -> Result<u16> {
    let mut stream = TcpStream::connect(addr)?;
    write!(
        stream,
        "POST /v1/ingest/work HTTP/1.1\r\nHost: {addr}\r\n{header}: {credential}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    )?;
    let mut s = String::new();
    stream.read_to_string(&mut s)?;
    Ok(s.split_whitespace()
        .nth(1)
        .context("missing status")?
        .parse()?)
}

#[test]
fn workflow_deliveries_authenticate_and_acknowledge_only_after_ingest_for_both_header_schemes()
-> Result<()> {
    for auth in ["shared_secret", "hmac_sha256"] {
        let dir = tempfile::tempdir()?;
        let path = dir.path().join("receipts.sqlite");
        let config = json!({"connection":"work","preset":"posthog_workflow","auth":{"kind":auth,"header":"x-workflow"}});
        let connector = build(&path, "webhook", config.clone())?;
        let listener = Server::http("127.0.0.1:0").unwrap();
        let addr = listener.server_addr().to_string();
        let receiver = thread::spawn(move || -> Result<Vec<Event>> {
            let mut delivered = vec![];
            for index in 0..4 {
                let mut req = listener
                    .recv_timeout(std::time::Duration::from_secs(5))?
                    .context("missing webhook request")?;
                assert_eq!(req.url(), "/v1/ingest/work");
                let mut body = vec![];
                req.as_reader().read_to_end(&mut body)?;
                let mut headers = HeaderMap::new();
                for field in req.headers() {
                    headers.append(
                        field.field.as_str().as_str().parse::<http::HeaderName>()?,
                        field.value.as_str().parse()?,
                    );
                }
                let status = match connector.receive_webhook(&headers, &body) {
                    Err(error)
                        if matches!(
                            error.downcast_ref::<WebhookError>(),
                            Some(WebhookError::Unauthorized)
                        ) =>
                    {
                        401
                    }
                    Err(error) => return Err(error),
                    Ok(events) if index == 1 => {
                        assert_eq!(events.len(), 1);
                        503 // Engine failed before delivery. The workflow will retry.
                    }
                    Ok(events) => {
                        if index == 3 {
                            assert!(events.is_empty());
                        }
                        connector.acknowledge_webhook(&events)?;
                        delivered.extend(events);
                        204
                    }
                };
                req.respond(Response::empty(status))?;
            }
            Ok(delivered)
        });
        let body = serde_json::to_string(&payload())?;
        let credential = if auth == "shared_secret" {
            SECRET.into()
        } else {
            sign(body.as_bytes())
        };
        for (header, expected) in [
            ("wrong", 401),
            (credential.as_str(), 503),
            (credential.as_str(), 204),
            (credential.as_str(), 204),
        ] {
            assert_eq!(post(&addr, "x-workflow", header, &body)?, expected);
        }
        let delivered = receiver.join().unwrap()?;
        assert_eq!(delivered.len(), 1);
        let e = &delivered[0];
        assert_eq!(e.connection, "work");
        assert_eq!(e.kind, "channel");
        assert_eq!(e.channel, "C123");
        assert_eq!(e.external_id, "run-178:slack-ev6");
        assert_eq!(e.thread_hint.as_deref(), Some("C123/ts1"));
        assert_eq!(e.attributes["topic_hint"], TOPIC);
        assert_eq!(e.attributes["source"]["service"], "slack");
        assert_eq!(e.attributes["metric"], 5);
        let headers = HeaderMap::from_iter([(
            http::HeaderName::from_static("x-workflow"),
            credential.parse()?,
        )]);
        let reopened = build(&path, "webhook", config.clone())?;
        assert!(
            reopened
                .receive_webhook(&headers, body.as_bytes())?
                .is_empty()
        );
        let mut other = config;
        other["connection"] = json!("another");
        assert_eq!(
            build(&path, "webhook", other)?
                .receive_webhook(&headers, body.as_bytes())?
                .len(),
            1
        );
    }
    Ok(())
}

#[tokio::test]
async fn bound_workflow_prefers_push_and_filters_signed_observations_by_the_configured_watch()
-> Result<()> {
    let dir = tempfile::tempdir()?;
    let path = dir.path().join("push.sqlite");
    assert_eq!(
        supported_modes("mcp", true),
        [WatchMode::Push, WatchMode::Pull]
    );
    assert_eq!(supported_modes("posthog", false), [WatchMode::Pull]);
    assert_eq!(supported_modes("webhook", false), [WatchMode::Push]);
    let watch = json!({"watch":{"id":TOPIC,"connection":"work","kind":"channel","key":"C123","label":"Watched channel"},"workflow":"release-notifications"});
    let conn = build(&path, "mcp", json!({"connection":"work","watches":[watch]}))?;
    assert!(conn.poll(chrono::DateTime::UNIX_EPOCH).await?.is_empty());
    let mut headers = HeaderMap::new();
    headers.insert("x-meep-secret", SECRET.parse()?);
    let event = payload();
    assert_eq!(
        conn.receive_webhook(&headers, &serde_json::to_vec(&event)?)?
            .len(),
        1
    );
    for (field, value) in [("key", "C999"), ("kind", "repo")] {
        let mut changed = event.clone();
        changed["source"][field] = json!(value);
        assert!(
            conn.receive_webhook(&headers, &serde_json::to_vec(&changed)?)?
                .is_empty()
        );
    }
    Ok(())
}
