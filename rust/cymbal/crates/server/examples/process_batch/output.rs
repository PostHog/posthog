use cymbal_api::cymbal::v1::{
    process_exception_batch_result, Drop, EnrichedExceptionEvent, ProcessExceptionBatchRequest,
    ProcessExceptionBatchResult, ProcessingError, Retry,
};

pub const RULE: &str = "────────────────────────────────────────────────────────────────────────";
const EVENT_ID_WIDTH: usize = 24;
const DETAIL_WIDTH: usize = 76;
pub const RESET: &str = "\x1b[0m";
pub const BOLD: &str = "\x1b[1m";
pub const DIM: &str = "\x1b[2m";
pub const GREEN: &str = "\x1b[32m";
pub const YELLOW: &str = "\x1b[33m";
pub const RED: &str = "\x1b[31m";
pub const BLUE: &str = "\x1b[34m";
pub const CYAN: &str = "\x1b[36m";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Verbosity {
    Compact,
    Info,
    Debug,
}

impl Verbosity {
    pub fn from_env() -> Self {
        std::env::var("CYMBAL_EXAMPLE_VERBOSITY")
            .ok()
            .as_deref()
            .map(Self::from_value)
            .unwrap_or(Self::Debug)
    }

    pub fn from_value(value: &str) -> Self {
        match value.trim().to_ascii_lowercase().as_str() {
            "compact" | "c" => Self::Compact,
            "info" | "i" => Self::Info,
            "debug" | "d" => Self::Debug,
            _ => Self::Debug,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Compact => "compact",
            Self::Info => "info",
            Self::Debug => "debug",
        }
    }
}

pub fn log_request(label: &str, request: &ProcessExceptionBatchRequest, verbosity: Verbosity) {
    match verbosity {
        Verbosity::Compact => {}
        Verbosity::Info => {
            println!("{BOLD}{BLUE}▶ {label}{RESET}");
            println!(
                "  {DIM}request{RESET} batch={CYAN}{}{RESET} events={YELLOW}{}{RESET}",
                batch_id(request),
                request.events.len(),
            );
        }
        Verbosity::Debug => log_request_debug(label, request),
    }
}

fn log_request_debug(label: &str, request: &ProcessExceptionBatchRequest) {
    println!("{BOLD}{BLUE}▶ {label}{RESET}");
    println!(
        "  {DIM}request{RESET} batch={CYAN}{}{RESET} events={YELLOW}{}{RESET}",
        batch_id(request),
        request.events.len(),
    );
    println!(
        "  {DIM}{:<EVENT_ID_WIDTH$} {:>4} {:>7}  message{RESET}",
        "event_id", "team", "bytes"
    );
    for event in request.events.iter().take(8) {
        println!(
            "  {:<EVENT_ID_WIDTH$} {:>4} {:>7}  {}",
            truncate(&event.event_id, EVENT_ID_WIDTH),
            event.team_id,
            event.properties_json.len(),
            payload_message(&event.properties_json)
        );
    }
    if request.events.len() > 8 {
        println!("  … {} more events", request.events.len() - 8);
    }
}

pub fn log_results(results: &[ProcessExceptionBatchResult], verbosity: Verbosity) {
    let counts = OutcomeCounts::from_results(results);
    match verbosity {
        Verbosity::Compact => {}
        Verbosity::Info | Verbosity::Debug => {
            println!(
                "  {DIM}response{RESET} total={YELLOW}{}{RESET} ✓={} ↓={} ↻={} ✗={} ?={}",
                results.len(),
                counts.next,
                counts.drop,
                counts.retry,
                counts.error,
                counts.missing,
            );
            if matches!(verbosity, Verbosity::Info) {
                println!("  {DIM}sample{RESET} {}", outcome_preview(results, 5));
            } else {
                log_result_table(results);
            }
        }
    }
}

fn log_result_table(results: &[ProcessExceptionBatchResult]) {
    println!(
        "  {DIM}{:<EVENT_ID_WIDTH$} {:<3} {:>7}  details{RESET}",
        "event_id", "out", "bytes"
    );
    for result in results {
        let summary = ResultSummary::from_result(result);
        println!(
            "  {:<EVENT_ID_WIDTH$} {:<3} {:>7}  {}",
            truncate(&result.event_id, EVENT_ID_WIDTH),
            summary.outcome_label,
            summary.payload_bytes,
            truncate(&summary.details, DETAIL_WIDTH),
        );
    }
}

pub fn log_expected_error(label: &str, error: &tonic::Status, verbosity: Verbosity) {
    match verbosity {
        Verbosity::Compact => {}
        Verbosity::Info | Verbosity::Debug => {
            println!("  {YELLOW}expected error{RESET} case={label}");
            println!("    {DIM}code{RESET}    {YELLOW}{}{RESET}", error.code());
            println!("    {DIM}message{RESET} {}", error.message());
        }
    }
}

pub fn log_success(
    label: &str,
    description: &str,
    results: Option<&[ProcessExceptionBatchResult]>,
    verbosity: Verbosity,
) {
    match verbosity {
        Verbosity::Compact => {
            if let Some(results) = results {
                println!(
                    "{GREEN}PASS{RESET} {label} · {} · {DIM}{description}{RESET}",
                    compact_counts(results)
                );
            } else {
                println!("{GREEN}PASS{RESET} {label} · {DIM}{description}{RESET}");
            }
        }
        Verbosity::Info => println!("  {DIM}status{RESET} {GREEN}PASS{RESET} {label}"),
        Verbosity::Debug => {
            println!("  {DIM}status{RESET} {GREEN}PASS{RESET} {label}");
            println!("{DIM}{}{RESET}", RULE);
        }
    }
}

pub fn log_failure(label: &str, error: &dyn std::error::Error, verbosity: Verbosity) {
    match verbosity {
        Verbosity::Compact => println!(
            "  {RED}FAIL{RESET} {label}: {}",
            truncate(&error.to_string(), 100)
        ),
        Verbosity::Info | Verbosity::Debug => {
            println!("  {DIM}status{RESET} {RED}FAIL{RESET} {label}");
            println!("  {DIM}error{RESET}  {error}");
        }
    }
}

pub fn log_summary(passed: usize, failed: usize, skipped: usize) {
    let status = if failed == 0 {
        format!("{GREEN}PASS{RESET}")
    } else {
        format!("{RED}FAIL{RESET}")
    };
    println!(
        "{BOLD}summary{RESET} {status} passed={GREEN}{passed}{RESET} failed={RED}{failed}{RESET} skipped={YELLOW}{skipped}{RESET}"
    );
}

#[derive(Debug, PartialEq, Eq)]
struct ResultSummary {
    outcome_label: String,
    payload_bytes: String,
    details: String,
}

impl ResultSummary {
    fn from_result(result: &ProcessExceptionBatchResult) -> Self {
        match &result.outcome {
            Some(process_exception_batch_result::Outcome::Next(next)) => Self::from_next(next),
            Some(process_exception_batch_result::Outcome::Drop(drop)) => Self::from_drop(drop),
            Some(process_exception_batch_result::Outcome::Retry(retry)) => Self::from_retry(retry),
            Some(process_exception_batch_result::Outcome::Error(error)) => Self::from_error(error),
            None => Self {
                outcome_label: format!("{RED}?{RESET}"),
                payload_bytes: "-".to_string(),
                details: "missing outcome".to_string(),
            },
        }
    }

    fn from_next(next: &EnrichedExceptionEvent) -> Self {
        let details = next_payload_details(&next.properties_json, next.metadata.len());
        Self {
            outcome_label: format!("{GREEN}✓{RESET}"),
            payload_bytes: next.properties_json.len().to_string(),
            details,
        }
    }

    fn from_drop(drop: &Drop) -> Self {
        Self {
            outcome_label: format!("{YELLOW}↓{RESET}"),
            payload_bytes: "-".to_string(),
            details: format!("reason={}", drop.reason),
        }
    }

    fn from_retry(retry: &Retry) -> Self {
        Self {
            outcome_label: format!("{YELLOW}↻{RESET}"),
            payload_bytes: "-".to_string(),
            details: format!(
                "retry_after_ms={} reason={}",
                retry.retry_after_ms, retry.reason
            ),
        }
    }

    fn from_error(error: &ProcessingError) -> Self {
        Self {
            outcome_label: format!("{RED}✗{RESET}"),
            payload_bytes: "-".to_string(),
            details: format!(
                "code={} retryable={} message={}",
                error.code, error.retryable, error.message
            ),
        }
    }
}

#[derive(Default)]
struct OutcomeCounts {
    next: usize,
    drop: usize,
    retry: usize,
    error: usize,
    missing: usize,
}

impl OutcomeCounts {
    fn from_results(results: &[ProcessExceptionBatchResult]) -> Self {
        let mut counts = Self::default();
        for result in results {
            match &result.outcome {
                Some(process_exception_batch_result::Outcome::Next(_)) => counts.next += 1,
                Some(process_exception_batch_result::Outcome::Drop(_)) => counts.drop += 1,
                Some(process_exception_batch_result::Outcome::Retry(_)) => counts.retry += 1,
                Some(process_exception_batch_result::Outcome::Error(_)) => counts.error += 1,
                None => counts.missing += 1,
            }
        }
        counts
    }
}

fn compact_counts(results: &[ProcessExceptionBatchResult]) -> String {
    let counts = OutcomeCounts::from_results(results);
    let mut parts = Vec::new();
    if counts.next > 0 {
        parts.push(format!("{GREEN}✓{}{RESET}", counts.next));
    }
    if counts.drop > 0 {
        parts.push(format!("{YELLOW}↓{}{RESET}", counts.drop));
    }
    if counts.retry > 0 {
        parts.push(format!("{YELLOW}↻{}{RESET}", counts.retry));
    }
    if counts.error > 0 {
        parts.push(format!("{RED}✗{}{RESET}", counts.error));
    }
    if counts.missing > 0 {
        parts.push(format!("{RED}?{}{RESET}", counts.missing));
    }
    if parts.is_empty() {
        return "∅".to_string();
    }
    parts.join(" ")
}

fn outcome_preview(results: &[ProcessExceptionBatchResult], limit: usize) -> String {
    if results.is_empty() {
        return "<empty>".to_string();
    }

    let mut parts = results
        .iter()
        .take(limit)
        .map(|result| {
            let summary = ResultSummary::from_result(result);
            format!(
                "{}:{}",
                truncate(&result.event_id, 16),
                summary.outcome_label
            )
        })
        .collect::<Vec<_>>();
    if results.len() > limit {
        parts.push(format!("…{} more", results.len() - limit));
    }
    parts.join(" ")
}

fn next_payload_details(properties_json: &[u8], metadata_keys: usize) -> String {
    let Ok(payload) = serde_json::from_slice::<serde_json::Value>(properties_json) else {
        return format!("metadata_keys={metadata_keys} payload=<non-json>");
    };

    let message = json_string(&payload, "/$exception_message")
        .or_else(|| json_string(&payload, "/message"))
        .unwrap_or_else(|| "<no message>".to_string());
    let fingerprint =
        json_string(&payload, "/$exception_fingerprint").unwrap_or_else(|| "<none>".to_string());
    let issue =
        json_string(&payload, "/$exception_issue_id").unwrap_or_else(|| "<none>".to_string());

    format!(
        "msg={} fp={} issue={} metadata_keys={}",
        truncate(&message, 30),
        truncate(&fingerprint, 18),
        truncate(&issue, 18),
        metadata_keys,
    )
}

fn payload_message(properties_json: &[u8]) -> String {
    let Ok(payload) = serde_json::from_slice::<serde_json::Value>(properties_json) else {
        return "<non-json payload>".to_string();
    };

    json_string(&payload, "/message")
        .or_else(|| json_string(&payload, "/$exception_message"))
        .map(|message| truncate(&message, 48))
        .unwrap_or_else(|| "<no message>".to_string())
}

fn json_string(payload: &serde_json::Value, pointer: &str) -> Option<String> {
    payload
        .pointer(pointer)
        .and_then(serde_json::Value::as_str)
        .map(ToString::to_string)
}

fn truncate(value: &str, width: usize) -> String {
    let mut chars = value.chars();
    let truncated = chars.by_ref().take(width).collect::<String>();
    if chars.next().is_none() {
        return truncated;
    }

    let mut truncated = truncated
        .chars()
        .take(width.saturating_sub(1))
        .collect::<String>();
    truncated.push('…');
    truncated
}

fn batch_id(request: &ProcessExceptionBatchRequest) -> &str {
    request
        .context
        .as_ref()
        .map_or("<missing>", |context| context.batch_id.as_str())
}

#[cfg(test)]
mod tests {
    use super::*;
    use cymbal_api::cymbal::v1::{ProcessingError, Retry};

    fn result(outcome: process_exception_batch_result::Outcome) -> ProcessExceptionBatchResult {
        ProcessExceptionBatchResult {
            event_id: "event-1".to_string(),
            outcome: Some(outcome),
        }
    }

    #[test]
    fn outcome_counts_include_every_result_shape() {
        let results = vec![
            result(process_exception_batch_result::Outcome::Next(
                EnrichedExceptionEvent {
                    properties_json: br#"{}"#.to_vec(),
                    metadata: Default::default(),
                },
            )),
            result(process_exception_batch_result::Outcome::Drop(Drop {
                reason: "suppressed".to_string(),
            })),
            result(process_exception_batch_result::Outcome::Retry(Retry {
                reason: "remote unavailable".to_string(),
                retry_after_ms: 50,
            })),
            result(process_exception_batch_result::Outcome::Error(
                ProcessingError {
                    message: "bad input".to_string(),
                    code: "invalid".to_string(),
                    retryable: false,
                },
            )),
            ProcessExceptionBatchResult {
                event_id: "event-5".to_string(),
                outcome: None,
            },
        ];

        let counts = OutcomeCounts::from_results(&results);

        assert_eq!(counts.next, 1);
        assert_eq!(counts.drop, 1);
        assert_eq!(counts.retry, 1);
        assert_eq!(counts.error, 1);
        assert_eq!(counts.missing, 1);
    }

    #[test]
    fn summaries_are_compact_for_next_retry_error_and_missing() {
        let next = ResultSummary::from_result(&result(process_exception_batch_result::Outcome::Next(
            EnrichedExceptionEvent {
                properties_json: br#"{"$exception_message":"boom","$exception_fingerprint":"fingerprint","$exception_issue_id":"issue-1"}"#.to_vec(),
                metadata: Default::default(),
            },
        )));
        let retry = ResultSummary::from_result(&result(
            process_exception_batch_result::Outcome::Retry(Retry {
                reason: "remote stage failed".to_string(),
                retry_after_ms: 100,
            }),
        ));
        let missing = ResultSummary::from_result(&ProcessExceptionBatchResult {
            event_id: "event-2".to_string(),
            outcome: None,
        });

        assert_eq!(next.payload_bytes, "100");
        assert!(next.details.contains("msg=boom"));
        assert!(next.details.contains("fp=fingerprint"));
        assert_eq!(
            retry.details,
            "retry_after_ms=100 reason=remote stage failed"
        );
        assert_eq!(missing.details, "missing outcome");
    }

    #[test]
    fn verbosity_accepts_compact_info_and_debug_values() {
        assert_eq!(Verbosity::from_value("compact"), Verbosity::Compact);
        assert_eq!(Verbosity::from_value("c"), Verbosity::Compact);
        assert_eq!(Verbosity::from_value("info"), Verbosity::Info);
        assert_eq!(Verbosity::from_value("debug"), Verbosity::Debug);
        assert_eq!(Verbosity::from_value("unknown"), Verbosity::Debug);
        assert_eq!(Verbosity::Info.as_str(), "info");
    }

    #[test]
    fn compact_counts_fit_single_line_status() {
        let results = vec![
            result(process_exception_batch_result::Outcome::Next(
                EnrichedExceptionEvent {
                    properties_json: br#"{}"#.to_vec(),
                    metadata: Default::default(),
                },
            )),
            result(process_exception_batch_result::Outcome::Retry(Retry {
                reason: "remote unavailable".to_string(),
                retry_after_ms: 50,
            })),
        ];

        assert_eq!(
            compact_counts(&results),
            format!("{GREEN}✓1{RESET} {YELLOW}↻1{RESET}")
        );
        assert_eq!(compact_counts(&[]), "∅");
    }

    #[test]
    fn outcome_preview_limits_event_list() {
        let results = (0..7)
            .map(|index| ProcessExceptionBatchResult {
                event_id: format!("event-{index}"),
                outcome: Some(process_exception_batch_result::Outcome::Next(
                    EnrichedExceptionEvent {
                        properties_json: br#"{}"#.to_vec(),
                        metadata: Default::default(),
                    },
                )),
            })
            .collect::<Vec<_>>();

        let preview = outcome_preview(&results, 3);

        assert!(preview.contains("event-0"));
        assert!(preview.contains("event-2"));
        assert!(preview.contains("…4 more"));
        assert!(!preview.contains("event-4"));
    }

    #[test]
    fn payload_message_handles_json_and_non_json_payloads() {
        assert_eq!(payload_message(br#"{"$exception_message":"boom"}"#), "boom");
        assert_eq!(payload_message(b"not json"), "<non-json payload>");
    }
}
