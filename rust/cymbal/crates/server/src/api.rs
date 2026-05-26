use cymbal_api::cymbal::v1::{
    process_exception_batch_result, Drop, EnrichedExceptionEvent,
    ExceptionEvent as ApiExceptionEvent, ProcessExceptionBatchRequest,
    ProcessExceptionBatchResult as ApiBatchResult, ProcessingError, Retry,
};
use cymbal_core::{BatchContext, StageError, StageInput};
use cymbal_domain::{
    recursively_sanitize_properties, EventOutcome, EventResult as DomainEventResult,
    ExceptionProperties, InputEvent, MISSING_TEAM_ID_DROP_REASON,
};
use serde_json::Value;
use tonic::Status;
use uuid::Uuid;

pub(crate) struct RequestStageInput {
    pub input: StageInput<InputEvent>,
    pub terminal_results: Vec<DomainEventResult>,
}

pub(crate) fn request_to_stage_input(request: ProcessExceptionBatchRequest) -> RequestStageInput {
    let context = request.context.map_or_else(
        || BatchContext {
            batch_id: String::new(),
            metadata: Default::default(),
        },
        |context| BatchContext {
            batch_id: context.batch_id,
            metadata: context.metadata,
        },
    );

    let mut terminal_results = Vec::new();
    let mut events = Vec::new();
    for event in request.events {
        if event.team_id <= 0 {
            terminal_results.push(DomainEventResult {
                event_id: event.event_id,
                outcome: EventOutcome::Drop {
                    reason: MISSING_TEAM_ID_DROP_REASON.to_string(),
                },
            });
            continue;
        }
        match exception_event_to_domain(event) {
            Ok(event) => events.push(event),
            Err(result) => terminal_results.push(result),
        }
    }

    RequestStageInput {
        input: StageInput::from_items(context, events),
        terminal_results,
    }
}

const INVALID_PROPERTIES_JSON_ERROR_CODE: &str = "invalid_properties_json";

fn exception_event_to_domain(event: ApiExceptionEvent) -> Result<InputEvent, DomainEventResult> {
    let event_id = event.event_id;
    let properties =
        public_properties_to_domain(event.properties_json, &event_id).map_err(|error| {
            DomainEventResult {
                event_id: event_id.clone(),
                outcome: EventOutcome::Error {
                    message: error,
                    code: Some(INVALID_PROPERTIES_JSON_ERROR_CODE.to_string()),
                    retryable: Some(false),
                },
            }
        })?;

    Ok(InputEvent {
        event_id,
        team_id: event.team_id,
        properties,
    })
}

fn public_properties_to_domain(
    properties_json: Vec<u8>,
    event_id: &str,
) -> Result<ExceptionProperties, String> {
    let properties =
        serde_json::from_slice::<Value>(&properties_json).map_err(|error| error.to_string())?;
    let Value::Object(mut properties) = properties else {
        return Err("exception properties must be a JSON object".to_string());
    };

    if let Some(exception_list) = properties.get_mut("$exception_list") {
        let sanitization_id = Uuid::parse_str(event_id).unwrap_or_else(|_| Uuid::now_v7());
        recursively_sanitize_properties(sanitization_id, exception_list, 0)
            .map_err(|error| error.to_string())?;
    }

    let mut properties =
        ExceptionProperties::from_map(properties).map_err(|error| error.to_string())?;
    properties.normalize_for_ingestion(event_id);
    Ok(properties)
}

pub(crate) fn domain_event_result_to_api(result: DomainEventResult) -> ApiBatchResult {
    let event_id = result.event_id;
    let outcome = match result.outcome {
        EventOutcome::Next {
            properties,
            metadata,
        } => process_exception_batch_result::Outcome::Next(EnrichedExceptionEvent {
            properties_json: properties
                .as_ref()
                .and_then(|properties| serde_json::to_vec(properties).ok())
                .unwrap_or_default(),
            metadata,
        }),
        EventOutcome::Drop { reason } => {
            process_exception_batch_result::Outcome::Drop(Drop { reason })
        }
        EventOutcome::Retry {
            reason,
            retry_after_ms,
        } => process_exception_batch_result::Outcome::Retry(Retry {
            reason,
            retry_after_ms: retry_after_ms.unwrap_or_default(),
        }),
        EventOutcome::Error {
            message,
            code,
            retryable,
        } => process_exception_batch_result::Outcome::Error(ProcessingError {
            message,
            code: code.unwrap_or_default(),
            retryable: retryable.unwrap_or_default(),
        }),
    };

    ApiBatchResult {
        event_id,
        outcome: Some(outcome),
    }
}

pub(crate) fn stage_error_to_status(error: StageError) -> Status {
    match error {
        StageError::InvalidInput(message) => Status::invalid_argument(message),
        StageError::Transient(message) => Status::unavailable(message),
        StageError::Internal(message) => Status::internal(message),
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use cymbal_api::cymbal::v1::{
        process_exception_batch_result, BatchContext as ApiBatchContext, ExceptionEvent,
        ProcessingOptions,
    };
    use cymbal_core::Metadata;
    use cymbal_domain::EventResult;
    use serde_json::{json, Value};
    use tonic::Code;

    use super::*;

    fn exception_event(event_id: &str, team_id: i64, properties_json: Vec<u8>) -> ExceptionEvent {
        ExceptionEvent {
            event_id: event_id.to_string(),
            team_id,
            distinct_id: format!("distinct-{event_id}"),
            timestamp: None,
            properties_json,
        }
    }

    fn valid_properties_json() -> Vec<u8> {
        serde_json::to_vec(&json!({
            "event": "$exception",
            "custom": "value",
        }))
        .unwrap()
    }

    fn exception_properties(value: Value) -> ExceptionProperties {
        ExceptionProperties::from_map(value.as_object().unwrap().clone()).unwrap()
    }

    fn error_terminal(result: &DomainEventResult) -> (&str, &str, bool) {
        let EventOutcome::Error {
            message,
            code,
            retryable,
        } = &result.outcome
        else {
            panic!("expected processing error, got {:?}", result.outcome);
        };

        (
            message.as_str(),
            code.as_deref().unwrap_or_default(),
            retryable.unwrap_or(true),
        )
    }

    #[test]
    fn request_to_stage_input_preserves_batch_context_metadata() {
        let metadata = HashMap::from([
            ("source".to_string(), "node-ingestion".to_string()),
            ("trace_id".to_string(), "trace-1".to_string()),
        ]);
        let request = ProcessExceptionBatchRequest {
            context: Some(ApiBatchContext {
                batch_id: "batch-1".to_string(),
                metadata: metadata.clone(),
            }),
            events: vec![exception_event("event-1", 42, valid_properties_json())],
            options: None,
        };

        let converted = request_to_stage_input(request);

        assert_eq!(converted.input.context.batch_id, "batch-1");
        assert_eq!(converted.input.context.metadata, metadata);
        assert_eq!(converted.input.items.len(), 1);
        assert!(converted.terminal_results.is_empty());
    }

    #[test]
    fn zero_negative_and_missing_team_ids_become_terminal_drops_before_stage_work() {
        let request = ProcessExceptionBatchRequest {
            context: None,
            events: vec![
                exception_event("zero-team", 0, valid_properties_json()),
                exception_event("negative-team", -1, valid_properties_json()),
                ExceptionEvent {
                    event_id: "missing-team".to_string(),
                    properties_json: valid_properties_json(),
                    ..Default::default()
                },
            ],
            options: None,
        };

        let converted = request_to_stage_input(request);

        assert!(converted.input.items.is_empty());
        assert_eq!(converted.terminal_results.len(), 3);
        assert_eq!(
            converted
                .terminal_results
                .iter()
                .map(|result| result.event_id.as_str())
                .collect::<Vec<_>>(),
            vec!["zero-team", "negative-team", "missing-team"]
        );
        for result in converted.terminal_results {
            assert!(matches!(
                result.outcome,
                EventOutcome::Drop { reason } if reason == MISSING_TEAM_ID_DROP_REASON
            ));
        }
    }

    #[test]
    fn invalid_json_and_non_object_json_become_non_retryable_processing_errors() {
        let request = ProcessExceptionBatchRequest {
            context: None,
            events: vec![
                exception_event("invalid-json", 42, br#"{"event":"$exception""#.to_vec()),
                exception_event("non-object-json", 42, br#"[]"#.to_vec()),
            ],
            options: None,
        };

        let converted = request_to_stage_input(request);

        assert!(converted.input.items.is_empty());
        assert_eq!(converted.terminal_results.len(), 2);

        let (message, code, retryable) = error_terminal(&converted.terminal_results[0]);
        assert!(!message.is_empty());
        assert_eq!(code, INVALID_PROPERTIES_JSON_ERROR_CODE);
        assert!(!retryable);

        let (message, code, retryable) = error_terminal(&converted.terminal_results[1]);
        assert_eq!(message, "exception properties must be a JSON object");
        assert_eq!(code, INVALID_PROPERTIES_JSON_ERROR_CODE);
        assert!(!retryable);
    }

    #[test]
    fn processing_options_are_currently_ignored_at_public_boundary() {
        let base_request = ProcessExceptionBatchRequest {
            context: None,
            events: vec![exception_event("event-1", 42, valid_properties_json())],
            options: None,
        };
        let options_request = ProcessExceptionBatchRequest {
            options: Some(ProcessingOptions {
                skip_alerting: true,
                emit_internal_events: false,
                emit_signals: false,
            }),
            ..base_request.clone()
        };

        let without_options = request_to_stage_input(base_request);
        let with_options = request_to_stage_input(options_request);

        assert_eq!(without_options.input.context, with_options.input.context);
        assert_eq!(without_options.input.items, with_options.input.items);
        assert_eq!(
            without_options.terminal_results,
            with_options.terminal_results
        );
    }

    #[test]
    fn event_outcomes_map_to_public_protobuf_outcomes_and_default_fields() {
        let mut metadata = Metadata::new();
        metadata.insert("stage".to_string(), "resolution".to_string());
        let properties = exception_properties(json!({
            "event": "$exception",
            "custom": "value",
        }));

        let next_result = domain_event_result_to_api(EventResult {
            event_id: "next".to_string(),
            outcome: EventOutcome::Next {
                properties: Some(properties),
                metadata: metadata.clone(),
            },
        });
        assert_eq!(next_result.event_id, "next");
        match next_result.outcome.unwrap() {
            process_exception_batch_result::Outcome::Next(next) => {
                assert_eq!(next.metadata, metadata);
                assert_eq!(
                    serde_json::from_slice::<Value>(&next.properties_json).unwrap(),
                    json!({"event": "$exception", "custom": "value"})
                );
            }
            outcome => panic!("expected next outcome, got {outcome:?}"),
        }

        let next_without_properties = domain_event_result_to_api(EventResult {
            event_id: "next-empty".to_string(),
            outcome: EventOutcome::Next {
                properties: None,
                metadata: Metadata::new(),
            },
        });
        match next_without_properties.outcome.unwrap() {
            process_exception_batch_result::Outcome::Next(next) => {
                assert!(next.properties_json.is_empty());
                assert!(next.metadata.is_empty());
            }
            outcome => panic!("expected next outcome, got {outcome:?}"),
        }

        let drop_result = domain_event_result_to_api(EventResult {
            event_id: "drop".to_string(),
            outcome: EventOutcome::Drop {
                reason: "missing_team_id".to_string(),
            },
        });
        match drop_result.outcome.unwrap() {
            process_exception_batch_result::Outcome::Drop(drop) => {
                assert_eq!(drop.reason, "missing_team_id");
            }
            outcome => panic!("expected drop outcome, got {outcome:?}"),
        }

        let retry_result = domain_event_result_to_api(EventResult {
            event_id: "retry".to_string(),
            outcome: EventOutcome::Retry {
                reason: "remote unavailable".to_string(),
                retry_after_ms: Some(250),
            },
        });
        match retry_result.outcome.unwrap() {
            process_exception_batch_result::Outcome::Retry(retry) => {
                assert_eq!(retry.reason, "remote unavailable");
                assert_eq!(retry.retry_after_ms, 250);
            }
            outcome => panic!("expected retry outcome, got {outcome:?}"),
        }

        let retry_without_after = domain_event_result_to_api(EventResult {
            event_id: "retry-default".to_string(),
            outcome: EventOutcome::Retry {
                reason: "try later".to_string(),
                retry_after_ms: None,
            },
        });
        match retry_without_after.outcome.unwrap() {
            process_exception_batch_result::Outcome::Retry(retry) => {
                assert_eq!(retry.reason, "try later");
                assert_eq!(retry.retry_after_ms, 0);
            }
            outcome => panic!("expected retry outcome, got {outcome:?}"),
        }

        let error_result = domain_event_result_to_api(EventResult {
            event_id: "error".to_string(),
            outcome: EventOutcome::Error {
                message: "bad input".to_string(),
                code: Some("invalid_properties_json".to_string()),
                retryable: Some(false),
            },
        });
        match error_result.outcome.unwrap() {
            process_exception_batch_result::Outcome::Error(error) => {
                assert_eq!(error.message, "bad input");
                assert_eq!(error.code, "invalid_properties_json");
                assert!(!error.retryable);
            }
            outcome => panic!("expected error outcome, got {outcome:?}"),
        }

        let error_defaults = domain_event_result_to_api(EventResult {
            event_id: "error-default".to_string(),
            outcome: EventOutcome::Error {
                message: "unknown".to_string(),
                code: None,
                retryable: None,
            },
        });
        match error_defaults.outcome.unwrap() {
            process_exception_batch_result::Outcome::Error(error) => {
                assert_eq!(error.message, "unknown");
                assert!(error.code.is_empty());
                assert!(!error.retryable);
            }
            outcome => panic!("expected error outcome, got {outcome:?}"),
        }
    }

    #[test]
    fn stage_error_variants_map_to_expected_tonic_status_codes() {
        for (error, expected_code, expected_message) in [
            (
                StageError::InvalidInput("bad payload".to_string()),
                Code::InvalidArgument,
                "bad payload",
            ),
            (
                StageError::Transient("try again".to_string()),
                Code::Unavailable,
                "try again",
            ),
            (
                StageError::Internal("bug".to_string()),
                Code::Internal,
                "bug",
            ),
        ] {
            let status = stage_error_to_status(error);

            assert_eq!(status.code(), expected_code);
            assert_eq!(status.message(), expected_message);
        }
    }
}
