use cymbal_proto::cymbal::{
    process::v1::{
        process_outcome, ProcessBatchRequest, ProcessBatchResponse, ProcessDone, ProcessDrop,
        ProcessDropReason, ProcessError, ProcessErrorCode, ProcessErrorKind, ProcessItem,
        ProcessOutcome, ServiceState, SubscribeRequest as ProcessSubscribeRequest,
    },
    resolution::v1::{
        resolve_outcome, Accepted, Done, Error, ErrorKind, LoadEvent, ResolveItem, ResolveOutcome,
        Retry, SubscribeRequest as ResolutionSubscribeRequest,
    },
};
use prost::Message;

#[test]
fn process_item_serializes_canonical_event_with_opaque_id() {
    let item = ProcessItem {
        id: "caller-1".to_string(),
        event_json: br#"{"uuid":"0198f1d7-26fb-7f17-9b75-4377002fe472","event":"$exception","team_id":42,"timestamp":"2026-01-01T00:00:00Z","properties":{"$exception_list":[]}}"#.to_vec(),
        timeout_ms: 1_500,
    };

    let decoded = ProcessItem::decode(item.encode_to_vec().as_slice()).unwrap();

    assert_eq!(decoded.id, "caller-1");
    assert_eq!(
        decoded.event_json,
        br#"{"uuid":"0198f1d7-26fb-7f17-9b75-4377002fe472","event":"$exception","team_id":42,"timestamp":"2026-01-01T00:00:00Z","properties":{"$exception_list":[]}}"#
    );
    assert_eq!(decoded.timeout_ms, 1_500);
}

#[test]
fn process_outcome_carries_exactly_one_terminal_variant() {
    let outcomes = [
        ProcessOutcome {
            id: "done-1".to_string(),
            result: Some(process_outcome::Result::Done(ProcessDone {
                processed_event_json: br#"{"event":"$exception","properties":{"resolved":true}}"#
                    .to_vec(),
            })),
        },
        ProcessOutcome {
            id: "drop-1".to_string(),
            result: Some(process_outcome::Result::Drop(ProcessDrop {
                reason: ProcessDropReason::SuppressionRule as i32,
            })),
        },
        ProcessOutcome {
            id: "error-1".to_string(),
            result: Some(process_outcome::Result::Error(ProcessError {
                kind: ProcessErrorKind::Invalid as i32,
                code: ProcessErrorCode::InvalidPayload as i32,
                retryable: false,
                retry_after_ms: 0,
                message: "event_json could not be decoded".to_string(),
                details_json: b"{}".to_vec(),
            })),
        },
    ];

    let decoded: Vec<ProcessOutcome> = outcomes
        .iter()
        .map(|outcome| ProcessOutcome::decode(outcome.encode_to_vec().as_slice()).unwrap())
        .collect();

    assert!(matches!(
        decoded[0].result,
        Some(process_outcome::Result::Done(_))
    ));
    assert!(matches!(
        decoded[1].result,
        Some(process_outcome::Result::Drop(ProcessDrop {
            reason,
        })) if reason == ProcessDropReason::SuppressionRule as i32
    ));
    assert!(matches!(
        decoded[2].result,
        Some(process_outcome::Result::Error(ProcessError {
            kind,
            code,
            retryable: false,
            ..
        })) if kind == ProcessErrorKind::Invalid as i32
            && code == ProcessErrorCode::InvalidPayload as i32
    ));
}

#[test]
fn process_enums_keep_initial_wire_values() {
    assert_eq!(ProcessDropReason::SuppressedIssue as i32, 1);
    assert_eq!(ProcessDropReason::SuppressionRule as i32, 2);
    assert_eq!(ProcessErrorKind::Invalid as i32, 1);
    assert_eq!(ProcessErrorKind::Processing as i32, 2);
    assert_eq!(ProcessErrorKind::Timeout as i32, 3);
    assert_eq!(ProcessErrorKind::Dependency as i32, 4);
    assert_eq!(ProcessErrorKind::Internal as i32, 5);
    assert_eq!(ProcessErrorCode::InvalidPayload as i32, 1);
    assert_eq!(ProcessErrorCode::Unimplemented as i32, 7);
}

#[test]
fn process_contract_allows_duplicate_ids() {
    let items = [
        ProcessItem {
            id: "duplicate".to_string(),
            event_json: br#"{"event":"$exception","properties":{}}"#.to_vec(),
            timeout_ms: 100,
        },
        ProcessItem {
            id: "duplicate".to_string(),
            event_json: br#"{"event":"$exception","properties":{"second":true}}"#.to_vec(),
            timeout_ms: 200,
        },
    ];

    let decoded: Vec<ProcessItem> = items
        .iter()
        .map(|item| ProcessItem::decode(item.encode_to_vec().as_slice()).unwrap())
        .collect();

    assert_eq!(decoded[0].id, "duplicate");
    assert_eq!(decoded[1].id, "duplicate");
    assert_ne!(decoded[0].event_json, decoded[1].event_json);
    assert_eq!(decoded[0].timeout_ms, 100);
    assert_eq!(decoded[1].timeout_ms, 200);
}

#[test]
fn process_error_round_trips_retry_after_hint() {
    let outcome = ProcessOutcome {
        id: "retryable-1".to_string(),
        result: Some(process_outcome::Result::Error(ProcessError {
            kind: ProcessErrorKind::Dependency as i32,
            code: ProcessErrorCode::DependencyUnavailable as i32,
            retryable: true,
            retry_after_ms: 250,
            message: "dependency unavailable".to_string(),
            details_json: br#"{"safe":true}"#.to_vec(),
        })),
    };

    let decoded = ProcessOutcome::decode(outcome.encode_to_vec().as_slice()).unwrap();

    assert!(matches!(
        decoded.result,
        Some(process_outcome::Result::Error(ProcessError {
            kind,
            code,
            retryable: true,
            retry_after_ms: 250,
            ..
        })) if kind == ProcessErrorKind::Dependency as i32
            && code == ProcessErrorCode::DependencyUnavailable as i32
    ));
}

#[test]
fn process_batch_preserves_input_order_contract() {
    let request = ProcessBatchRequest {
        items: vec![
            ProcessItem {
                id: "first".to_string(),
                event_json: br#"{"event":"$exception","properties":{"first":true}}"#.to_vec(),
                timeout_ms: 1_000,
            },
            ProcessItem {
                id: "second".to_string(),
                event_json: br#"{"event":"$exception","properties":{"second":true}}"#.to_vec(),
                timeout_ms: 2_000,
            },
        ],
    };
    let response = ProcessBatchResponse {
        outcomes: vec![
            ProcessOutcome {
                id: "first".to_string(),
                result: Some(process_outcome::Result::Done(ProcessDone {
                    processed_event_json: br#"{"properties":{"first":true}}"#.to_vec(),
                })),
            },
            ProcessOutcome {
                id: "second".to_string(),
                result: Some(process_outcome::Result::Drop(ProcessDrop {
                    reason: ProcessDropReason::SuppressedIssue as i32,
                })),
            },
        ],
    };

    let decoded_request = ProcessBatchRequest::decode(request.encode_to_vec().as_slice()).unwrap();
    let decoded_response =
        ProcessBatchResponse::decode(response.encode_to_vec().as_slice()).unwrap();

    assert_eq!(decoded_request.items[0].id, "first");
    assert_eq!(decoded_request.items[0].timeout_ms, 1_000);
    assert_eq!(decoded_request.items[1].id, "second");
    assert_eq!(decoded_request.items[1].timeout_ms, 2_000);
    assert_eq!(decoded_response.outcomes[0].id, "first");
    assert_eq!(decoded_response.outcomes[1].id, "second");
}

#[test]
fn process_subscribe_reports_service_state() {
    let request = ProcessSubscribeRequest {
        subscriber_id: "node/error-tracking-1".to_string(),
        tick_hint_ms: 500,
    };
    let state = ServiceState {
        service_instance_id: "cymbal/pod-1".to_string(),
        draining: false,
        accepting_stream: true,
        accepting_batch: true,
        in_flight_items: 7,
        max_in_flight_items: 128,
        sequence: 3,
        message: "ready".to_string(),
    };

    let decoded_request =
        ProcessSubscribeRequest::decode(request.encode_to_vec().as_slice()).unwrap();
    let decoded_state = ServiceState::decode(state.encode_to_vec().as_slice()).unwrap();

    assert_eq!(decoded_request.subscriber_id, "node/error-tracking-1");
    assert_eq!(decoded_request.tick_hint_ms, 500);
    assert_eq!(decoded_state.service_instance_id, "cymbal/pod-1");
    assert!(!decoded_state.draining);
    assert!(decoded_state.accepting_stream);
    assert!(decoded_state.accepting_batch);
    assert_eq!(decoded_state.in_flight_items, 7);
    assert_eq!(decoded_state.max_in_flight_items, 128);
    assert_eq!(decoded_state.sequence, 3);
}

#[test]
fn resolve_item_serializes_exception_payload_with_correlation_id_and_deadline() {
    let item = ResolveItem {
        id: 7,
        team_id: 42,
        exception_json: br#"{"type":"Error"}"#.to_vec(),
        metadata: br#"{"apple_debug_images_json":[]}"#.to_vec(),
        deadline_ms: 1_500,
    };

    let decoded = ResolveItem::decode(item.encode_to_vec().as_slice()).unwrap();

    assert_eq!(decoded.id, 7);
    assert_eq!(decoded.team_id, 42);
    assert_eq!(decoded.exception_json, br#"{"type":"Error"}"#);
    assert_eq!(decoded.metadata, br#"{"apple_debug_images_json":[]}"#);
    assert_eq!(decoded.deadline_ms, 1_500);
}

#[test]
fn resolve_outcome_echoes_id_and_carries_done_error_or_retry() {
    let outcomes = [
        ResolveOutcome {
            id: 1,
            result: Some(resolve_outcome::Result::Done(Done {
                resolved_exception_json: br#"{"type":"ResolvedError"}"#.to_vec(),
            })),
        },
        ResolveOutcome {
            id: 2,
            result: Some(resolve_outcome::Result::Error(Error {
                kind: ErrorKind::InvalidPayload as i32,
                message: "exception_json could not be decoded".to_string(),
                details_json: b"{}".to_vec(),
            })),
        },
        ResolveOutcome {
            id: 3,
            result: Some(resolve_outcome::Result::Retry(Retry {
                code: "transient".to_string(),
                message: "try again later".to_string(),
                retry_after_ms: 25,
            })),
        },
        ResolveOutcome {
            id: 4,
            result: Some(resolve_outcome::Result::Accepted(Accepted {})),
        },
        ResolveOutcome {
            id: 5,
            result: Some(resolve_outcome::Result::Error(Error {
                kind: ErrorKind::Overloaded as i32,
                message: "server overloaded".to_string(),
                details_json: b"{}".to_vec(),
            })),
        },
    ];

    let decoded: Vec<ResolveOutcome> = outcomes
        .iter()
        .map(|outcome| ResolveOutcome::decode(outcome.encode_to_vec().as_slice()).unwrap())
        .collect();

    assert!(matches!(
        decoded[0].result,
        Some(resolve_outcome::Result::Done(_))
    ));
    assert!(matches!(
        decoded[1].result,
        Some(resolve_outcome::Result::Error(_))
    ));
    assert!(matches!(
        decoded[2].result,
        Some(resolve_outcome::Result::Retry(Retry {
            retry_after_ms: 25,
            ..
        }))
    ));
    assert!(matches!(
        decoded[3].result,
        Some(resolve_outcome::Result::Accepted(_))
    ));
    assert!(matches!(
        decoded[4].result,
        Some(resolve_outcome::Result::Error(Error {
            kind,
            ..
        })) if kind == ErrorKind::Overloaded as i32
    ));
    assert_eq!(
        decoded.iter().map(|outcome| outcome.id).collect::<Vec<_>>(),
        vec![1, 2, 3, 4, 5]
    );
}

#[test]
fn subscribe_request_round_trips_caller_hint_and_identity() {
    let request = ResolutionSubscribeRequest {
        subscriber_id: "cymbal/pod-1".to_string(),
        tick_hint_ms: 500,
    };

    let decoded = ResolutionSubscribeRequest::decode(request.encode_to_vec().as_slice()).unwrap();

    assert_eq!(decoded.subscriber_id, "cymbal/pod-1");
    assert_eq!(decoded.tick_hint_ms, 500);
}

#[test]
fn load_event_carries_routing_relevant_state_with_sequence() {
    let event = LoadEvent {
        service_instance_id: "resolver-a".to_string(),
        draining: false,
        sequence: 7,
        message: "ok".to_string(),
    };

    let decoded = LoadEvent::decode(event.encode_to_vec().as_slice()).unwrap();

    assert_eq!(decoded.service_instance_id, "resolver-a");
    assert_eq!(decoded.sequence, 7);
    assert!(!decoded.draining);
}
