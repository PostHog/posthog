mod common;

use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use common::record_from_js;
use ingestion_framework::{IngestionOutputs, OutputMessage};
use logs_ingestion::content_weights::StagedRecord;
use logs_ingestion::js::{json_parse, JsValue};
use logs_ingestion::pipeline::LogsTransformer;
use logs_ingestion::rate_limiter::Clock;
use logs_ingestion::transformations::exec::redact_sensitive_values;
use logs_ingestion::transformations::functions::{HogFunction, HogFunctionRow};
use logs_ingestion::transformations::{
    HogFunctionMonitoring, HogFunctionSource, LogsTransformerConfig, LogsTransformerService,
    StaticHogFunctions, TransformationBatchBudget,
};

const TEAM_ID: i64 = 7;

const RUNAWAY: &str =
    r#"["_H", 1, 33, 0, 29, 40, 9, 33, 1, 36, 0, 6, 37, 0, 39, -12, 32, "record", 1, 1, 38, 35]"#;
const BUSY: &str = r#"["_H", 1, 33, 0, 33, 100000, 36, 0, 15, 40, 9, 33, 1, 36, 0, 6, 37, 0, 39, -16, 32, "record", 1, 1, 38, 35]"#;
// let rec := record; rec.attributes.svc := inputs.svc; return rec
const TAG_SVC: &str = r#"["_H", 1, 32, "record", 1, 1, 36, 0, 32, "attributes", 45, 32, "svc", 32, "svc", 32, "inputs", 1, 2, 46, 36, 0, 38, 35]"#;
// return f'service = {record.service_name}'
const SVC_TEMPLATE: &str =
    r#"["_H", 1, 32, "service = ", 32, "service_name", 32, "record", 1, 2, 2, "concat", 2, 38]"#;
// print('token is', inputs.credentials.token, inputs.secret.a.b.c.d.e.f.g.token); throw Error(f'failed for {inputs.credentials.token}')
const LEAK_SECRETS: &str = r#"["_H", 1, 32, "token is", 32, "token", 32, "credentials", 32, "inputs", 1, 3, 32, "token", 32, "g", 32, "f", 32, "e", 32, "d", 32, "c", 32, "b", 32, "a", 32, "secret", 32, "inputs", 1, 10, 2, "print", 3, 35, 32, "failed for ", 32, "token", 32, "credentials", 32, "inputs", 1, 3, 2, "concat", 2, 2, "Error", 1, 49]"#;
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
    let clock: Clock = Arc::new(|| 1_736_944_633_250.0);
    service_with(functions, hog_timeout_ms, 60_000.0, clock)
}

fn service_with(
    functions: Arc<dyn HogFunctionSource>,
    hog_timeout_ms: f64,
    message_budget_ms: f64,
    clock: Clock,
) -> (LogsTransformerService, Arc<Captured>) {
    let outputs = Arc::new(Captured::default());
    let monitoring = Arc::new(HogFunctionMonitoring::new(
        outputs.clone(),
        clock.clone(),
        true,
    ));
    let config = LogsTransformerConfig {
        site_url: "http://localhost:8010".into(),
        hog_timeout_ms,
        message_budget_ms,
        batch_budget_ms: 600_000.0,
        batch_deadline_ms: f64::INFINITY,
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
        attribute(&records[0], "posthog.transformations_failed").as_deref(),
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
async fn the_batch_budget_is_shared_across_messages_of_one_team_only() {
    let other_team_function = HogFunction {
        team_id: TEAM_ID + 1,
        ..(*function(BUSY, "{}", None)).clone()
    };
    let (service, _) = service(
        Arc::new(StaticHogFunctions(vec![
            function(BUSY, "{}", None),
            Arc::new(other_team_function),
        ])),
        60_000.0,
    );
    let budget = Arc::new(TransformationBatchBudget::new(0.0001, f64::INFINITY));
    let mut first = vec![record("api")];
    service
        .transform_records(TEAM_ID, &mut first, Some(budget.clone()))
        .await
        .unwrap();
    assert_eq!(
        attribute(&first[0], "posthog.transformations_skipped"),
        None
    );
    assert!(budget.used_ms() > 0.0);

    let mut second = vec![record("api")];
    service
        .transform_records(TEAM_ID, &mut second, Some(budget.clone()))
        .await
        .unwrap();
    assert_eq!(
        attribute(&second[0], "posthog.transformations_skipped").as_deref(),
        Some("\"budget\"")
    );

    let used_by_first_team = budget.used_ms();
    let mut other_team = vec![record("api")];
    service
        .transform_records(TEAM_ID + 1, &mut other_team, Some(budget.clone()))
        .await
        .unwrap();
    assert_eq!(
        attribute(&other_team[0], "posthog.transformations_skipped"),
        None
    );
    assert!(budget.used_ms() > used_by_first_team);
}

#[tokio::test]
async fn the_batch_deadline_stops_every_team() {
    let (service, _) = service(
        Arc::new(StaticHogFunctions(vec![function(BUSY, "{}", None)])),
        60_000.0,
    );
    let budget = Arc::new(TransformationBatchBudget::new(60_000.0, 0.0));
    let mut records = vec![record("api")];
    service
        .transform_records(TEAM_ID, &mut records, Some(budget))
        .await
        .unwrap();
    assert_eq!(
        attribute(&records[0], "posthog.transformations_skipped").as_deref(),
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

#[tokio::test]
async fn nested_secrets_are_redacted_from_print_and_error_logs() {
    let encrypted = r#"{
        "credentials": {"value": {"token": "nested'secret-token"}, "order": 0},
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
    assert_eq!(
        attribute(&records[0], "posthog.transformations_failed"),
        None
    );
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

// let rec := record; rec.body := replaceAll(inputs.s, '', inputs.t); return rec
const REPLACE_EMPTY: &str = r#"["_H", 1, 32, "record", 1, 1, 36, 0, 32, "body", 32, "s", 32, "inputs", 1, 2, 32, "", 32, "t", 32, "inputs", 1, 2, 2, "replaceAll", 3, 46, 36, 0, 38, 35]"#;
// let rec := record; rec.body := inputs.stars; return rec
const STARS: &str = r#"["_H", 1, 32, "record", 1, 1, 36, 0, 32, "body", 32, "stars", 32, "inputs", 1, 2, 46, 36, 0, 38, 35]"#;
// let rec := record; rec.attributes.m := (-4611686018427387904 * 2) % -1; return rec
const MIN_MOD: &str = r#"["_H", 1, 32, "record", 1, 1, 36, 0, 32, "attributes", 45, 32, "m", 33, -1, 33, 2, 33, -4611686018427387904, 8, 10, 46, 36, 0, 38, 35]"#;
// let n := 0; 300 times: n := n + length(keys(record.attributes)); let rec := record; rec.attributes.n := n; return rec
const REREAD: &str = r#"["_H", 1, 33, 0, 33, 0, 33, 300, 36, 1, 15, 40, 26, 32, "attributes", 32, "record", 1, 2, 2, "keys", 1, 2, "length", 1, 36, 0, 6, 37, 0, 33, 1, 36, 1, 6, 37, 1, 39, -33, 35, 32, "record", 1, 1, 36, 1, 32, "attributes", 45, 32, "n", 36, 0, 46, 36, 1, 38, 35, 35]"#;
// let a := {'x': 1}; for (let i := 0; i < 22; i := i + 1) { a := {'l': a, 'r': a} }; print(a); return record
const DAG: &str = r#"["_H", 1, 32, "x", 33, 1, 42, 1, 33, 0, 33, 22, 36, 1, 15, 40, 21, 32, "l", 36, 0, 32, "r", 36, 0, 42, 2, 37, 0, 33, 1, 36, 1, 6, 37, 1, 39, -28, 35, 36, 0, 2, "print", 1, 35, 32, "record", 1, 1, 38, 35]"#;

// let a := []; for (let i := 0; i < 20000; i := i + 1) { a := [a] }; let rec := record; rec.attributes.deep := a; return rec
const DEEP: &str = r#"["_H", 1, 43, 0, 33, 0, 33, 20000, 36, 1, 15, 40, 15, 36, 0, 43, 1, 37, 0, 33, 1, 36, 1, 6, 37, 1, 39, -22, 35, 32, "record", 1, 1, 36, 1, 32, "attributes", 45, 32, "deep", 36, 0, 46, 36, 1, 38, 35, 35]"#;
// print(record.body, record.body, ... ten times); return record
const PRINT_BODY_TEN_TIMES: &str = r#"["_H", 1, 32, "body", 32, "record", 1, 2, 32, "body", 32, "record", 1, 2, 32, "body", 32, "record", 1, 2, 32, "body", 32, "record", 1, 2, 32, "body", 32, "record", 1, 2, 32, "body", 32, "record", 1, 2, 32, "body", 32, "record", 1, 2, 32, "body", 32, "record", 1, 2, 32, "body", 32, "record", 1, 2, 32, "body", 32, "record", 1, 2, 2, "print", 10, 35, 32, "record", 1, 1, 38]"#;

async fn run_one(function: Arc<HogFunction>, mut records: Vec<StagedRecord>) -> Vec<StagedRecord> {
    let (service, _) = service(Arc::new(StaticHogFunctions(vec![function])), 60_000.0);
    service
        .transform_records(TEAM_ID, &mut records, None)
        .await
        .unwrap();
    records
}

fn failed(staged: &StagedRecord) -> bool {
    attribute(staged, "posthog.transformations_failed").is_some()
}

#[tokio::test]
async fn oversized_results_fail_the_invocation_instead_of_allocating() {
    let replace = format!(
        r#"{{"s": {{"value": "{}"}}, "t": {{"value": "{}"}}}}"#,
        "y".repeat(1000),
        "x".repeat(1024 * 1024)
    );
    let stars = format!(r#"{{"stars": {{"value": "{}"}}}}"#, "*".repeat(700 * 1024));
    let cases = [
        function(REPLACE_EMPTY, &replace, None),
        // A one-character secret that occurs in the redaction marker grows the body fourteenfold.
        function(STARS, &stars, Some(r#"{"secret": {"value": "*"}}"#)),
        // Shared references expand on every visit: printing 22 nested objects writes 2^22 leaves.
        function(DAG, "{}", None),
        function(DEEP, "{}", None),
    ];
    for f in cases {
        let records = run_one(f, vec![record("api")]).await;
        assert!(failed(&records[0]));
        assert_eq!(
            records[0].record.body(),
            Some("user jane@example.com logged in")
        );
    }
}

#[tokio::test]
async fn integer_edge_cases_run_without_a_panic() {
    let records = run_one(function(MIN_MOD, "{}", None), vec![record("api")]).await;
    assert_eq!(attribute(&records[0], "m").as_deref(), Some("0"));
}

#[tokio::test]
async fn rereading_a_large_record_stays_inside_the_memory_limit() {
    let attributes: Vec<String> = (0..200)
        .map(|i| format!(r#""attr_{i}": "\"{}\"""#, "v".repeat(200)))
        .collect();
    let staged = StagedRecord::fresh(record_from_js(&js(&format!(
        r#"{{"uuid": "u", "body": "b", "attributes": {{{}}}}}"#,
        attributes.join(",")
    ))));
    let records = run_one(function(REREAD, "{}", None), vec![staged]).await;
    assert!(
        !failed(&records[0]),
        "{:?}",
        attribute(&records[0], "posthog.transformations_failed")
    );
    assert_eq!(attribute(&records[0], "n").as_deref(), Some("60000"));
}

#[tokio::test]
async fn a_failed_input_template_spends_the_budgets() {
    let inputs = format!(r#"{{"slow": {{"value": "", "bytecode": {RUNAWAY}}}}}"#);
    let (service, _) = service(
        Arc::new(StaticHogFunctions(vec![function(IDENTITY, &inputs, None)])),
        5.0,
    );
    let budget = Arc::new(TransformationBatchBudget::new(0.0001, f64::INFINITY));
    let mut records = vec![record("api"), record("api")];
    service
        .transform_records(TEAM_ID, &mut records, Some(budget))
        .await
        .unwrap();
    assert!(failed(&records[0]));
    assert_eq!(
        attribute(&records[1], "posthog.transformations_skipped").as_deref(),
        Some("\"budget\"")
    );
}

// let arr := range(64); for i in 1..=64: arr[i] := record.body; let rec := record; rec.attributes.h := sha256HmacChainHex(arr); return rec
const HASH_MANY_BODIES: &str = r#"["_H", 1, 33, 64, 2, "range", 1, 33, 1, 33, 64, 36, 1, 16, 40, 20, 36, 0, 36, 1, 32, "body", 32, "record", 1, 2, 46, 33, 1, 36, 1, 6, 37, 1, 39, -27, 35, 32, "record", 1, 1, 36, 1, 32, "attributes", 45, 32, "h", 36, 0, 2, "sha256HmacChainHex", 1, 46, 36, 1, 38, 35, 35]"#;

#[tokio::test]
async fn a_native_call_does_not_read_many_references_to_one_large_string() {
    let staged = StagedRecord::fresh(record_from_js(&js(&format!(
        r#"{{"uuid": "u", "body": "{}"}}"#,
        "b".repeat(900 * 1024)
    ))));
    let records = run_one(function(HASH_MANY_BODIES, "{}", None), vec![staged]).await;
    assert!(failed(&records[0]));
}

// fun make(big) { return (x) -> big }; let held := []; 20 times: held := arrayPushBack(held, make(concat(record.body, 'x')))
const HOLD_BODIES_IN_CLOSURES: &str = r#"["_H", 1, 52, "make", 1, 0, 13, 52, "lambda", 1, 1, 3, 55, 0, 38, 53, 1, true, 0, 38, 53, 0, 43, 0, 33, 0, 33, 20, 36, 2, 15, 40, 31, 36, 1, 32, "body", 32, "record", 1, 2, 32, "x", 2, "concat", 2, 36, 0, 54, 1, 2, "arrayPushBack", 2, 37, 1, 33, 1, 36, 2, 6, 37, 2, 39, -38, 35, 32, "record", 1, 1, 38, 35, 35]"#;

#[tokio::test]
async fn strings_that_closures_capture_count_toward_the_memory_limit() {
    let staged = StagedRecord::fresh(record_from_js(&js(&format!(
        r#"{{"uuid": "u", "body": "{}"}}"#,
        "b".repeat(900 * 1024)
    ))));
    let records = run_one(function(HOLD_BODIES_IN_CLOSURES, "{}", None), vec![staged]).await;
    assert!(failed(&records[0]));
}

// `a := [a, a]` 21 times, then `rec.attributes.n := length(a)`.
const LENGTH_OF_SHARED_PAIRS: &str = r#"["_H", 1, 33, 1, 43, 1, 33, 0, 33, 21, 36, 1, 15, 40, 17, 36, 0, 36, 0, 43, 2, 37, 0, 33, 1, 36, 1, 6, 37, 1, 39, -24, 35, 32, "record", 1, 1, 36, 1, 32, "attributes", 45, 32, "n", 36, 0, 2, "length", 1, 46, 36, 1, 38, 35, 35]"#;

#[tokio::test]
async fn the_check_before_a_native_call_stops_on_values_that_hold_each_other() {
    let records = run_one(
        function(LENGTH_OF_SHARED_PAIRS, "{}", None),
        vec![record("api")],
    )
    .await;
    assert!(failed(&records[0]));
}

#[tokio::test]
async fn print_arguments_share_one_size_limit() {
    let staged = StagedRecord::fresh(record_from_js(&js(&format!(
        r#"{{"uuid": "u", "body": "{}"}}"#,
        "b".repeat(900 * 1024)
    ))));
    let records = run_one(function(PRINT_BODY_TEN_TIMES, "{}", None), vec![staged]).await;
    assert!(failed(&records[0]));
}

#[tokio::test]
async fn messages_of_a_batch_run_one_at_a_time_against_the_batch_budget() {
    let (service, _) = service(
        Arc::new(StaticHogFunctions(vec![function(BUSY, "{}", None)])),
        60_000.0,
    );
    let budget = Arc::new(TransformationBatchBudget::new(0.0001, f64::INFINITY));
    let mut messages: Vec<Vec<StagedRecord>> = (0..8).map(|_| vec![record("api")]).collect();
    futures::future::join_all(
        messages
            .iter_mut()
            .map(|records| service.transform_records(TEAM_ID, records, Some(budget.clone()))),
    )
    .await;
    let transformed = messages
        .iter()
        .filter(|records| attribute(&records[0], "posthog.transformations_skipped").is_none())
        .count();
    assert_eq!(transformed, 1);
}

#[tokio::test]
async fn a_timeout_too_large_for_the_clock_is_no_deadline() {
    let (service, _) = service(
        Arc::new(StaticHogFunctions(vec![function(
            TAG_SVC,
            r#"{"svc": {"value": "x"}}"#,
            None,
        )])),
        f64::INFINITY,
    );
    let mut records = vec![record("api")];
    service
        .transform_records(TEAM_ID, &mut records, None)
        .await
        .unwrap();
    assert_eq!(attribute(&records[0], "svc").as_deref(), Some("\"x\""));
}

#[test]
fn redaction_stops_at_the_length_the_log_line_keeps() {
    let redacted = redact_sensitive_values(&"x".repeat(100_000), &["x".to_string()], 100);
    assert!(redacted.len() < 200, "{}", redacted.len());
}

fn secret_inputs(count: usize) -> String {
    let secrets: Vec<String> = (0..count).map(|i| format!("\"secret-{i}\"")).collect();
    format!(
        r#"{{"many": {{"value": [{}], "order": 0}}}}"#,
        secrets.join(",")
    )
}

#[test]
fn a_log_line_that_too_many_secrets_would_scan_is_redacted_whole() {
    let secrets: Vec<String> = (0..150_000).map(|i| format!("secret-{i}")).collect();
    let redacted = redact_sensitive_values("no secret here", &secrets, 10_000);
    assert_eq!(redacted, "***REDACTED***");
}

#[tokio::test]
async fn a_result_that_too_many_secrets_would_scan_fails_the_invocation() {
    let staged = StagedRecord::fresh(record_from_js(&js(&format!(
        r#"{{"uuid": "u", "body": "{}"}}"#,
        "b".repeat(900 * 1024)
    ))));
    let records = run_one(
        function(IDENTITY, "{}", Some(&secret_inputs(2_000))),
        vec![staged],
    )
    .await;
    assert!(failed(&records[0]));
}

// throw Error(record.body)
const THROW_BODY: &str = r#"["_H", 1, 32, "body", 32, "record", 1, 2, 2, "Error", 1, 49]"#;

#[tokio::test]
async fn the_redaction_of_an_error_log_spends_the_budgets() {
    let ticks = Arc::new(std::sync::atomic::AtomicU64::new(0));
    let clock: Clock = Arc::new(move || {
        600_000.0 * ticks.fetch_add(1, std::sync::atomic::Ordering::SeqCst) as f64
    });
    let (service, _) = service_with(
        Arc::new(StaticHogFunctions(vec![function(
            THROW_BODY,
            "{}",
            Some(&secret_inputs(1)),
        )])),
        60_000.0,
        f64::INFINITY,
        clock,
    );
    let budget = Arc::new(TransformationBatchBudget::new(f64::INFINITY, f64::INFINITY));
    service
        .transform_records(TEAM_ID, &mut vec![record("api")], Some(budget.clone()))
        .await
        .unwrap();
    assert!(budget.used_ms() >= 600_000.0, "{}", budget.used_ms());
}

#[test]
fn a_log_line_stops_at_the_bytes_that_long_secrets_compare() {
    let secrets: Vec<String> = (0..200)
        .map(|i| format!("{}{i}", "a".repeat(4096)))
        .collect();
    let redacted = redact_sensitive_values(&"a".repeat(20_000), &secrets, 10_000);
    assert_eq!(redacted, "***REDACTED***");
}

#[tokio::test]
async fn a_result_that_grows_under_redaction_counts_its_new_length() {
    let stars = ["\"*\""; 7].join(",");
    let others: Vec<String> = (0..2_000).map(|i| format!("\"z{i}\"")).collect();
    // The leaves of an array are read from its end, so the stars are the first secrets.
    let encrypted = format!(
        r#"{{"many": {{"value": [{},{stars}], "order": 0}}}}"#,
        others.join(",")
    );
    let staged = StagedRecord::fresh(record_from_js(&js(r#"{"uuid": "u", "body": "*"}"#)));
    let records = run_one(function(IDENTITY, "{}", Some(&encrypted)), vec![staged]).await;
    assert!(failed(&records[0]));
}

// return record.body
const BODY_TEMPLATE: &str = r#"["_H", 1, 32, "body", 32, "record", 1, 2, 38]"#;

fn body_inputs(count: usize) -> String {
    let inputs: Vec<String> = (0..count)
        .map(|i| format!(r#""in{i}": {{"value": "", "bytecode": {BODY_TEMPLATE}}}"#))
        .collect();
    format!("{{{}}}", inputs.join(","))
}

#[tokio::test]
async fn input_templates_share_one_size_limit_and_one_time_budget() {
    let staged = StagedRecord::fresh(record_from_js(&js(&format!(
        r#"{{"uuid": "u", "body": "{}"}}"#,
        "b".repeat(900 * 1024)
    ))));
    let records = run_one(function(IDENTITY, &body_inputs(80), None), vec![staged]).await;
    assert!(failed(&records[0]));

    let clock: Clock = Arc::new(|| 0.0);
    let (service, _) = service_with(
        Arc::new(StaticHogFunctions(vec![function(
            IDENTITY,
            &body_inputs(2),
            None,
        )])),
        60_000.0,
        1e-9,
        clock,
    );
    let mut records = vec![record("api")];
    service
        .transform_records(TEAM_ID, &mut records, None)
        .await
        .unwrap();
    assert!(failed(&records[0]));
}
