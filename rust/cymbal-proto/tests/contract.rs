use cymbal_proto::cymbal::resolution::v1::{
    resolve_outcome, Accepted, Done, Error, ErrorKind, LoadEvent, ResolveItem, ResolveOutcome,
    Retry, SubscribeRequest,
};
use prost::Message;

#[test]
fn resolve_item_serializes_exception_payload_with_correlation_id_and_deadline() {
    let item = ResolveItem {
        id: 7,
        team_id: 42,
        exception_json: br#"{"type":"Error"}"#.to_vec(),
        metadata: br#"{"debug_images_json":[]}"#.to_vec(),
        deadline_ms: 1_500,
    };

    let decoded = ResolveItem::decode(item.encode_to_vec().as_slice()).unwrap();

    assert_eq!(decoded.id, 7);
    assert_eq!(decoded.team_id, 42);
    assert_eq!(decoded.exception_json, br#"{"type":"Error"}"#);
    assert_eq!(decoded.metadata, br#"{"debug_images_json":[]}"#);
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
    let event = LoadEvent {
        service_instance_id: "resolver-a".to_string(),
        draining: false,
        sequence: 7,
        message: "ok".to_string(),
        in_flight: 11,
        max_in_flight: 64,
    };

    let decoded = LoadEvent::decode(event.encode_to_vec().as_slice()).unwrap();

    assert_eq!(decoded.service_instance_id, "resolver-a");
    assert_eq!(decoded.sequence, 7);
    assert_eq!(decoded.in_flight, 11);
    assert_eq!(decoded.max_in_flight, 64);
    assert!(!decoded.draining);
}
