//! Ingestion warnings for the AI events endpoint (`/i/v0/ai`).
//!
//! The endpoint's context projection lives with the handler, which owns the
//! event shape it reads `$lib` out of; see this directory's module doc.
//!
//! One request is one event here, so every warning carries `count = 1`.

use common_ingestion_warnings::{
    emit_request_warning, WarningEmitter, WarningRequestContext, WarningType, CAPTURE_AI_EVENTS,
};
use serde_json::{json, Map};

use super::bounded_detail;
use crate::ai_rejection::{AiFailure, AiRejection};
use crate::api::CaptureError;

/// Map a rejection to the warning the customer should see, or `None` when they
/// can't act on it.
///
/// Attributable is not the same as actionable. Every rejection here happens
/// after the token is read, so all of them *could* be attributed to a team; the
/// bar for emitting is that the customer can change something to stop it.
///
/// Five of these reuse types the analytics paths already emit, because the
/// condition is identical and a reader of the v2 table shouldn't have to learn a
/// second vocabulary for the same mistake. The AI-specific types cover what has
/// no analytics equivalent: this endpoint accepts only six event names and
/// requires `$ai_model`, and its payload is multipart rather than a JSON batch.
///
/// Exhaustive with no catch-all, so a new rejection variant fails to compile
/// until someone decides whether customers should see a warning for it.
pub fn warning_for_ai_rejection(rejection: &AiRejection) -> Option<WarningType> {
    match rejection {
        // Sending ordinary analytics to the AI path, or omitting the one
        // property every AI event needs.
        AiRejection::EventNameNotAllowed(_)
        | AiRejection::AiModelMissing
        | AiRejection::AiModelNotString
        | AiRejection::AiModelEmpty => Some(WarningType::InvalidAiEvent),

        // Shared with the analytics paths: same mistake, same type.
        AiRejection::EventMissingName
        | AiRejection::EventNameRequired
        | AiRejection::EventNameEmpty => Some(WarningType::MissingEventName),
        AiRejection::EventMissingDistinctId
        | AiRejection::DistinctIdRequired
        | AiRejection::DistinctIdEmpty => Some(WarningType::MissingDistinctId),
        AiRejection::EventUuidRequired => Some(WarningType::MissingEventUuid),
        AiRejection::EventUuidInvalid(_) => Some(WarningType::InvalidEventUuid),
        AiRejection::EventPartTooBig { .. } | AiRejection::EventAndPropertiesTooBig { .. } => {
            Some(WarningType::MessageSizeTooLarge)
        }

        // The properties object specifically is missing or unreadable.
        AiRejection::EventMissingProperties
        | AiRejection::PropertiesPartNotUtf8
        | AiRejection::PropertiesPartNotJson => Some(WarningType::MalformedEventProperties),

        // Structural problems the customer built into the request.
        AiRejection::NotMultipart
        | AiRejection::InvalidBoundary(_)
        | AiRejection::MissingEventPart
        | AiRejection::FirstPartNotEvent(_)
        | AiRejection::DuplicateEventPart
        | AiRejection::UnknownField(_)
        | AiRejection::EventPartNotUtf8
        | AiRejection::EventPartNotJson
        | AiRejection::EventNotObject
        | AiRejection::ConflictingProperties => Some(WarningType::InvalidAiPayload),

        // The body stream broke mid-read, so the request was truncated or
        // aborted. We can't tell a client that hung up from a proxy or our own
        // load balancer dropping the connection, and blaming the customer's
        // payload for a drop we caused is worse than staying quiet. Same call
        // the legacy path makes for `BodyReadTimeout`.
        //
        // Little is lost: a body that is genuinely malformed rather than
        // truncated fails one of the specific arms above, which say more.
        AiRejection::MultipartParseFailed(_) | AiRejection::FieldDataUnreadable(_) => None,
    }
}

/// Emit the warning for a failed AI request, if the customer should see one.
///
/// The caller only reaches this once a token is known, so attribution is always
/// available; pre-token failures never get here.
pub fn emit_ai_failure_warning(
    emitter: Option<&dyn WarningEmitter>,
    request: &WarningRequestContext,
    failure: &AiFailure,
) {
    let Some((warning, details)) = warning_for_ai_failure(failure) else {
        return;
    };
    emit_request_warning(emitter, request, CAPTURE_AI_EVENTS, warning, details, 1);
}

/// The warning and details for a failure, or `None` when the customer can't act
/// on it.
fn warning_for_ai_failure(
    failure: &AiFailure,
) -> Option<(WarningType, Map<String, serde_json::Value>)> {
    match failure {
        AiFailure::Rejected(rejection) => {
            Some((warning_for_ai_rejection(rejection)?, details_for(rejection)))
        }

        // Both of these come from the gzip decompressor, the only shared helper
        // the handler calls after reading the token. Its size check raises
        // `EventTooBig`; a corrupt stream raises `RequestDecodingError`. Bad
        // compression is the customer's payload just as much as a wrong
        // Content-Type is, so it gets the same treatment.
        AiFailure::Other(CaptureError::EventTooBig(_)) => {
            Some((WarningType::MessageSizeTooLarge, Map::new()))
        }
        AiFailure::Other(CaptureError::RequestDecodingError(_)) => {
            Some((WarningType::InvalidAiPayload, Map::new()))
        }

        // Everything else reaching here is ours: quota is surfaced through
        // billing, and Kafka and serialization failures are not the customer's
        // to fix.
        AiFailure::Other(_) => None,
    }
}

/// Per-rejection details.
///
/// Only values that are safe to show and useful to act on: the rejected event
/// name, the offending part name, and sizes. The rejection's own message is
/// deliberately excluded — several embed a library error string, and this lands
/// in a customer-visible column.
///
/// Every value copied out of the request goes through
/// [`bounded_detail`](super::bounded_detail): all three are client-controlled and
/// nothing downstream length-limits details, so an oversized one would inflate
/// the warning message and its stored row.
fn details_for(rejection: &AiRejection) -> Map<String, serde_json::Value> {
    let mut details = Map::new();
    match rejection {
        AiRejection::EventNameNotAllowed(event_name) => {
            details.insert("eventName".to_string(), json!(bounded_detail(event_name)));
            details.insert(
                "allowed".to_string(),
                json!(crate::ai_rejection::ALLOWED_AI_EVENTS),
            );
        }
        AiRejection::FirstPartNotEvent(field) | AiRejection::UnknownField(field) => {
            details.insert("part".to_string(), json!(bounded_detail(field)));
        }
        AiRejection::EventPartTooBig { size, max }
        | AiRejection::EventAndPropertiesTooBig { size, max } => {
            details.insert("size".to_string(), json!(size));
            details.insert("limit".to_string(), json!(max));
        }
        _ => {}
    }
    details
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_ingestion_warnings::test_support::CollectingEmitter;
    use rstest::rstest;

    fn request() -> WarningRequestContext {
        WarningRequestContext {
            token: "tok".to_string(),
            lib: "posthog-python".to_string(),
            lib_version: "3.1.0".to_string(),
            path: "/i/v0/ai".to_string(),
        }
    }

    #[rstest]
    #[case::wrong_event_name(
        AiRejection::EventNameNotAllowed("$pageview".to_string()),
        Some(WarningType::InvalidAiEvent)
    )]
    #[case::no_model(AiRejection::AiModelMissing, Some(WarningType::InvalidAiEvent))]
    #[case::no_event_name(AiRejection::EventNameRequired, Some(WarningType::MissingEventName))]
    #[case::no_distinct_id(AiRejection::DistinctIdEmpty, Some(WarningType::MissingDistinctId))]
    #[case::no_uuid(AiRejection::EventUuidRequired, Some(WarningType::MissingEventUuid))]
    #[case::bad_uuid(
        AiRejection::EventUuidInvalid("nope".to_string()),
        Some(WarningType::InvalidEventUuid)
    )]
    #[case::oversize(
        AiRejection::EventAndPropertiesTooBig { size: 1, max: 0 },
        Some(WarningType::MessageSizeTooLarge)
    )]
    #[case::bad_properties(
        AiRejection::PropertiesPartNotJson,
        Some(WarningType::MalformedEventProperties)
    )]
    #[case::bad_multipart(AiRejection::NotMultipart, Some(WarningType::InvalidAiPayload))]
    // Truncated or aborted body: fault is ambiguous, so nothing is emitted.
    #[case::truncated_stream(AiRejection::MultipartParseFailed("eof".to_string()), None)]
    #[case::truncated_field(AiRejection::FieldDataUnreadable("eof".to_string()), None)]
    #[case::blob_style_part(
        AiRejection::UnknownField("event.properties.x".to_string()),
        Some(WarningType::InvalidAiPayload)
    )]
    fn rejections_map_to_their_warning(
        #[case] rejection: AiRejection,
        #[case] expected: Option<WarningType>,
    ) {
        assert_eq!(warning_for_ai_rejection(&rejection), expected);
    }

    // Same trust chain the other pipelines pin: an emitted type that is not
    // capture-produced is demoted to a generic client warning at the consumer,
    // and one on both routes breaks the common crate's one-route invariant.
    // Both fail silently in production. Covers every variant, so a new one
    // can't slip in mapped to an untrusted type.
    #[test]
    fn every_rejection_maps_to_a_trusted_single_routed_type() {
        let mut silent = Vec::new();

        for rejection in crate::ai_rejection::all_variants() {
            let Some(warning) = warning_for_ai_rejection(&rejection) else {
                silent.push(rejection);
                continue;
            };
            assert!(
                warning.capture_produced(),
                "{rejection:?} maps to {warning:?}, which is not on the consumer trust allowlist"
            );
            let tag_routed = WarningType::from_tag(warning.as_str()) == Some(warning);
            let direct = WarningType::DIRECT_EMIT.contains(&warning);
            assert!(
                tag_routed ^ direct,
                "{warning:?} must be on exactly one emit route"
            );
        }

        // Pinned rather than merely allowed: staying silent is a judgment call
        // about fault, so a third variant joining this set should be a decision
        // someone made here, not a mapping someone forgot. Compared by variant,
        // since the payload values are placeholders.
        let silent: Vec<_> = silent.iter().map(std::mem::discriminant).collect();
        let expected = [
            AiRejection::MultipartParseFailed(String::new()),
            AiRejection::FieldDataUnreadable(String::new()),
        ];
        assert_eq!(
            silent,
            expected
                .iter()
                .map(std::mem::discriminant)
                .collect::<Vec<_>>(),
            "the set of rejections that emit nothing changed"
        );
    }

    #[test]
    fn wrong_event_name_reports_the_name_and_what_was_expected() {
        let emitter = CollectingEmitter::default();
        emit_ai_failure_warning(
            Some(&emitter),
            &request(),
            &AiFailure::Rejected(AiRejection::EventNameNotAllowed("$pageview".to_string())),
        );

        let emitted = emitter.emitted();
        assert_eq!(emitted.len(), 1);
        let warning = &emitted[0];
        assert_eq!(warning.warning, WarningType::InvalidAiEvent);
        assert_eq!(warning.source, CAPTURE_AI_EVENTS);
        // One request is one event.
        assert_eq!(warning.count, 1);
        assert_eq!(
            warning.extra_details.get("eventName"),
            Some(&json!("$pageview"))
        );
        assert_eq!(
            warning.extra_details.get("lib"),
            Some(&json!("posthog-python"))
        );
        assert_eq!(warning.extra_details.get("path"), Some(&json!("/i/v0/ai")));
    }

    #[test]
    fn unknown_field_rejection_names_the_part_but_not_the_error_message() {
        let emitter = CollectingEmitter::default();
        emit_ai_failure_warning(
            Some(&emitter),
            &request(),
            &AiFailure::Rejected(AiRejection::UnknownField(
                "event.properties.image".to_string(),
            )),
        );

        let emitted = emitter.emitted();
        assert_eq!(emitted.len(), 1);
        assert_eq!(
            emitted[0].extra_details.get("part"),
            Some(&json!("event.properties.image"))
        );
        assert!(!emitted[0].extra_details.contains_key("message"));
    }

    #[test]
    fn oversize_rejection_reports_size_against_the_limit() {
        let emitter = CollectingEmitter::default();
        emit_ai_failure_warning(
            Some(&emitter),
            &request(),
            &AiFailure::Rejected(AiRejection::EventAndPropertiesTooBig {
                size: 1_000_000,
                max: 983_040,
            }),
        );

        let emitted = emitter.emitted();
        assert_eq!(emitted[0].warning, WarningType::MessageSizeTooLarge);
        assert_eq!(
            emitted[0].extra_details.get("size"),
            Some(&json!(1_000_000))
        );
        assert_eq!(emitted[0].extra_details.get("limit"), Some(&json!(983_040)));
    }

    // The gzip decompressor is the one shared helper the handler calls after
    // reading the token, so both its failures are attributable and actionable
    // even though neither is an AiRejection.
    #[rstest]
    #[case::oversize(
        CaptureError::EventTooBig("too big".to_string()),
        WarningType::MessageSizeTooLarge
    )]
    #[case::corrupt_gzip(
        CaptureError::RequestDecodingError("invalid GZIP data".to_string()),
        WarningType::InvalidAiPayload
    )]
    fn gzip_failures_warn(#[case] err: CaptureError, #[case] expected: WarningType) {
        let emitter = CollectingEmitter::default();
        emit_ai_failure_warning(Some(&emitter), &request(), &AiFailure::Other(err));

        let emitted = emitter.emitted();
        assert_eq!(emitted.len(), 1);
        assert_eq!(emitted[0].warning, expected);
    }

    #[rstest]
    #[case::quota(CaptureError::BillingLimit)]
    #[case::service_unavailable(CaptureError::ServiceUnavailable("down".to_string()))]
    #[case::serialization(CaptureError::NonRetryableSinkError)]
    #[case::kafka(CaptureError::RetryableSinkError)]
    #[case::internal(CaptureError::InternalError("boom".to_string()))]
    fn our_failures_never_warn(#[case] err: CaptureError) {
        let emitter = CollectingEmitter::default();
        emit_ai_failure_warning(Some(&emitter), &request(), &AiFailure::Other(err));
        assert!(emitter.emitted().is_empty());
    }

    // Details are client-controlled and nothing downstream length-limits them,
    // so an oversized event name or part name must not inflate the warning
    // message or its stored row. Truncation is marked and char-safe.
    #[rstest]
    #[case::event_name(
        AiRejection::EventNameNotAllowed("$".to_string() + &"n".repeat(500)),
        "eventName"
    )]
    #[case::part_name(
        AiRejection::UnknownField("f".repeat(500)),
        "part"
    )]
    fn oversized_client_values_are_bounded(#[case] rejection: AiRejection, #[case] key: &str) {
        let emitter = CollectingEmitter::default();
        emit_ai_failure_warning(Some(&emitter), &request(), &AiFailure::Rejected(rejection));

        let emitted = emitter.emitted();
        let value = emitted[0].extra_details[key]
            .as_str()
            .expect("string detail");
        assert!(
            value.chars().count() <= crate::ingestion_warnings::MAX_SDK_ATTRIBUTION_LEN + 1,
            "{key} was not bounded: {} chars",
            value.chars().count()
        );
        assert!(value.ends_with('\u{2026}'), "{key} should mark truncation");
    }

    // A multi-byte name must not be cut mid-character, which would produce
    // invalid UTF-8 in the warning payload.
    #[test]
    fn bounding_respects_char_boundaries() {
        let emitter = CollectingEmitter::default();
        emit_ai_failure_warning(
            Some(&emitter),
            &request(),
            &AiFailure::Rejected(AiRejection::UnknownField("\u{4f60}\u{597d}".repeat(200))),
        );

        let emitted = emitter.emitted();
        let value = emitted[0].extra_details["part"]
            .as_str()
            .expect("string detail");
        assert!(value.ends_with('\u{2026}'));
        // Round-trips as valid UTF-8 with whole characters only.
        assert!(value
            .trim_end_matches('\u{2026}')
            .chars()
            .all(|c| c == '\u{4f60}' || c == '\u{597d}'));
    }

    #[test]
    fn no_emitter_is_a_silent_no_op() {
        emit_ai_failure_warning(
            None,
            &request(),
            &AiFailure::Rejected(AiRejection::AiModelMissing),
        );
    }
}
