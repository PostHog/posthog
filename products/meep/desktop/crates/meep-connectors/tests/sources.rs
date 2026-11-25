mod support;
use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use http::HeaderMap;
use meep_connections::Health;
use meep_connectors::{ConnectorFactory, LiveConnector, StateStore, StoreState, WebhookError};
use meep_store::Connection;
use serde_json::{Value, json};
use std::{collections::BTreeMap, path::Path, sync::Arc, thread, time::Duration};
use support::{McpServer, Step};
use tiny_http::{Header, Response, Server};

struct Reply {
    path: String,
    status: u16,
    response: Value,
}

fn reply(path: &str, response: Value) -> Reply {
    Reply {
        path: format!("/api/projects/17/{path}"),
        status: 200,
        response,
    }
}

fn failure(path: &str, status: u16, detail: &str) -> Reply {
    Reply {
        status,
        ..reply(path, json!({"detail":detail}))
    }
}

struct Loopback {
    origin: String,
    worker: thread::JoinHandle<Vec<Value>>,
}

impl Loopback {
    fn start(replies: Vec<Reply>) -> Self {
        let server = Server::http("127.0.0.1:0").unwrap();
        let origin = format!("http://{}", server.server_addr());
        let worker = thread::spawn(move || {
            let mut bodies = vec![];
            for reply in replies {
                let mut req = server
                    .recv_timeout(Duration::from_secs(45))
                    .unwrap()
                    .expect("expected a connector request");
                assert_eq!(req.url(), reply.path);
                assert_eq!(
                    req.headers()
                        .iter()
                        .find(|h| h.field.equiv("authorization"))
                        .unwrap()
                        .value
                        .as_str(),
                    "Bearer test-token"
                );
                let mut body = String::new();
                req.as_reader().read_to_string(&mut body).unwrap();
                if body.is_empty() {
                    assert_eq!(req.method().as_str(), "GET");
                } else {
                    assert_eq!(req.method().as_str(), "POST");
                    bodies.push(serde_json::from_str(&body).unwrap());
                }
                let content_type = Header::from_bytes("Content-Type", "application/json").unwrap();
                req.respond(
                    Response::from_string(reply.response.to_string())
                        .with_header(content_type)
                        .with_status_code(reply.status),
                )
                .unwrap();
            }
            bodies
        });
        Self { origin, worker }
    }

    fn bodies(self) -> Vec<Value> {
        self.worker.join().unwrap()
    }
}

const ACCOUNT: &str = "work";
const INSTALLATION: &str = "00000000-0000-4000-8000-000000000080";
const DISCOVERY: &str = "mcp_server_installations/available_tools/";
const CALL: &str = "mcp_server_installations/00000000-0000-4000-8000-000000000080/call_tool/";
const START: DateTime<Utc> = DateTime::UNIX_EPOCH;

fn watch(id: u128, kind: &str, key: &str) -> Value {
    json!({"id":uuid::Uuid::from_u128(id),"connection":ACCOUNT,"kind":kind,"key":key,"label":key})
}

fn factory(path: Option<&Path>) -> Result<ConnectorFactory> {
    let db = match path {
        Some(path) => Connection::open(path)?,
        None => Connection::open_in_memory()?,
    };
    Ok(ConnectorFactory::new(Arc::new(StoreState::new(db)?)))
}

fn build(factory: &ConnectorFactory, kind: &str, config: Value) -> Result<Box<dyn LiveConnector>> {
    factory.build(
        kind,
        config,
        &BTreeMap::from([
            ("token".into(), "test-token".into()),
            ("secret".into(), "test-key".into()),
        ]),
    )
}

fn account(origin: &str, watches: Value) -> Value {
    json!({"origin":origin,"connection":ACCOUNT,"project":17,"watches":watches})
}

fn posthog_config(server: &McpServer, mut watches: Value) -> Value {
    for watch in watches.as_array_mut().unwrap() {
        watch["mode"] = json!("pull");
    }
    json!({"connection":ACCOUNT, "project":17, "mcp_endpoint":server.endpoint, "watches":watches})
}

fn insight_call(tool: &str, id: Value, value: Value) -> Step {
    Step::call(
        tool,
        json!({"insightId":id,"output_format":"json"}),
        json!({"results":value}),
    )
}
#[tokio::test]
async fn insight_uses_latest_query_bucket_and_emits_only_beyond_absolute_threshold_across_reopens()
-> Result<()> {
    let tool = "insight_query";
    let mut steps = vec![];
    for val in [12, 15, 9, 9, 14, 9] {
        steps.extend([
            Step::list(&[tool]),
            insight_call(tool, json!(42), json!([{"count":999,"data":[77,val]}])),
        ]);
    }
    let server = McpServer::start(steps);
    let config = posthog_config(
        &server,
        json!([{"watch":watch(1,"insight","Signups"),"resource_id":42,"threshold":3}]),
    );
    let dir = tempfile::tempdir()?;
    let db = dir.path().join("state.sqlite");
    let connector = build(&factory(Some(&db))?, "posthog", config.clone())?;
    assert!(connector.poll(START).await?.is_empty());
    assert!(connector.poll(START).await?.is_empty());
    let first = &connector.poll(START).await?[0];
    assert_eq!(first.channel, "Signups");
    assert_eq!(first.kind, "insight");
    assert_eq!(
        first.attributes,
        json!({"old":15,"new":9,"fact":"Signups changed from 15 to 9."})
    );
    assert_eq!(first.attributes["fact"], first.text);
    drop(connector);
    let reopened = build(&factory(Some(&db))?, "posthog", config)?;
    assert!(reopened.poll(START).await?.is_empty());
    let up = &reopened.poll(START).await?[0];
    let down = &reopened.poll(START).await?[0];
    assert_ne!(up.external_id, down.external_id);
    assert_ne!(down.external_id, first.external_id);
    assert_eq!(first.thread_hint, down.thread_hint);
    server.finish();
    Ok(())
}

#[tokio::test]
async fn shared_source_changes_target_each_watch_and_keep_thresholds_independent() -> Result<()> {
    let tool = "insight-query";
    let mut steps = vec![];
    for value in [0, 3] {
        steps.push(Step::list(&[tool]));
        for _ in 0..2 {
            steps.push(insight_call(tool, json!(42), json!([[value]])));
        }
    }
    let server = McpServer::start(steps);
    let first = watch(11, "insight", "42");
    let second = watch(12, "insight", "42");
    let connector = build(
        &factory(None)?,
        "posthog",
        posthog_config(
            &server,
            json!([
                {"watch":first,"threshold":1}, {"watch":second,"threshold":5}
            ]),
        ),
    )?;
    assert!(connector.poll_routed(START).await?.is_empty());
    let events = connector.poll_routed(START).await?;
    assert_eq!(events.len(), 1);
    assert_eq!(serde_json::to_value(events[0].watch)?, first["id"]);
    server.finish();
    Ok(())
}

#[tokio::test]
async fn shared_flag_emits_one_targeted_change_per_watch() -> Result<()> {
    let tool = "feature-flag-get-definition";
    let mut steps = vec![];
    for active in [false, true] {
        steps.push(Step::list(&[tool]));
        for _ in 0..2 {
            steps.push(Step::call(
                tool,
                json!({"id":42}),
                json!({"active":active,"filters":{}}),
            ));
        }
    }
    let server = McpServer::start(steps);
    let first = watch(11, "flag", "42");
    let second = watch(12, "flag", "42");
    let connector = build(
        &factory(None)?,
        "posthog",
        posthog_config(
            &server,
            json!([
                {"watch":first}, {"watch":second}
            ]),
        ),
    )?;
    assert!(connector.poll_routed(START).await?.is_empty());
    let events = connector.poll_routed(START).await?;
    assert_eq!(events.len(), 2);
    assert_eq!(serde_json::to_value(events[0].watch)?, first["id"]);
    assert_eq!(serde_json::to_value(events[1].watch)?, second["id"]);
    server.finish();
    Ok(())
}

#[tokio::test]
async fn trusted_insight_refresh_uses_the_exact_saved_query_and_reuses_recent_result() -> Result<()>
{
    let query = json!({"kind":"DataVisualizationNode","source":{"kind":"HogQLQuery","query":"SELECT count() FROM events"}});
    let tool = "insight-query";
    let steps = (0..2)
        .flat_map(|_| {
            [
                Step::list(&[tool]),
                Step::call(
                    tool,
                    json!({"insightId":42,"output_format":"json"}),
                    json!({"query":{"kind":"unwrapped"},"insight":{"query":query},"results":[[0]]}),
                ),
            ]
        })
        .collect();
    let mcp = McpServer::start(steps);
    let api = Loopback::start(vec![reply(
        "query/",
        json!({"is_cached":false,"results":[[5]]}),
    )]);
    let mut config = posthog_config(&mcp, json!([{"watch":watch(1,"insight","42")} ]));
    config["origin"] = json!(api.origin);
    config["fresh_insights"] = json!(true);
    let connector = build(&factory(None)?, "posthog", config)?;
    assert!(connector.poll(START).await?.is_empty());
    assert!(connector.poll(START).await?.is_empty());
    assert_eq!(
        api.bodies(),
        vec![json!({"query":query,"refresh":"force_blocking"})]
    );
    mcp.finish();
    Ok(())
}

#[tokio::test]
async fn trusted_insight_refresh_reports_scope_failure_instead_of_using_stale_results() -> Result<()>
{
    let tool = "insight-query";
    let mcp = McpServer::start(vec![
        Step::list(&[tool]),
        Step::call(
            tool,
            json!({"insightId":42,"output_format":"json"}),
            json!({"insight":{"query":{"kind":"HogQLQuery","query":"SELECT 1"}},"results":[[0]]}),
        ),
    ]);
    let api = Loopback::start(vec![failure("query/", 403, "missing query scope")]);
    let mut config = posthog_config(&mcp, json!([{"watch":watch(1,"insight","42")} ]));
    config["origin"] = json!(api.origin);
    config["fresh_insights"] = json!(true);
    let connector = build(&factory(None)?, "posthog", config)?;
    let error = connector.poll(START).await.unwrap_err();
    assert!(format!("{error:#}").contains("missing query scope"));
    api.bodies();
    mcp.finish();
    Ok(())
}

#[tokio::test]
async fn trusted_insight_refresh_rejects_cached_or_unconfirmed_results() -> Result<()> {
    for response in [
        json!({"is_cached":true,"results":[[0]]}),
        json!({"results":[[0]]}),
    ] {
        let tool = "insight-query";
        let mcp = McpServer::start(vec![
            Step::list(&[tool]),
            Step::call(
                tool,
                json!({"insightId":42,"output_format":"json"}),
                json!({"insight":{"query":{"kind":"HogQLQuery","query":"SELECT 1"}},"results":[[0]]}),
            ),
        ]);
        let api = Loopback::start(vec![reply("query/", response)]);
        let mut config = posthog_config(&mcp, json!([{"watch":watch(1,"insight","42")} ]));
        config["origin"] = json!(api.origin);
        config["fresh_insights"] = json!(true);
        let connector = build(&factory(None)?, "posthog", config)?;
        let error = connector.poll(START).await.unwrap_err();
        assert!(format!("{error:#}").contains("did not confirm a fresh insight result"));
        api.bodies();
        mcp.finish();
    }
    Ok(())
}

#[tokio::test]
async fn flag_tracks_activation_and_targeting_but_ignores_metadata_and_payload_edits() -> Result<()>
{
    let flags = [
        (false, 10, "v1"),
        (false, 10, "v2"),
        (false, 35, "v2"),
        (true, 35, "v2"),
    ];
    let tool = "feature-flag-get-definition";
    let mut steps = vec![];
    for (active, rollout, other) in flags {
        steps.extend([Step::list(&[tool]),Step::call(tool,json!({"id":88}),json!({"active":active,
            "name":other,"filters":{"groups":[{"rollout_percentage":rollout}],"payloads":{"true":other}}}))]);
    }
    let server = McpServer::start(steps);
    let connector = build(
        &factory(None)?,
        "posthog",
        posthog_config(&server, json!([{"watch":watch(1,"flag","88")}])),
    )?;
    for _ in 0..2 {
        assert!(connector.poll(START).await?.is_empty());
    }
    let event = &connector.poll(START).await?[0];
    assert_eq!(
        event
            .attributes
            .pointer("/old/rollout/groups/0/rollout_percentage"),
        Some(&json!(10))
    );
    assert_eq!(
        event
            .attributes
            .pointer("/new/rollout/groups/0/rollout_percentage"),
        Some(&json!(35))
    );
    let event = &connector.poll(START).await?[0];
    assert_eq!(event.attributes["old"]["active"], false);
    assert_eq!(event.attributes["new"]["active"], true);
    assert!(matches!(connector.health(), Health::Ok { .. }));
    server.finish();
    Ok(())
}

#[tokio::test]
async fn hogql_binds_literal_event_names_and_emits_once_per_threshold_crossing() -> Result<()> {
    let tool = "execute-sql";
    let event = "Bill's \u{005c} signup";
    let sql = "SELECT count() AS meep_count FROM events WHERE event = base64Decode('QmlsbCdzIFwgc2lnbnVw') AND timestamp >= now() - toIntervalSecond(900) AND timestamp <= now()";
    let mut steps = vec![];
    for count in [5, 9, 4, 5] {
        steps.extend([
            Step::list(&[tool]),
            Step::call(tool, json!({"query":sql}), Value::Null)
                .event_query()
                .text(&format!("meep_count\n{count}")),
        ]);
    }
    let server = McpServer::start(steps);
    let connector = build(
        &factory(None)?,
        "posthog",
        posthog_config(
            &server,
            json!([{"watch":watch(1,"event",event),"threshold":5,"window_seconds":900}]),
        ),
    )?;
    let first = &connector.poll(START).await?[0];
    assert_eq!(first.channel, event);
    assert_eq!(first.attributes["old"], Value::Null);
    for _ in 0..2 {
        assert!(connector.poll(START).await?.is_empty());
    }
    let later = &connector.poll(START).await?[0];
    assert_eq!(later.attributes["old"], 4);
    assert_eq!(later.attributes["new"], 5);
    assert_ne!(later.external_id, first.external_id);
    server.finish();
    Ok(())
}

#[tokio::test]
async fn a_later_watch_failure_preserves_earlier_transitions_and_health_recovers() -> Result<()> {
    let tool = "insight-query";
    let mut steps = vec![];
    for (val, status) in [(19, 200), (20, 401), (20, 401), (20, 503), (20, 200)] {
        steps.extend([
            Step::list(&[tool]),
            insight_call(tool, json!(1), json!([{"metric":val}])),
            insight_call(tool, json!(2), json!(4)).fail(status),
        ]);
    }
    let server = McpServer::start(steps);
    let config = posthog_config(
        &server,
        json!([{"watch":watch(1,"insight","1"),"result_pointer":"/0/metric"},{"watch":watch(2,"insight","2")}]),
    );
    let connector = build(&factory(None)?, "posthog", config)?;
    assert!(connector.poll(START).await?.is_empty());
    let batch = connector.poll(START).await?;
    assert_eq!(batch.len(), 1);
    assert_eq!(batch[0].attributes["old"], 19);
    assert_eq!(batch[0].attributes["new"], 20);
    let Health::Expired { since, detail } = connector.health() else {
        panic!("401 must expire credentials")
    };
    assert!(detail.contains("work") && detail.contains("upstream detail"));
    assert!(connector.poll(START).await?.is_empty());
    assert!(matches!(connector.health(), Health::Expired { since:again,.. } if again == since));
    assert!(connector.poll(START).await?.is_empty());
    assert!(matches!(connector.health(), Health::Failing { detail,.. } if detail.contains("503")));
    assert!(connector.poll(START).await?.is_empty());
    assert!(matches!(connector.health(), Health::Ok { .. }));
    server.finish();
    Ok(())
}

fn discovery(tool: &str) -> Reply {
    reply(
        DISCOVERY,
        json!({"servers":[{"installation_id":INSTALLATION,"name":"Slack","slug":"slack","tools":[
        {"name":tool,"description":"Read","input_schema":{},"annotations":{},"approval_state":"approved"}]}]}),
    )
}

fn slack() -> Value {
    json!({"watch":watch(1,"channel","C123"),"tool":"history","arguments":{"channel":"C123","inclusive":true},
        "cursor_argument":"oldest","pagination":{"kind":"cursor","argument":"cursor","next":"/response_metadata/next_cursor"},
        "mapping":{"items":"/messages","id":"/id","author":"/user","text":"/text","timestamp":"/ts","thread":"/thread_ts"}})
}

fn mcp_config(origin: &str, subscriptions: Value) -> Value {
    let mut config = account(origin, subscriptions);
    config["installation_id"] = json!(INSTALLATION);
    config
}

fn msg(id: &str, ts: &str) -> Value {
    json!({"id":id,"ts":ts,"thread_ts":"10.012345","user":"U02","text":"updated"})
}

fn structured(value: Value) -> Reply {
    reply(
        CALL,
        json!({"content":[],"is_error":false,"structured_content":value}),
    )
}
fn text_result(value: Value) -> Reply {
    reply(
        CALL,
        json!({"content":[{"type":"text","text":value.to_string()}],"is_error":false}),
    )
}

#[tokio::test]
async fn mcp_drains_pages_in_order_and_resumes_the_exact_timestamp_including_unseen_ties()
-> Result<()> {
    let a = msg("a", "10.012345");
    let b = msg("b", "11.987654");
    let c = msg("c", "11.987654");
    let server = Loopback::start(vec![
        discovery("history"),
        structured(
            json!({"messages":[b],"has_more":true,"response_metadata":{"next_cursor":"page2"}}),
        ),
        text_result(json!({"messages":[b,a],"has_more":false})),
        discovery("history"),
        structured(json!({"messages":[a,b,c],"has_more":false})),
        discovery("history"),
        structured(json!({"messages":[b,c]})),
    ]);
    let config = mcp_config(&server.origin, json!([slack()]));
    let dir = tempfile::tempdir()?;
    let path = dir.path().join("mcp.sqlite");
    let connector = build(&factory(Some(&path))?, "mcp", config.clone())?;
    let batch = connector.poll(START).await?;
    assert_eq!(
        batch
            .iter()
            .map(|e| e.external_id.as_str())
            .collect::<Vec<_>>(),
        ["a", "b"]
    );
    assert_eq!(batch[0].at.timestamp_subsec_micros(), 12345);
    assert_eq!(batch[0].thread_hint.as_deref(), Some("10.012345"));
    assert_eq!(batch[0].attributes, a);
    drop(connector);
    let connector = build(&factory(Some(&path))?, "mcp", config)?;
    assert_eq!(connector.poll(START).await?[0].external_id, "c");
    assert!(connector.poll(START).await?.is_empty());
    let requests = server.bodies();
    assert_eq!(
        requests[0],
        json!({"tool_name":"history","arguments":{"channel":"C123","inclusive":true}})
    );
    assert_eq!(requests[1]["arguments"]["cursor"], "page2");
    assert_eq!(requests[2]["arguments"]["oldest"], "11.987654");
    assert!(requests[2]["arguments"].get("cursor").is_none());
    Ok(())
}

#[tokio::test]
async fn github_preset_keeps_each_pr_update_in_one_thread_and_stops_paging_at_the_watermark()
-> Result<()> {
    let pr = |id: i32, at: &str| json!({"html_url":format!("https://github.test/org/repo/pull/{id}"),"number":id,"user":{"login":"lin"},"title":"Change","updated_at":at});
    let prior = pr(3, "2025-01-01T00:00:00Z");
    let first = pr(4, "2025-01-02T00:00:00Z");
    let later = pr(4, "2025-01-03T00:00:00Z");
    let server = Loopback::start(vec![
        discovery("list_pull_requests"),
        text_result(json!([first, prior])),
        discovery("list_pull_requests"),
        text_result(json!([later, first])),
        text_result(json!([])),
    ]);
    let mut sub: Value =
        serde_json::from_str(include_str!("../templates/github-pull-requests.json"))?;
    sub["watch"] = watch(1, "repo", "org/repo");
    sub["arguments"]["owner"] = json!("org");
    sub["arguments"]["repo"] = json!("repo");
    sub["pagination"]["size"] = json!(2);
    let connector = build(
        &factory(None)?,
        "mcp",
        mcp_config(&server.origin, json!([sub])),
    )?;
    let since = "2025-01-02T00:00:00Z".parse()?;
    let one = connector.poll(since).await?;
    assert_eq!(one.len(), 1);
    let two = connector.poll(since).await?;
    assert_eq!(two.len(), 1);
    assert_eq!(one[0].thread_hint, two[0].thread_hint);
    assert_ne!(one[0].external_id, two[0].external_id);
    let requests = server.bodies();
    assert_eq!(requests[0]["arguments"]["perPage"], 2);
    assert_eq!(requests[2]["arguments"]["page"], 2);
    Ok(())
}

#[tokio::test]
async fn missing_tools_are_never_called_and_gateway_401_remains_typed() -> Result<()> {
    let server = Loopback::start(vec![
        discovery("something_else"),
        discovery("history"),
        failure(CALL, 401, "token expired"),
    ]);
    let connector = build(
        &factory(None)?,
        "mcp",
        mcp_config(&server.origin, json!([slack()])),
    )?;
    let err = connector.poll(START).await.unwrap_err();
    assert!(
        err.to_string()
            .contains("does not advertise tool 'history'")
    );
    assert!(matches!(connector.health(), Health::Failing {detail,..} if detail.contains("Slack")));
    connector.poll(START).await.unwrap_err();
    assert!(
        matches!(connector.health(), Health::Expired {detail,..} if detail.contains("token expired"))
    );
    assert_eq!(server.bodies().len(), 1);
    Ok(())
}

#[tokio::test]
async fn malformed_rows_and_failed_pages_never_advance_the_cursor() -> Result<()> {
    let first = msg("one", "10.1");
    let server = Loopback::start(vec![
        discovery("history"),
        structured(json!({"messages":[first],"response_metadata":{"next_cursor":"p"}})),
        reply(
            CALL,
            json!({"is_error":true,"content":[{"type":"text","text":"upstream denied access"}]}),
        ),
        discovery("history"),
        structured(json!({"messages":[first,{"id":"invalid"}]})),
        discovery("history"),
        structured(json!({"messages":[first]})),
    ]);
    let connector = build(
        &factory(None)?,
        "mcp",
        mcp_config(&server.origin, json!([slack()])),
    )?;
    assert!(
        connector
            .poll(START)
            .await
            .unwrap_err()
            .to_string()
            .contains("denied access")
    );
    assert!(
        connector
            .poll(START)
            .await
            .unwrap_err()
            .to_string()
            .contains("/ts")
    );
    assert_eq!(connector.poll(START).await?[0].external_id, "one");
    assert!(
        server
            .bodies()
            .iter()
            .all(|r| r["arguments"].get("oldest").is_none())
    );
    Ok(())
}

fn webhook_config(kind: &str) -> Value {
    json!({"connection":ACCOUNT,"watch":watch(1,"project","desktop"),"auth":{"kind":kind,"header":"X-Verify"},
        "mapping":{"items":"/records","id":"/id","text":"/title","timestamp":"/when","author":"/nested/a~1b","thread":"/pr"}})
}

const BODY: &[u8] = br#"{ "records": [{"id":32,"title":"Merged","when":"2025-02-03T10:23:00+02:00","nested":{"a/b":"Kim"},"pr":9}] }"#;

#[tokio::test]
async fn webhook_maps_authenticated_bytes_to_the_configured_watch_and_preserves_source_metadata()
-> Result<()> {
    let connector = build(&factory(None)?, "webhook", webhook_config("shared_secret"))?;
    let mut headers = HeaderMap::new();
    headers.insert("x-verify", "test-key".parse()?);
    let events = connector.receive_webhook(&headers, BODY)?;
    let event = &events[0];
    assert_eq!(
        (&event.connection, &event.kind, &event.channel),
        (
            &ACCOUNT.to_owned(),
            &"project".to_owned(),
            &"desktop".to_owned()
        )
    );
    assert_eq!(event.external_id, "32");
    assert_eq!(event.thread_hint.as_deref(), Some("9"));
    assert_eq!(event.author, "Kim");
    assert_eq!(event.at.to_rfc3339(), "2025-02-03T08:23:00+00:00");
    assert_eq!(event.attributes["nested"], json!({"a/b":"Kim"}));
    assert!(connector.poll(START).await?.is_empty());
    assert!(matches!(connector.health(), Health::Ok { .. }));
    let err = connector.receive_webhook(&headers, b"{}").unwrap_err();
    assert!(matches!(
        err.downcast_ref::<WebhookError>(),
        Some(WebhookError::InvalidPayload(_))
    ));
    Ok(())
}

#[test]
fn verifies_hmac_over_exact_raw_bytes_before_parsing_and_rejects_ambiguous_headers() -> Result<()> {
    // Produced independently using Python hmac.digest with key "test-key".
    let digest = "38ebfb90895ed9d7dad1a6e4391dbff1aafed06c7325b91d44bde50c3cca205b";
    let connector = build(&factory(None)?, "webhook", webhook_config("hmac_sha256"))?;
    let mut headers = HeaderMap::new();
    for bad in ["", "sha256=ab", "test-key"] {
        headers.insert("x-verify", bad.parse()?);
        let err = connector
            .receive_webhook(&headers, b"invalid JSON")
            .unwrap_err();
        assert!(matches!(
            err.downcast_ref::<WebhookError>(),
            Some(WebhookError::Unauthorized)
        ));
    }
    for valid in [digest.to_string(), format!("sha256={digest}")] {
        headers.insert("x-verify", valid.parse()?);
        assert_eq!(connector.receive_webhook(&headers, BODY)?.len(), 1);
        let mut changed = BODY.to_vec();
        changed.push(b' ');
        assert!(connector.receive_webhook(&headers, &changed).is_err());
    }
    headers.append("x-verify", digest.parse()?);
    assert!(connector.receive_webhook(&headers, BODY).is_err());
    headers.clear();
    assert!(connector.receive_webhook(&headers, BODY).is_err());
    Ok(())
}

#[test]
fn shared_secret_is_required_even_for_an_empty_body() -> Result<()> {
    let connector = build(&factory(None)?, "webhook", webhook_config("shared_secret"))?;
    let mut headers = HeaderMap::new();
    for secret in [None, Some(""), Some("bad")] {
        if let Some(s) = secret {
            headers.insert("X-Verify", s.parse()?);
        }
        let err = connector.receive_webhook(&headers, b"").unwrap_err();
        assert!(matches!(
            err.downcast_ref::<WebhookError>(),
            Some(WebhookError::Unauthorized)
        ));
    }
    Ok(())
}

#[test]
fn independent_stores_reject_stale_writes_without_overwriting_another_connection() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let path = dir.path().join("state.sqlite");
    let first = StoreState::new(Connection::open(&path)?)?;
    let second = StoreState::new(Connection::open(&path)?)?;
    assert_eq!(first.load("work")?, None);
    second.commit("work", None, &json!({"n":2}))?;
    assert!(first.commit("work", None, &json!({"n":1})).is_err());
    first.commit("another", None, &json!("isolated"))?;
    let old = first.load("work")?.context("missing checkpoint")?;
    assert_eq!(old, json!({"n":2}));
    second.commit("work", Some(&old), &json!({"n":3}))?;
    assert!(first.commit("work", Some(&old), &json!("stale")).is_err());
    assert_eq!(first.load("another")?, Some(json!("isolated")));
    Ok(())
}

#[test]
fn malformed_configurations_fail_before_making_requests() -> Result<()> {
    let factory = factory(None)?;
    let config = |mut w: Value| {
        w["mode"] = json!("pull");
        account("http://127.0.0.1:1", json!([w]))
    };
    for sub in [
        json!({"watch":watch(1,"flag","by-key"),"resource_id":0}),
        json!({"watch":watch(1,"insight","1"),"threshold":-1}),
        json!({"watch":watch(1,"event","daily"),"threshold":1.1,"window_seconds":60}),
        json!({"watch":watch(1,"event","daily"),"threshold":1,"window_seconds":0}),
        json!({"watch":watch(1,"unknown","key")}),
    ] {
        assert!(build(&factory, "posthog", config(sub)).is_err());
    }
    let mut bad = webhook_config("shared_secret");
    bad["mapping"]["id"] = json!("/a~b");
    assert!(build(&factory, "webhook", bad).is_err());
    assert!(
        factory
            .build(
                "webhook",
                webhook_config("shared_secret"),
                &Default::default()
            )
            .is_err()
    );
    let mut bad = webhook_config("shared_secret");
    bad["watch"]["connection"] = json!("another");
    assert!(build(&factory, "webhook", bad).is_err());
    Ok(())
}

#[tokio::test]
async fn changing_a_watch_resource_resets_its_baseline_even_when_its_id_stays_the_same()
-> Result<()> {
    let tool = "insight-query";
    let mut steps = vec![];
    for (id, result) in [(10, 20), (11, 500), (11, 499)] {
        steps.extend([
            Step::list(&[tool]),
            insight_call(tool, json!(id), json!(result)),
        ]);
    }
    let server = McpServer::start(steps);
    let factory = factory(None)?;
    let config = |id| {
        posthog_config(
            &server,
            json!([{"watch":watch(1,"insight","signups"),"resource_id":id}]),
        )
    };
    assert!(
        build(&factory, "posthog", config(10))?
            .poll(START)
            .await?
            .is_empty()
    );
    let changed = build(&factory, "posthog", config(11))?;
    assert!(changed.poll(START).await?.is_empty());
    let event = &changed.poll(START).await?[0];
    assert_eq!(event.attributes["old"], 500);
    server.finish();
    Ok(())
}

#[tokio::test]
async fn an_idle_posthog_account_checks_credentials_before_reporting_healthy() -> Result<()> {
    let server = McpServer::start(vec![Step::list(&[]).fail(401), Step::list(&[])]);
    let connector = build(
        &factory(None)?,
        "posthog",
        posthog_config(&server, json!([])),
    )?;
    assert!(connector.poll(START).await.is_err());
    assert!(matches!(connector.health(), Health::Expired { .. }));
    assert!(connector.poll(START).await?.is_empty());
    assert!(matches!(connector.health(), Health::Ok { .. }));
    server.finish();
    Ok(())
}

#[tokio::test]
async fn a_missing_installation_or_incomplete_page_never_reports_a_successful_empty_poll()
-> Result<()> {
    let page = json!({"messages":[msg("m","12.34")],"has_more":true, "response_metadata":{"next_cursor":"repeated"}});
    let server = Loopback::start(vec![
        reply(DISCOVERY, json!({"servers":[]})),
        discovery("history"),
        structured(json!({"messages":[],"has_more":true})),
        discovery("history"),
        structured(page.clone()),
        structured(page),
        discovery("history"),
        structured(json!({"messages":[msg("m","12.34")]})),
    ]);
    let connector = build(
        &factory(None)?,
        "mcp",
        mcp_config(&server.origin, json!([slack()])),
    )?;
    for message in ["not available", "no page cursor", "repeated a page cursor"] {
        assert!(
            connector
                .poll(START)
                .await
                .unwrap_err()
                .to_string()
                .contains(message)
        );
    }
    assert_eq!(connector.poll(START).await?[0].external_id, "m");
    assert!(
        server
            .bodies()
            .iter()
            .all(|b| b["arguments"].get("oldest").is_none())
    );
    Ok(())
}

#[tokio::test]
async fn slack_preset_limits_first_poll_by_since_and_maps_thread_roots() -> Result<()> {
    let mut sub: Value =
        serde_json::from_str(include_str!("../templates/slack-channel-history.json"))?;
    sub["watch"] = watch(1, "channel", "C123");
    sub["arguments"]["channel"] = json!("C123");
    let tool = sub["tool"].as_str().unwrap();
    let root = json!({"ts":"1000.000003","text":"Build finished","bot_id":"B1"});
    let server = Loopback::start(vec![
        discovery(tool),
        structured(json!({"messages":[root]})),
    ]);
    let connector = build(
        &factory(None)?,
        "mcp",
        mcp_config(&server.origin, json!([sub])),
    )?;
    let since = DateTime::from_timestamp(1000, 1000).unwrap();
    let events = connector.poll(since).await?;
    assert_eq!(events[0].thread_hint.as_deref(), Some("1000.000003"));
    assert_eq!(events[0].author, "B1");
    let requests = server.bodies();
    assert_eq!(requests[0]["arguments"]["oldest"], "1000.000001000");
    Ok(())
}

#[tokio::test]
async fn connected_tools_with_pending_or_revoked_approval_are_never_called() -> Result<()> {
    let mut replies = vec![];
    for state in ["pending", "denied", "unknown"] {
        let mut list = discovery("history");
        list.response["servers"][0]["tools"][0]["approval_state"] = json!(state);
        replies.push(list);
    }
    let server = Loopback::start(replies);
    let connector = build(
        &factory(None)?,
        "mcp",
        mcp_config(&server.origin, json!([slack()])),
    )?;
    for state in ["pending", "denied", "unknown"] {
        let err = connector.poll(START).await.unwrap_err().to_string();
        assert!(err.contains("approval") && err.contains("history") && err.contains(state));
    }
    assert!(server.bodies().is_empty());
    Ok(())
}

#[tokio::test]
async fn native_discovery_follows_next_cursor_and_never_invokes_an_unadvertised_alias() -> Result<()>
{
    let tool = "feature_flag_get_definition_by_key";
    let definition = "active: true\nfilters:\n  groups[1]{rollout_percentage}:\n    25";
    let server = McpServer::start(vec![
        Step::list(&["unrelated"]),
        Step::list(&[]).page("more"),
        Step::list(&[tool]).after("more"),
        Step::call(tool, json!({"key":"checkout"}), Value::Null).text(definition),
        Step::list(&[tool]),
        Step::call(tool, json!({"key":"checkout"}), Value::Null).rpc_error(),
    ]);
    let connector = build(
        &factory(None)?,
        "posthog",
        posthog_config(&server, json!([{"watch":watch(1,"flag","checkout")}])),
    )?;
    let err = connector.poll(START).await.unwrap_err();
    assert!(
        err.to_string()
            .contains("feature-flag-get-definition-by-key")
    );
    assert!(connector.poll(START).await?.is_empty());
    let err = connector.poll(START).await.unwrap_err().to_string();
    assert!(err.contains("upstream detail") && err.contains("tools/call"));
    server.finish();
    Ok(())
}

#[tokio::test]
async fn mixed_modes_poll_only_unbound_watches_and_accept_only_bound_workflow_sources() -> Result<()>
{
    let tool = "feature-flag-get-definition";
    let server = McpServer::start(vec![
        Step::list(&[tool]),
        Step::call(
            tool,
            json!({"id":8}),
            json!({"active":true,"filters":{"groups":[]}}),
        ),
    ]);
    let config = json!({"connection":ACCOUNT,"project":17,"mcp_endpoint":server.endpoint,"watches":[
        {"watch":watch(1,"insight","daily"),"workflow":"workflow-11"},
        {"watch":watch(2,"flag","8")}
    ]});
    let connector = build(&factory(None)?, "posthog", config)?;
    assert!(connector.poll(START).await?.is_empty());
    let mut headers = HeaderMap::new();
    headers.insert("x-meep-secret", "test-key".parse()?);
    let mut body = json!({"source":{"service":"posthog","kind":"insight","key":"daily"},
        "author":"workflow","at":"2026-01-02T01:00:00Z","external_id":"run/1","text":"Alert"});
    assert_eq!(
        connector
            .receive_webhook(&headers, &serde_json::to_vec(&body)?)?
            .len(),
        1
    );
    body["source"] = json!({"service":"posthog","kind":"flag","key":"8"});
    assert!(
        connector
            .receive_webhook(&headers, &serde_json::to_vec(&body)?)?
            .is_empty()
    );
    server.finish();
    Ok(())
}

#[tokio::test]
async fn failed_native_watch_preserves_its_checkpoint_while_later_watches_advance() -> Result<()> {
    let tool = "feature-flag-get-definition";
    let flag = |id, active| {
        Step::call(
            tool,
            json!({"id":id}),
            json!({"active":active,"filters":{}}),
        )
    };
    let missing = || Step::call(tool, json!({"id":1}), json!({"found":false}));
    let server = McpServer::start(vec![
        Step::list(&[tool]),
        flag(1, true),
        flag(2, true),
        Step::list(&[tool]),
        missing(),
        flag(2, false),
        Step::list(&[tool]),
        missing(),
        flag(2, false),
        Step::list(&[tool]),
        flag(1, false),
        flag(2, false),
    ]);
    let dir = tempfile::tempdir()?;
    let db = dir.path().join("watch-state.sqlite");
    let config = posthog_config(
        &server,
        json!([
            {"watch":watch(1,"flag","1")},
            {"watch":watch(2,"flag","2")}
        ]),
    );
    let connector = build(&factory(Some(&db))?, "posthog", config.clone())?;
    assert!(connector.poll(START).await?.is_empty());
    let events = connector.poll(START).await?;
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].channel, "2");
    assert_eq!(events[0].attributes["old"]["active"], true);
    assert_eq!(events[0].attributes["new"]["active"], false);
    assert!(matches!(connector.health(), Health::Failing { .. }));
    drop(connector);
    let reopened = build(&factory(Some(&db))?, "posthog", config)?;
    assert!(
        reopened.poll(START).await?.is_empty(),
        "healthy event must not repeat after restart"
    );
    assert!(matches!(reopened.health(), Health::Failing { .. }));
    let recovered = reopened.poll(START).await?;
    assert_eq!(recovered.len(), 1);
    assert_eq!(recovered[0].channel, "1");
    assert_eq!(recovered[0].attributes["old"]["active"], true);
    assert_eq!(recovered[0].attributes["new"]["active"], false);
    assert!(matches!(reopened.health(), Health::Ok { .. }));
    server.finish();
    Ok(())
}
