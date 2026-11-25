use super::*;
use std::{sync::Mutex, thread};
use tiny_http::{Header, Response, Server};

fn host() -> (String, Server) {
    let server = Server::http("127.0.0.1:0").expect("bind loopback");
    (format!("http://{}", server.server_addr()), server)
}
fn gateway(url: String) -> Gateway {
    Gateway::new(
        Config {
            base_url: url,
            ..Config::default()
        },
        Arc::new("pha_loopback".to_owned()),
    )
    .expect("gateway")
}
fn questions() -> Questions {
    [
        (
            "apply".into(),
            Question::Noul {
                instructions: "Does the rule apply?".into(),
                criteria: [(true, "yes".into()), (false, "no".into())].into(),
            },
        ),
        (
            "route".into(),
            Question::Choice {
                instructions: "Which route?".into(),
                criteria: [
                    ("new".into(), "New thread".into()),
                    ("existing".into(), "Continue".into()),
                ]
                .into(),
            },
        ),
        (
            "rank".into(),
            Question::Score {
                instructions: "How relevant?".into(),
                criteria: vec!["Low".into(), "High".into()],
            },
        ),
    ]
    .into()
}
fn respond(
    server: &Server,
    path: &str,
    token: &str,
    check: impl FnOnce(Value),
    status: u16,
    reply: Value,
) {
    let mut request = server
        .recv_timeout(Duration::from_secs(30))
        .expect("receive")
        .expect("request");
    assert_eq!(request.url(), path);
    assert!(
        request.headers().iter().any(
            |h| h.field.equiv("Authorization") && h.value.as_str() == format!("Bearer {token}")
        )
    );
    check(serde_json::from_reader(request.as_reader()).expect("body"));
    request
        .respond(Response::from_string(reply.to_string()).with_status_code(status))
        .expect("response");
}

#[tokio::test]
async fn system_one_preserves_each_question_type_calibration_usage_and_refusals() {
    let (origin, s) = host();
    let h = thread::spawn(move || {
        respond(
            &s,
            "/v1/systemone",
            "pha_loopback",
            |v| {
                assert_eq!(v["model"], "posthog/hogference/jevk5-fp8-0.2");
                assert_eq!(v["state"]["mission"], "Delivery");
                assert_eq!(v["questions"]["apply"]["criteria"]["true"], "yes");
                assert_eq!(v["questions"]["route"]["type"], "choice");
                assert_eq!(v["questions"]["rank"]["criteria"], json!(["Low", "High"]));
            },
            200,
            json!({"model":"jev","answers":{"apply":{"type":"noul","noul":0.92},"route":{"type":"choice","choice":"existing","confidence":0.88,"probabilities":{"new":0.12,"existing":0.88}},"rank":{"type":"refusal"}},"usage":{"input_tokens":14}}),
        )
    });
    let d = gateway(origin)
        .decide(&json!({"mission":"Delivery"}), &questions())
        .await
        .expect("decisions");
    assert!(
        matches!(&d.answers["route"],Answer::Choice{calibration,..} if calibration.confidence==Some(0.88) && calibration.probabilities["new"]==0.12)
    );
    assert!(matches!(d.answers["rank"], Answer::Refusal));
    assert_eq!(d.usage["input_tokens"], 14);
    h.join().expect("upstream");
}

#[tokio::test]
async fn completion_retries_a_temporary_failure_and_exposes_attempt_metadata() {
    let (origin, s) = host();
    let log = Arc::new(Mutex::new(vec![]));
    let seen = log.clone();
    let g =
        gateway(origin).with_log(move |e| seen.lock().expect("log").push((e.attempt, e.status)));
    let h = thread::spawn(move || {
        respond(
            &s,
            "/v1/chat/completions",
            "pha_loopback",
            |_| {},
            503,
            Value::Null,
        );
        respond(
            &s,
            "/v1/chat/completions",
            "pha_loopback",
            |v| {
                assert_eq!(v["max_completion_tokens"], 240);
                assert_eq!(v["model"], "openai/gpt-5.4-mini");
                assert_eq!(
                    v["messages"],
                    json!([{"role":"system","content":"Summarize"},{"role":"user","content":"context"}])
                );
            },
            200,
            json!({"choices":[{"message":{"content":"A take"}}]}),
        );
    });
    assert_eq!(
        g.write(
            "Summarize",
            &[Message {
                role: Role::User,
                content: "context".into()
            }],
            240
        )
        .await
        .expect("write"),
        "A take"
    );
    assert_eq!(
        *log.lock().expect("log"),
        [(1, None), (1, Some(503)), (2, None), (2, Some(200))]
    );
    h.join().expect("upstream");
}
#[tokio::test]
async fn missing_scope_unauthorized_and_refusal_are_distinct_terminal_results() {
    for (status, body, expected) in [
        (401, json!({"code":"scope_missing"}), "scope"),
        (401, json!({"code":"auth_failed"}), "auth"),
        (
            200,
            json!({"choices":[{"message":{"refusal":"declined"}}]}),
            "refusal",
        ),
    ] {
        let (origin, s) = host();
        let h = thread::spawn(move || {
            respond(
                &s,
                "/v1/chat/completions",
                "pha_loopback",
                |_| {},
                status,
                body,
            )
        });
        let e = gateway(origin).write("", &[], 40).await.expect_err("error");
        assert!(matches!(
            (expected, e),
            ("scope", Error::MissingScope)
                | ("auth", Error::Unauthorized)
                | ("refusal", Error::Refused)
        ));
        h.join().expect("upstream");
    }
}
#[tokio::test]
async fn a_long_retry_after_is_returned_without_retrying_early() {
    let (origin, s) = host();
    let h = thread::spawn(move || {
        let request = s.recv().expect("request");
        request
            .respond(
                Response::empty(429)
                    .with_header(Header::from_bytes("Retry-After", "90").expect("header")),
            )
            .expect("429");
    });
    let e = gateway(origin)
        .write("", &[], 1)
        .await
        .expect_err("unavailable");
    assert!(
        matches!(e,Error::Unavailable{retry_after:Some(delay),..} if delay==Duration::from_secs(90))
    );
    h.join().expect("upstream");
}
#[tokio::test]
async fn invalid_or_missing_answers_are_rejected_before_the_engine_can_apply_them() {
    for answers in [
        json!({}),
        json!({"apply":{"type":"noul","noul":1.1},"rank":{"type":"refusal"},"route":{"type":"refusal"}}),
        json!({"apply":{"type":"refusal"},"rank":{"type":"score","score":1},"route":{"type":"choice","choice":"fabricated"}}),
    ] {
        let (origin, s) = host();
        let h = thread::spawn(move || {
            respond(
                &s,
                "/v1/systemone",
                "pha_loopback",
                |_| {},
                200,
                json!({"model":"jev","answers":answers,"usage":{}}),
            )
        });
        assert!(matches!(
            gateway(origin).decide(&Value::Null, &questions()).await,
            Err(Error::Invalid(_))
        ));
        h.join().expect("upstream");
    }
}

#[tokio::test]
async fn transport_timeout_is_bounded_and_returns_a_retryable_error() {
    let (origin, s) = host();
    let g = Gateway::new(
        Config {
            base_url: origin,
            timeout: Duration::from_millis(80),
            ..Config::default()
        },
        Arc::new("pha_test".to_owned()),
    )
    .expect("gateway");
    let count = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let attempts = count.clone();
    let g = g.with_log(move |e| {
        if e.status.is_none() {
            attempts.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        }
    });
    // Hold accepted requests open through all attempts.
    let e = tokio::time::timeout(Duration::from_secs(5), g.write("", &[], 1))
        .await
        .expect("bounded")
        .expect_err("timeout");
    assert!(matches!(e,Error::Unavailable{cause,..} if cause=="request timed out"));
    assert_eq!(count.load(std::sync::atomic::Ordering::Relaxed), 3);
    drop(s);
}

#[test]
fn gateway_credentials_require_tls_outside_loopback() {
    for (origin, accepted) in [
        ("http://example.org", false),
        ("http://localhost.example.org", false),
        ("http://[::1]", true),
        ("https://example.org", true),
    ] {
        assert_eq!(
            Gateway::new(
                Config {
                    base_url: origin.into(),
                    ..Config::default()
                },
                Arc::new("fixture".to_owned())
            )
            .is_ok(),
            accepted
        );
    }
}
