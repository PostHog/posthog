use axum::http::StatusCode;
use axum_test_helper::TestClient;
use base64::engine::general_purpose;
use base64::Engine;
use capture::event::ProcessedEvent;
use capture::router::router;
use serde::Deserialize;
use std::fs::File;
use std::io::{BufRead, BufReader};

#[derive(Debug, Deserialize)]
struct RequestDump {
    path: String,
    method: String,
    content_encoding: String,
    content_type: String,
    ip: String,
    now: String,
    body: String,
    output: Vec<ProcessedEvent>,
}

static REQUESTS_DUMP_FILE_NAME: &str = "tests/requests_dump.jsonl";

#[tokio::test]
async fn it_matches_django_capture_behaviour() -> anyhow::Result<()> {
    let file = File::open(REQUESTS_DUMP_FILE_NAME)?;
    let reader = BufReader::new(file);

    for line in reader.lines() {
        let case: RequestDump = serde_json::from_str(&line?)?;

        if !case.path.starts_with("/e/") {
            println!("Skipping {} test case", &case.path);
            continue;
        }

        let raw_body = general_purpose::STANDARD.decode(&case.body)?;
        assert_eq!(
            case.method, "POST",
            "update code to handle method {}",
            case.method
        );

        let app = router();
        let client = TestClient::new(app);
        let mut req = client.post(&case.path).body(raw_body);
        if !case.content_encoding.is_empty() {
            req = req.header("Content-encoding", case.content_encoding);
        }
        if !case.content_type.is_empty() {
            req = req.header("Content-type", case.content_type);
        }
        if !case.ip.is_empty() {
            req = req.header("X-Forwarded-For", case.ip);
        }
        let res = req.send().await;

        assert_eq!(res.status(), StatusCode::OK, "{}", res.text().await);
    }
    Ok(())
}
