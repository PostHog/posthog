//! `LogsTransformerService` behavior that the parity scenarios cannot pin: wall-clock limits, fetch failures and secret shapes.

mod common;

use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use common::record_from_js;
use ingestion_framework::{IngestionOutputs, OutputMessage};
use logs_ingestion::content_weights::StagedRecord;
use logs_ingestion::js::{json_parse, JsValue};
use logs_ingestion::pipeline::LogsTransformer;
use logs_ingestion::rate_limiter::Clock;
use logs_ingestion::transformations::functions::{HogFunction, HogFunctionRow};
use logs_ingestion::transformations::{
    HogFunctionMonitoring, HogFunctionSource, LogsTransformerConfig, LogsTransformerService,
    StaticHogFunctions, TransformationBatchBudget,
};

const TEAM_ID: i64 = 7;

// let i := 0; while (true) { i := i + 1 }; return record
const RUNAWAY: &str =
    r#"["_H", 1, 33, 0, 29, 40, 9, 33, 1, 36, 0, 6, 37, 0, 39, -12, 32, "record", 1, 1, 38, 35]"#;
// let i := 0; while (i < 100000) { i := i + 1 }; return record
const BUSY: &str = r#"["_H", 1, 33, 0, 33, 100000, 36, 0, 15, 40, 9, 33, 1, 36, 0, 6, 37, 0, 39, -16, 32, "record", 1, 1, 38, 35]"#;
// let rec := record; rec.attributes.svc := inputs.svc; return rec
const TAG_SVC: &str = r#"["_H", 1, 32, "record", 1, 1, 36, 0, 32, "attributes", 45, 32, "svc", 32, "svc", 32, "inputs", 1, 2, 46, 36, 0, 38, 35]"#;
// return f'service = {record.service_name}'
const SVC_TEMPLATE: &str =
    r#"["_H", 1, 32, "service = ", 32, "service_name", 32, "record", 1, 2, 2, "concat", 2, 38]"#;
// print('token is', inputs.credentials.token, inputs.secret.a.b.c.d.e.f.g.token)
// throw Error(f'failed for {inputs.credentials.token}')
const LEAK_SECRETS: &str = r#"["_H", 1, 32, "token is", 32, "token", 32, "credentials", 32, "inputs", 1, 3, 32, "token", 32, "g", 32, "f", 32, "e", 32, "d", 32, "c", 32, "b", 32, "a", 32, "secret", 32, "inputs", 1, 10, 2, "print", 3, 35, 32, "failed for ", 32, "token", 32, "credentials", 32, "inputs", 1, 3, 2, "concat", 2, 2, "Error", 1, 49]"#;
// return record
const IDENTITY: &str = r#"["_H", 1, 32, "record", 1, 1, 38]"#;

fn js(text: &str) -> JsValue {
    json_parse(text).unwrap()
}

fn function(bytecode: &str, inputs: &str, encrypted_inputs: Option<&str>) -> Arc<HogFunction> {
    Arc::new(HogFunction::from_row(HogFunctionRow {
        id: "00000000-0000-0000-0000-000000000001".into(),
        team_id: TEAM_ID,
        name: "Test fn".into(),
        function_type: "transformation_log".into(),
        execution_order: Some(1.0),
        created_at: String::new(),
        bytecode: js(bytecode),
        inputs: js(inputs),
        encrypted_inputs: encrypted_inputs.map(js),
    }))
}

fn record(service_name: &str) -> StagedRecord {
    StagedRecord::fresh(record_from_js(&js(&format!(
        r#"{{"uuid": "u", "body": "user jane@example.com logged in", "severity_text": "info",
            "service_name": "{service_name}", "attributes": {{"user_email": "\"jane@example.com\""}}}}"#
    ))))
}

fn attribute(staged: &StagedRecord, key: &str) -> Option<String> {
    staged
        .record
        .attributes()
        .and_then(|a| a.get(key))
        .and_then(|v| v.as_str())
        .map(str::to_string)
}

#[derive(Default)]
struct Captured(Mutex<Vec<(String, String)>>);

#[async_trait]
impl IngestionOutputs for Captured {
    async fn produce(&self, output: &str, message: OutputMessage) -> anyhow::Result<()> {
        self.queue_messages(output, vec![message]).await
    }

    async fn queue_messages(
        &self,
        output: &str,
        messages: Vec<OutputMessage>,
    ) -> anyhow::Result<()> {
        let mut captured = self.0.lock().unwrap();
        for m in messages {
            let value =
                String::from_utf8_lossy(m.value.as_deref().unwrap_or_default()).into_owned();
            captured.push((output.to_string(), value));
        }
        Ok(())
    }
}

fn service(
    functions: Arc<dyn HogFunctionSource>,
    hog_timeout_ms: f64,
) -> (LogsTransformerService, Arc<Captured>) {
    let outputs = Arc::new(Captured::default());
    let clock: Clock = Arc::new(|| 1_736_944_633_250.0);
    let monitoring = Arc::new(HogFunctionMonitoring::new(
        outputs.clone(),
        clock.clone(),
        true,
    ));
    let config = LogsTransformerConfig {
        site_url: "http://localhost:8010".into(),
        hog_timeout_ms,
        message_budget_ms: 60_000.0,
        batch_budget_ms: 600_000.0,
        max_error_logs_per_function_per_message: 3,
    };
    (
        LogsTransformerService::new(functions, monitoring, config, clock),
        outputs,
    )
}

#[tokio::test]
async fn a_runaway_program_is_stopped_by_the_wall_clock_and_fails_open() {
    let (service, outputs) = service(
        Arc::new(StaticHogFunctions(vec![function(RUNAWAY, "{}", None)])),
        5.0,
    );
    let mut records = vec![record("api")];
    service
        .transform_records(TEAM_ID, &mut records, None)
        .await
        .unwrap();
    assert_eq!(
        attribute(&records[0], "$transformations_failed").as_deref(),
        Some("\"Test fn (00000000-0000-0000-0000-000000000001)\"")
    );
    service.flush().await.unwrap();
    let logs: Vec<String> = outputs
        .0
        .lock()
        .unwrap()
        .iter()
        .filter(|(o, _)| o == "log_entries")
        .map(|(_, v)| v.clone())
        .collect();
    assert_eq!(logs.len(), 1);
    assert!(
        logs[0].contains("Execution timed out after 0.005 seconds"),
        "{}",
        logs[0]
    );
}

#[tokio::test]
async fn the_batch_budget_is_shared_across_messages() {
    let (service, _) = service(
        Arc::new(StaticHogFunctions(vec![function(BUSY, "{}", None)])),
        60_000.0,
    );
    let budget = Arc::new(TransformationBatchBudget::new(0.0001));
    let mut first = vec![record("api")];
    service
        .transform_records(TEAM_ID, &mut first, Some(budget.clone()))
        .await
        .unwrap();
    assert_eq!(attribute(&first[0], "$transformations_skipped"), None);
    assert!(budget.used_ms() > 0.0);

    let mut second = vec![record("api")];
    service
        .transform_records(TEAM_ID, &mut second, Some(budget))
        .await
        .unwrap();
    assert_eq!(
        attribute(&second[0], "$transformations_skipped").as_deref(),
        Some("\"budget\"")
    );
}

#[tokio::test]
async fn record_referencing_encrypted_templates_resolve_per_record() {
    let encrypted =
        format!(r#"{{"svc": {{"value": "x", "bytecode": {SVC_TEMPLATE}, "order": 0}}}}"#);
    let (service, _) = service(
        Arc::new(StaticHogFunctions(vec![function(
            TAG_SVC,
            "{}",
            Some(&encrypted),
        )])),
        60_000.0,
    );
    let mut records = vec![record("svc-a"), record("svc-b")];
    service
        .transform_records(TEAM_ID, &mut records, None)
        .await
        .unwrap();
    assert_eq!(
        attribute(&records[0], "svc").as_deref(),
        Some("\"service = svc-a\"")
    );
    assert_eq!(
        attribute(&records[1], "svc").as_deref(),
        Some("\"service = svc-b\"")
    );
}

// Secret inputs accept any JSON, so redaction must reach string leaves at any depth and in the thrown text.
#[tokio::test]
async fn nested_secrets_are_redacted_from_print_and_error_logs() {
    let encrypted = r#"{
        "credentials": {"value": {"token": "nested-secret-token"}, "order": 0},
        "secret": {"value": {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"token": "very-deep-secret"}}}}}}}}, "order": 1}
    }"#;
    let (service, outputs) = service(
        Arc::new(StaticHogFunctions(vec![function(
            LEAK_SECRETS,
            "{}",
            Some(encrypted),
        )])),
        60_000.0,
    );
    let mut records = vec![record("api")];
    service
        .transform_records(TEAM_ID, &mut records, None)
        .await
        .unwrap();
    service.flush().await.unwrap();
    let logs = outputs.0.lock().unwrap().clone();
    let text: Vec<&str> = logs
        .iter()
        .filter(|(o, _)| o == "log_entries")
        .map(|(_, v)| v.as_str())
        .collect();
    assert_eq!(text.len(), 2);
    for entry in text {
        assert!(entry.contains("***REDACTED***"), "{entry}");
        assert!(!entry.contains("secret"), "{entry}");
    }
}

#[tokio::test]
async fn a_very_large_secret_array_does_not_fail_the_function() {
    let secrets: Vec<String> = (0..150_000).map(|i| format!("\"secret-{i}\"")).collect();
    let encrypted = format!(
        r#"{{"many": {{"value": [{}], "order": 0}}}}"#,
        secrets.join(",")
    );
    let (service, _) = service(
        Arc::new(StaticHogFunctions(vec![function(
            IDENTITY,
            "{}",
            Some(&encrypted),
        )])),
        60_000.0,
    );
    let mut records = vec![record("api")];
    service
        .transform_records(TEAM_ID, &mut records, None)
        .await
        .unwrap();
    assert_eq!(attribute(&records[0], "$transformations_failed"), None);
}

struct FailingSource;

#[async_trait]
impl HogFunctionSource for FailingSource {
    async fn transformation_ids(&self, _team_id: i64) -> anyhow::Result<Vec<String>> {
        anyhow::bail!("pg down")
    }
    async fn transformations(&self, _team_id: i64) -> anyhow::Result<Vec<Arc<HogFunction>>> {
        anyhow::bail!("pg down")
    }
}

// A fetch error must not fail the message into the DLQ; records pass through untransformed.
#[tokio::test]
async fn function_fetch_failures_fail_open() {
    let (service, _) = service(Arc::new(FailingSource), 60_000.0);
    assert!(!service.team_has_transformations(TEAM_ID).await.unwrap());
    let mut records = vec![record("api"), record("api")];
    let before = records.clone();
    service
        .transform_records(TEAM_ID, &mut records, None)
        .await
        .unwrap();
    assert_eq!(records, before);
}
