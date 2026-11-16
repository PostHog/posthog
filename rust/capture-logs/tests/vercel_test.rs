use capture_logs::endpoints::vercel::*;
use chrono::{TimeDelta, Utc};
use serde_json::json;

fn recent_millis() -> i64 {
    (Utc::now() - TimeDelta::minutes(1)).timestamp_millis()
}

fn request_line(id: &str) -> serde_json::Value {
    json!({
        "id": id,
        "deploymentId": "dpl_1",
        "source": "static",
        "host": "example.com",
        "timestamp": recent_millis(),
        "projectId": "prj_1",
        "projectName": "web",
        "level": "info",
        "environment": "production",
        "proxy": {
            "timestamp": recent_millis(),
            "method": "GET",
            "host": "example.com",
            "path": "/docs/start?utm_source=newsletter",
            "userAgent": ["Mozilla/5.0 ExampleBot/1.0"],
            "region": "iad1",
            "statusCode": 200,
            "clientIp": "192.0.2.10",
            "scheme": "https",
            "vercelCache": "HIT"
        }
    })
}

#[test]
fn parse_delivery_keeps_every_valid_line_in_both_formats() {
    // `b` has drifted field types; it keeps its row and loses only those fields.
    let drifted = json!({"id": "b", "timestamp": "soon", "proxy": {"statusCode": "200"}});
    let lines = [
        request_line("a"),
        json!(42),
        json!(["x"]),
        json!({"unrelated": true}),
        drifted,
        request_line("c"),
    ];

    let ndjson = lines
        .iter()
        .map(|l| l.to_string())
        .collect::<Vec<_>>()
        .join("\n");
    let array = serde_json::to_string(&lines).unwrap();

    for body in [ndjson, array] {
        let parsed = parse_delivery(body.as_bytes()).unwrap();
        let ids: Vec<_> = parsed.logs.iter().map(|l| l.id.clone().unwrap()).collect();
        assert_eq!(ids, ["a", "b", "c"]);
        assert_eq!(parsed.invalid, 3);
        assert_eq!(
            parsed.first_error.as_deref(),
            Some("expected a JSON object, got a number")
        );
        assert_eq!(parsed.logs[1].timestamp, None);
    }

    for body in [
        request_line("only").to_string(),
        serde_json::to_string_pretty(&request_line("only")).unwrap(),
        json!({"id": "only", "statusCode": "oops"}).to_string(),
    ] {
        let parsed = parse_delivery(body.as_bytes()).unwrap();
        assert_eq!((parsed.logs.len(), parsed.invalid), (1, 0), "{body}");
    }

    // A pretty-printed array with a syntax error falls back to lines, and no line is valid.
    let broken = "[\n  {\n    \"id\": \"a\",\n  },\n]";
    let parsed = parse_delivery(broken.as_bytes()).unwrap();
    assert!(parsed.logs.is_empty() && parsed.invalid > 0);

    let too_many = vec![r#"{"id":"x"}"#; MAX_LINES_PER_DELIVERY + 1];
    for body in [format!("[{}]", too_many.join(",")), too_many.join("\n")] {
        assert!(matches!(
            parse_delivery(body.as_bytes()),
            Err(DeliveryError::TooManyLines)
        ));
    }

    let empty = parse_delivery(b"  \n").unwrap();
    assert!(empty.logs.is_empty());
    assert!(parse_delivery(b"{oops").is_err());
}

#[test]
fn request_line_maps_to_semantic_attributes_and_an_access_log_body() {
    let log = |id: &str| serde_json::from_value::<VercelLog>(request_line(id)).unwrap();
    let (row, overridden) = vercel_log_to_kafka_row(log("a"), "phc_test");

    // A redelivered line gets the same row id; another line or project does not.
    assert_eq!(
        row.uuid,
        vercel_log_to_kafka_row(log("a"), "phc_test").0.uuid
    );
    assert_ne!(
        row.uuid,
        vercel_log_to_kafka_row(log("b"), "phc_test").0.uuid
    );
    assert_ne!(
        row.uuid,
        vercel_log_to_kafka_row(log("a"), "phc_other").0.uuid
    );
    // An empty id is not an id: two such lines must not share a row id.
    assert_ne!(
        vercel_log_to_kafka_row(log(""), "phc_test").0.uuid,
        vercel_log_to_kafka_row(log(""), "phc_test").0.uuid
    );

    assert!(!overridden);
    assert_eq!(row.body, "GET /docs/start?utm_source=newsletter 200");
    assert_eq!(row.service_name, "web");
    assert_eq!(
        (row.severity_text.as_str(), row.severity_number),
        ("info", 9)
    );
    for (key, value) in [
        ("http.request.method", json!("GET")),
        ("server.address", json!("example.com")),
        ("url.path", json!("/docs/start")),
        ("url.query", json!("utm_source=newsletter")),
        ("http.response.status_code", json!(200)),
        ("client.address", json!("192.0.2.10")),
        ("user_agent.original", json!("Mozilla/5.0 ExampleBot/1.0")),
        ("vercel.source", json!("static")),
        ("vercel.cache", json!("HIT")),
        ("vercel.log.id", json!("a")),
    ] {
        assert_eq!(row.attributes.get(key), Some(&value.to_string()), "{key}");
    }
    for (key, value) in [
        ("service.name", "web"),
        ("vercel.project.id", "prj_1"),
        ("vercel.deployment.id", "dpl_1"),
        ("deployment.environment.name", "production"),
    ] {
        assert_eq!(
            row.resource_attributes.get(key),
            Some(&json!(value).to_string()),
            "{key}"
        );
    }
}

#[test]
fn function_output_keeps_its_message_severity_and_trace() {
    let log: VercelLog = serde_json::from_value(json!({
        "id": "fn",
        "deploymentId": "dpl_1",
        "source": "lambda",
        "timestamp": recent_millis(),
        "projectId": "prj_1",
        "level": "error",
        "message": "Database timeout",
        "traceId": "1b02cd14bb8642fd092bc23f54c7ffcd",
        "spanId": "f24e8631bd11faa7"
    }))
    .unwrap();
    let (row, _) = vercel_log_to_kafka_row(log, "phc_test");

    assert_eq!(row.body, "Database timeout");
    assert_eq!(
        (row.severity_text.as_str(), row.severity_number),
        ("error", 17)
    );
    assert_eq!(row.service_name, "prj_1");
    assert_eq!(row.trace_id, "GwLNFLuGQv0JK8I/VMf/zQ==");
    assert_eq!(row.span_id, "8k6GMb0R+qc=");
}

#[test]
fn severity_table() {
    for (level, expected) in [
        (Some("fatal"), ("fatal", 21)),
        (Some("error"), ("error", 17)),
        (Some("warning"), ("warn", 13)),
        (Some("info"), ("info", 9)),
        (None, ("info", 9)),
    ] {
        let (text, number) = normalize_vercel_severity(level);
        assert_eq!((text.as_str(), number), expected, "{level:?}");
    }
}

#[test]
fn drain_gate_is_closed_unless_a_token_is_listed() {
    for (enabled, token, allowed) in [
        ("", "phc_a", false),
        ("phc_a", "phc_a", true),
        (" phc_a , phc_b ", "phc_b", true),
        ("phc_a", "phc_c", false),
        ("*", "phc_c", true),
    ] {
        assert_eq!(
            VercelDrainGate::new(enabled).allows(token),
            allowed,
            "{enabled:?} / {token}"
        );
    }
}

#[test]
fn only_real_http_statuses_become_the_response_status() {
    for (proxy_status, line_status, expected) in [
        (json!(200), json!(null), Some(200)),
        // Background revalidation reports -1 on the proxy; the function's 503 must survive.
        (json!(-1), json!(503), Some(503)),
        (json!(-1), json!(null), None),
        (json!(null), json!(-1), None),
    ] {
        let mut line = request_line("a");
        line["proxy"]["statusCode"] = proxy_status.clone();
        line["statusCode"] = line_status.clone();
        let log: VercelLog = serde_json::from_value(line).unwrap();
        let (row, _) = vercel_log_to_kafka_row(log, "phc_test");

        assert_eq!(
            row.attributes.get("http.response.status_code"),
            expected.map(|code| json!(code).to_string()).as_ref(),
            "{proxy_status} / {line_status}"
        );
        if proxy_status == json!(-1) {
            assert_eq!(
                row.attributes.get("vercel.proxy.status_code"),
                Some(&"-1".to_string())
            );
        }
    }
}

#[test]
fn token_comes_from_the_path_then_the_header_then_the_query() {
    for (path, auth, query, expected) in [
        (
            Some("phc_path"),
            Some("Bearer phc_header"),
            Some("phc_query"),
            Some("phc_path"),
        ),
        (
            Some(""),
            Some("Bearer phc_header"),
            None,
            Some("phc_header"),
        ),
        (None, Some("bearer phc_header "), None, Some("phc_header")),
        (None, Some("phc_bare"), None, Some("phc_bare")),
        (None, Some("Bearer "), Some("phc_query"), Some("phc_query")),
        (None, None, Some(""), None),
    ] {
        let mut headers = axum::http::HeaderMap::new();
        if let Some(value) = auth {
            headers.insert("authorization", value.parse().unwrap());
        }
        assert_eq!(
            token_from_request(path, &headers, query).as_deref(),
            expected,
            "{path:?} / {auth:?} / {query:?}"
        );
    }
}
