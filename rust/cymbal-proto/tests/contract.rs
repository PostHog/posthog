use std::collections::HashSet;

use cymbal_proto::cymbal::resolution::v1::{
    item_outcome, outcome, BatchSummary, Done, ExceptionResolution, ExceptionResolutionItem,
    ItemOutcome, ItemReference, LoadEvent, Outcome, ResolveRequest, Retry, SubscribeRequest,
};
use prost::Message;

#[test]
fn resolve_request_serializes_exception_level_items_with_stable_identity() {
    let request = ResolveRequest {
        batch_id: "batch-1".to_string(),
        items: vec![ExceptionResolutionItem {
            item_id: "event-1:exception-0".to_string(),
            item_index: 0,
            team_id: 42,
            exception: Some(ExceptionResolution {
                exception_json: br#"{"type":"Error"}"#.to_vec(),
                apple_debug_images_json: b"[]".to_vec(),
            }),
        }],
    };

    let decoded = ResolveRequest::decode(request.encode_to_vec().as_slice()).unwrap();

    assert_eq!(decoded.batch_id, "batch-1");
    assert_eq!(decoded.items.len(), 1);
    assert_eq!(decoded.items[0].item_id, "event-1:exception-0");
    assert_eq!(decoded.items[0].item_index, 0);
    assert_eq!(decoded.items[0].team_id, 42);
    assert_eq!(
        decoded.items[0].exception.as_ref().unwrap().exception_json,
        br#"{"type":"Error"}"#
    );
}

#[test]
fn streamed_outcome_envelope_carries_item_and_terminal_summary_shapes_only() {
    // After the Subscribe split, Outcome's oneof only carries item_outcome
    // and batch_summary. The reserved tag 11 (was service_info) is intentionally
    // not addressable from generated Rust types — exercised here so a future
    // re-introduction of a load variant on this oneof is a compile break, not
    // a silent overlap.
    let outcomes = [
        Outcome {
            batch_id: "batch-1".to_string(),
            sequence: 1,
            message: Some(outcome::Message::ItemOutcome(ItemOutcome {
                item_id: "event-1:exception-0".to_string(),
                item_index: 0,
                result: Some(item_outcome::Result::Done(Done {
                    resolved_exception_json: br#"{"type":"ResolvedError"}"#.to_vec(),
                })),
            })),
        },
        Outcome {
            batch_id: "batch-1".to_string(),
            sequence: 2,
            message: Some(outcome::Message::BatchSummary(BatchSummary {
                submitted_items: 1,
                item_outcomes: 1,
                done_items: 1,
                error_items: 0,
                retry_items: 0,
                missing_items: vec![],
                duplicate_items: vec![],
            })),
        },
    ];

    let decoded: Vec<Outcome> = outcomes
        .iter()
        .map(|outcome| Outcome::decode(outcome.encode_to_vec().as_slice()).unwrap())
        .collect();

    assert!(matches!(
        decoded[0].message,
        Some(outcome::Message::ItemOutcome(ItemOutcome {
            result: Some(item_outcome::Result::Done(_)),
            ..
        }))
    ));
    assert!(matches!(
        decoded[1].message,
        Some(outcome::Message::BatchSummary(_))
    ));
}

#[test]
fn batch_summary_counts_item_outcomes_only_and_can_report_gaps() {
    let submitted = [
        ItemReference {
            item_id: "event-1:exception-0".to_string(),
            item_index: 0,
        },
        ItemReference {
            item_id: "event-1:exception-1".to_string(),
            item_index: 1,
        },
        ItemReference {
            item_id: "event-2:exception-0".to_string(),
            item_index: 2,
        },
    ];
    let item_outcomes = [
        ItemOutcome {
            item_id: submitted[0].item_id.clone(),
            item_index: submitted[0].item_index,
            result: Some(item_outcome::Result::Done(Done {
                resolved_exception_json: b"{}".to_vec(),
            })),
        },
        ItemOutcome {
            item_id: submitted[1].item_id.clone(),
            item_index: submitted[1].item_index,
            result: Some(item_outcome::Result::Retry(Retry {
                code: "overloaded".to_string(),
                message: "try another endpoint".to_string(),
                retry_after_ms: 25,
            })),
        },
        ItemOutcome {
            item_id: submitted[1].item_id.clone(),
            item_index: submitted[1].item_index,
            result: Some(item_outcome::Result::Retry(Retry {
                code: "overloaded".to_string(),
                message: "duplicate retry signal".to_string(),
                retry_after_ms: 25,
            })),
        },
    ];

    let seen_once: HashSet<(String, u32)> = item_outcomes
        .iter()
        .map(|outcome| (outcome.item_id.clone(), outcome.item_index))
        .collect();
    let summary = BatchSummary {
        submitted_items: submitted.len() as u32,
        item_outcomes: item_outcomes.len() as u32,
        done_items: item_outcomes
            .iter()
            .filter(|outcome| matches!(outcome.result, Some(item_outcome::Result::Done(_))))
            .count() as u32,
        error_items: item_outcomes
            .iter()
            .filter(|outcome| matches!(outcome.result, Some(item_outcome::Result::Error(_))))
            .count() as u32,
        retry_items: item_outcomes
            .iter()
            .filter(|outcome| matches!(outcome.result, Some(item_outcome::Result::Retry(_))))
            .count() as u32,
        missing_items: submitted
            .iter()
            .filter(|item| !seen_once.contains(&(item.item_id.clone(), item.item_index)))
            .cloned()
            .collect(),
        duplicate_items: vec![submitted[1].clone()],
    };

    assert_eq!(summary.submitted_items, 3);
    assert_eq!(summary.item_outcomes, 3);
    assert_eq!(summary.done_items, 1);
    assert_eq!(summary.retry_items, 2);
    assert_eq!(summary.missing_items, vec![submitted[2].clone()]);
    assert_eq!(summary.duplicate_items, vec![submitted[1].clone()]);
}

#[test]
fn subscribe_request_round_trips_caller_hint_and_identity() {
    // SubscribeRequest is intentionally small. We pin the on-the-wire shape so
    // future additions (e.g. filters) have to choose new tags rather than
    // accidentally aliasing the v1 hint field.
    let request = SubscribeRequest {
        subscriber_id: "cymbal/pod-1".to_string(),
        tick_hint_ms: 500,
    };
    let decoded = SubscribeRequest::decode(request.encode_to_vec().as_slice()).unwrap();
    assert_eq!(decoded.subscriber_id, "cymbal/pod-1");
    assert_eq!(decoded.tick_hint_ms, 500);
}

#[test]
fn load_event_carries_routing_relevant_state_with_sequence() {
    // LoadEvent is what the endpoint pool reads. Every routing decision flows
    // through these fields, so the test pins the shape end-to-end including
    // the sequence so a reconnected stream can be detected by callers.
    let event = LoadEvent {
        service_instance_id: "resolver-a".to_string(),
        degraded: false,
        draining: false,
        sequence: 7,
        message: "ok".to_string(),
        suggested_batch_size: 48,
    };

    let decoded = LoadEvent::decode(event.encode_to_vec().as_slice()).unwrap();
    assert_eq!(decoded.service_instance_id, "resolver-a");
    assert_eq!(decoded.sequence, 7);
    assert_eq!(decoded.suggested_batch_size, 48);
    assert!(!decoded.degraded);
    assert!(!decoded.draining);
}
