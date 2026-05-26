mod output;
mod payloads;

use std::collections::BTreeSet;

use cymbal_api::cymbal::v1::cymbal_ingestion_client::CymbalIngestionClient;
use cymbal_api::cymbal::v1::{
    ExceptionEvent, ProcessExceptionBatchRequest, ProcessExceptionBatchResult,
};
use futures::TryStreamExt;
use output::{
    log_expected_error, log_failure, log_request, log_results, log_success, log_summary, Verbosity,
    BOLD, CYAN, DIM, RESET, RULE,
};
use payloads::{
    batch_context, default_processing_options, empty_exception_list_properties,
    exception_without_stacktrace_properties, input_event, invalid_exception_list_properties,
    invalid_json_properties, manual_fingerprint_exception_properties,
    multi_frame_exception_properties, plain_event_properties, sample_exception_properties,
};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let endpoint = std::env::var("CYMBAL_PIPELINE_ENDPOINT")
        .unwrap_or_else(|_| "http://127.0.0.1:50150".to_string());
    let verbosity = Verbosity::from_env();
    println!("\n{BOLD}{CYAN}Cymbal ingestion examples{RESET}");
    println!("{DIM}endpoint:{RESET} {endpoint}");
    println!("{DIM}verbosity:{RESET} {}", verbosity.as_str());
    println!("{DIM}{}{RESET}", RULE);

    let mut client = match CymbalIngestionClient::connect(endpoint.clone()).await {
        Ok(client) => client,
        Err(error) => {
            log_failure("connect", &error, verbosity);
            log_summary(0, 1, example_count());
            return Err(error.into());
        }
    };

    let mut passed = 0;
    let mut failed = 0;
    let skipped = 0;

    for example in example_cases() {
        let label = example.label;
        match run_example_case(&mut client, verbosity, example).await {
            Ok(()) => passed += 1,
            Err(error) => {
                failed += 1;
                log_failure(label, error.as_ref(), verbosity);
            }
        }
    }

    match run_oversized_batch(&mut client, verbosity).await {
        Ok(()) => passed += 1,
        Err(error) => {
            failed += 1;
            log_failure("oversized batch", error.as_ref(), verbosity);
        }
    }

    log_summary(passed, failed, skipped);
    if failed > 0 {
        return Err(format!("{failed} Cymbal ingestion example(s) failed").into());
    }

    Ok(())
}

struct ExampleCase {
    label: &'static str,
    description: &'static str,
    batch_id: &'static str,
    events: Vec<ExceptionEvent>,
}

fn example_count() -> usize {
    example_cases().len() + 1
}

fn example_cases() -> Vec<ExampleCase> {
    vec![
        ExampleCase {
            label: "single-event baseline",
            description: "valid exception creates or reuses an issue",
            batch_id: "local-smoke-test",
            events: vec![input_event(
                "event-1",
                sample_exception_properties("local Cymbal smoke test"),
            )],
        },
        ExampleCase {
            label: "empty batch",
            description: "no events returns an empty stream",
            batch_id: "empty-batch",
            events: Vec::new(),
        },
        ExampleCase {
            label: "exception shape variants",
            description: "stackless, multi-frame, empty-list, and unicode payloads",
            batch_id: "exception-shape-variants",
            events: vec![
                input_event(
                    "event-stackless",
                    exception_without_stacktrace_properties("stackless exception"),
                ),
                input_event(
                    "event-multiframe",
                    multi_frame_exception_properties("multi-frame exception"),
                ),
                input_event(
                    "event-empty-list",
                    empty_exception_list_properties("empty exception list"),
                ),
                input_event(
                    "event-unicode",
                    sample_exception_properties("unicode exception 🚨 café"),
                ),
            ],
        },
        ExampleCase {
            label: "same fingerprint burst",
            description: "batch cache deduplicates repeated manual fingerprints",
            batch_id: "same-fingerprint-burst",
            events: vec![
                input_event(
                    "event-same-fp-1",
                    manual_fingerprint_exception_properties(
                        "same fingerprint first",
                        "shared-example-fingerprint",
                    ),
                ),
                input_event(
                    "event-same-fp-2",
                    manual_fingerprint_exception_properties(
                        "same fingerprint second",
                        "shared-example-fingerprint",
                    ),
                ),
                input_event(
                    "event-same-fp-3",
                    manual_fingerprint_exception_properties(
                        "same fingerprint third",
                        "shared-example-fingerprint",
                    ),
                ),
            ],
        },
        ExampleCase {
            label: "mixed event batch",
            description: "valid, manual, plain, malformed, and non-json payloads",
            batch_id: "mixed-event-batch",
            events: vec![
                input_event("event-2", sample_exception_properties("first batch item")),
                input_event(
                    "event-3",
                    manual_fingerprint_exception_properties(
                        "manual fingerprint item",
                        "manual-example-fingerprint",
                    ),
                ),
                input_event(
                    "event-4",
                    plain_event_properties("plain non-exception event"),
                ),
                input_event(
                    "event-5",
                    invalid_exception_list_properties("invalid exception list shape"),
                ),
                input_event("event-6", invalid_json_properties()),
            ],
        },
    ]
}

async fn run_example_case(
    client: &mut CymbalIngestionClient<tonic::transport::Channel>,
    verbosity: Verbosity,
    example: ExampleCase,
) -> Result<(), Box<dyn std::error::Error>> {
    let expected_event_ids = example
        .events
        .iter()
        .map(|event| event.event_id.clone())
        .collect::<Vec<_>>();
    let request = ProcessExceptionBatchRequest {
        context: Some(batch_context(example.batch_id)),
        events: example.events,
        options: Some(default_processing_options()),
    };

    log_request(example.label, &request, verbosity);
    let results = process_exception_batch(client, request).await?;
    log_results(&results, verbosity);
    assert_result_ids(&results, &expected_event_ids)?;
    log_success(
        example.label,
        example.description,
        Some(&results),
        verbosity,
    );
    Ok(())
}

async fn run_oversized_batch(
    client: &mut CymbalIngestionClient<tonic::transport::Channel>,
    verbosity: Verbosity,
) -> Result<(), Box<dyn std::error::Error>> {
    let max_events = std::env::var("CYMBAL_EXAMPLE_OVERSIZED_BATCH_EVENTS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(10_001);
    let request = ProcessExceptionBatchRequest {
        context: Some(batch_context("oversized-batch")),
        events: (0..max_events)
            .map(|index| {
                input_event(
                    format!("oversized-event-{index}"),
                    sample_exception_properties("oversized batch item"),
                )
            })
            .collect(),
        options: Some(default_processing_options()),
    };

    log_request("oversized batch", &request, verbosity);
    let error = match client.process_exception_batch(request).await {
        Ok(_) => return Err("expected oversized batch to fail with ResourceExhausted".into()),
        Err(error) => error,
    };
    log_expected_error("oversized batch", &error, verbosity);
    if error.code() != tonic::Code::ResourceExhausted {
        return Err(format!("expected ResourceExhausted, got {}", error.code()).into());
    }
    log_success(
        "oversized batch",
        "server rejects batches above configured event limit",
        None,
        verbosity,
    );

    Ok(())
}

async fn process_exception_batch(
    client: &mut CymbalIngestionClient<tonic::transport::Channel>,
    request: ProcessExceptionBatchRequest,
) -> Result<Vec<ProcessExceptionBatchResult>, Box<dyn std::error::Error>> {
    Ok(client
        .process_exception_batch(request)
        .await?
        .into_inner()
        .try_collect::<Vec<_>>()
        .await?)
}

fn assert_result_ids(
    results: &[ProcessExceptionBatchResult],
    expected_event_ids: &[String],
) -> Result<(), Box<dyn std::error::Error>> {
    if results.len() != expected_event_ids.len() {
        return Err(format!(
            "expected {} results, got {}",
            expected_event_ids.len(),
            results.len()
        )
        .into());
    }

    let actual_ids = results
        .iter()
        .map(|result| result.event_id.clone())
        .collect::<BTreeSet<_>>();
    let expected_ids = expected_event_ids.iter().cloned().collect::<BTreeSet<_>>();
    if actual_ids != expected_ids {
        return Err(format!("expected result IDs {expected_ids:?}, got {actual_ids:?}").into());
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn assert_result_ids_accepts_any_outcome_shape_and_any_order() {
        let results = vec![
            ProcessExceptionBatchResult {
                event_id: "event-2".to_string(),
                outcome: None,
            },
            ProcessExceptionBatchResult {
                event_id: "event-1".to_string(),
                outcome: None,
            },
        ];

        assert!(
            assert_result_ids(&results, &["event-1".to_string(), "event-2".to_string()]).is_ok()
        );
        assert!(assert_result_ids(&results, &["event-1".to_string()]).is_err());
        assert!(
            assert_result_ids(&results, &["event-1".to_string(), "event-3".to_string()]).is_err()
        );
    }

    #[test]
    fn example_cases_cover_empty_valid_manual_plain_and_malformed_payloads() {
        let examples = vec![
            ExampleCase {
                label: "empty",
                description: "empty",
                batch_id: "empty",
                events: Vec::new(),
            },
            ExampleCase {
                label: "mixed",
                description: "mixed",
                batch_id: "mixed",
                events: vec![
                    input_event("valid", sample_exception_properties("valid")),
                    input_event(
                        "manual",
                        manual_fingerprint_exception_properties("manual", "fingerprint"),
                    ),
                    input_event("plain", plain_event_properties("plain")),
                    input_event("invalid-list", invalid_exception_list_properties("bad")),
                    input_event("invalid-json", invalid_json_properties()),
                ],
            },
        ];

        assert!(examples.iter().any(|example| example.events.is_empty()));
        assert_eq!(
            examples
                .iter()
                .map(|example| example.events.len())
                .sum::<usize>(),
            5
        );
    }
}
