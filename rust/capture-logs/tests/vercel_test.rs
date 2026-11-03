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
    let lines = [
        request_line("a"),
        json!({"id": "b", "timestamp": "not a number"}),
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
        assert_eq!(ids, ["a", "c"]);
        assert_eq!(parsed.invalid, 1);
    }

    let single = parse_delivery(request_line("only").to_string().as_bytes()).unwrap();
    assert_eq!(single.logs.len(), 1);

    let empty = parse_delivery(b"  \n").unwrap();
    assert!(empty.logs.is_empty());
    assert!(parse_delivery(b"{oops").is_err());
}

#[test]
fn request_line_maps_to_semantic_attributes_and_an_access_log_body() {
    let log: VercelLog = serde_json::from_value(request_line("a")).unwrap();
    let (row, overridden) = vercel_log_to_kafka_row(log);

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
    let (row, _) = vercel_log_to_kafka_row(log);

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
