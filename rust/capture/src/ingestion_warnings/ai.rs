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

use crate::ai_rejection::{AiFailure, AiRejection};
use crate::api::CaptureError;

/// Map a rejection to the warning the customer should see.
///
/// Five of these reuse types the analytics paths already emit, because the
/// condition is identical and a reader of the v2 table shouldn't have to learn a
/// second vocabulary for the same mistake. The AI-specific types cover what has
/// no analytics equivalent: this endpoint accepts only six event names and
/// requires `$ai_model`, and its payload is multipart rather than a JSON batch.
///
/// Exhaustive with no catch-all, so a new rejection variant fails to compile
/// until someone decides whether customers should see a warning for it.
pub fn warning_for_ai_rejection(rejection: &AiRejection) -> WarningType {
    match rejection {
        // Sending ordinary analytics to the AI path, or omitting the one
        // property every AI event needs.
        AiRejection::EventNameNotAllowed(_)
        | AiRejection::AiModelMissing
        | AiRejection::AiModelNotString
        | AiRejection::AiModelEmpty => WarningType::InvalidAiEvent,

        // Shared with the analytics paths: same mistake, same type.
        AiRejection::EventMissingName
        | AiRejection::EventNameRequired
        | AiRejection::EventNameEmpty => WarningType::MissingEventName,
        AiRejection::EventMissingDistinctId
        | AiRejection::DistinctIdRequired
        | AiRejection::DistinctIdEmpty => WarningType::MissingDistinctId,
        AiRejection::EventUuidRequired => WarningType::MissingEventUuid,
        AiRejection::EventUuidInvalid(_) => WarningType::InvalidEventUuid,
        AiRejection::EventPartTooBig { .. }
        | AiRejection::EventAndPropertiesTooBig { .. }
        | AiRejection::SumOfPartsTooBig { .. } => WarningType::MessageSizeTooLarge,

        // The properties object specifically is missing or unreadable.
        AiRejection::EventMissingProperties
        | AiRejection::PropertiesPartNotUtf8
        | AiRejection::PropertiesPartNotJson => WarningType::MalformedEventProperties,

        // Everything structural about the multipart request itself.
        AiRejection::NotMultipart
        | AiRejection::InvalidBoundary(_)
        | AiRejection::MultipartParseFailed(_)
        | AiRejection::FieldDataUnreadable(_)
        | AiRejection::MissingEventPart
        | AiRejection::FirstPartNotEvent(_)
        | AiRejection::DuplicateEventPart
        | AiRejection::UnknownField(_)
        | AiRejection::EventPartNotUtf8
        | AiRejection::EventPartNotJson
        | AiRejection::EventNotObject
        | AiRejection::ConflictingProperties
        | AiRejection::BlobContentTypeMissing(_)
        | AiRejection::BlobContentTypeUnsupported { .. }
        | AiRejection::BlobEmpty(_)
        | AiRejection::BlobPropertyNested(_)
        | AiRejection::BlobPropertyDuplicate(_) => WarningType::InvalidAiPayload,
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
            Some((warning_for_ai_rejection(rejection), details_for(rejection)))
        }
        // The gzip decompressor raises this after the token is read, when the
        // decompressed body would exceed the endpoint's limit. Every other
        // `CaptureError` reaching here is ours: quota is surfaced through
        // billing, and blob storage, S3, and Kafka failures are not the
        // customer's to fix.
        AiFailure::Other(CaptureError::EventTooBig(_)) => {
            Some((WarningType::MessageSizeTooLarge, Map::new()))
        }
        AiFailure::Other(_) => None,
    }
}

/// Per-rejection details.
///
/// Only values that are safe to show and useful to act on: the rejected event
/// name, the offending part name, and sizes. The rejection's own message is
/// deliberately excluded — several embed a library error string, and this lands
/// in a customer-visible column.
fn details_for(rejection: &AiRejection) -> Map<String, serde_json::Value> {
    let mut details = Map::new();
    match rejection {
        AiRejection::EventNameNotAllowed(event_name) => {
            details.insert("eventName".to_string(), json!(event_name));
            details.insert(
                "allowed".to_string(),
                json!(crate::ai_rejection::ALLOWED_AI_EVENTS),
            );
        }
        AiRejection::FirstPartNotEvent(field)
        | AiRejection::UnknownField(field)
        | AiRejection::BlobContentTypeMissing(field)
        | AiRejection::BlobEmpty(field)
        | AiRejection::BlobPropertyNested(field)
        | AiRejection::BlobPropertyDuplicate(field) => {
            details.insert("part".to_string(), json!(field));
        }
        AiRejection::BlobContentTypeUnsupported {
            field,
            content_type,
        } => {
            details.insert("part".to_string(), json!(field));
            details.insert("contentType".to_string(), json!(content_type));
        }
        AiRejection::EventPartTooBig { size, max }
        | AiRejection::EventAndPropertiesTooBig { size, max }
        | AiRejection::SumOfPartsTooBig { size, max } => {
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
        WarningType::InvalidAiEvent
    )]
    #[case::no_model(AiRejection::AiModelMissing, WarningType::InvalidAiEvent)]
    #[case::no_event_name(AiRejection::EventNameRequired, WarningType::MissingEventName)]
    #[case::no_distinct_id(AiRejection::DistinctIdEmpty, WarningType::MissingDistinctId)]
    #[case::no_uuid(AiRejection::EventUuidRequired, WarningType::MissingEventUuid)]
    #[case::bad_uuid(
        AiRejection::EventUuidInvalid("nope".to_string()),
        WarningType::InvalidEventUuid
    )]
    #[case::oversize(
        AiRejection::SumOfPartsTooBig { size: 1, max: 0 },
        WarningType::MessageSizeTooLarge
    )]
    #[case::bad_properties(
        AiRejection::PropertiesPartNotJson,
        WarningType::MalformedEventProperties
    )]
    #[case::bad_multipart(AiRejection::NotMultipart, WarningType::InvalidAiPayload)]
    #[case::bad_blob(
        AiRejection::BlobEmpty("event.properties.x".to_string()),
        WarningType::InvalidAiPayload
    )]
    fn rejections_map_to_their_warning(
        #[case] rejection: AiRejection,
        #[case] expected: WarningType,
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
        let all = [
            AiRejection::NotMultipart,
            AiRejection::InvalidBoundary("x".to_string()),
            AiRejection::MultipartParseFailed("x".to_string()),
            AiRejection::FieldDataUnreadable("x".to_string()),
            AiRejection::MissingEventPart,
            AiRejection::FirstPartNotEvent("x".to_string()),
            AiRejection::DuplicateEventPart,
            AiRejection::UnknownField("x".to_string()),
            AiRejection::EventPartNotUtf8,
            AiRejection::EventPartNotJson,
            AiRejection::EventNotObject,
            AiRejection::PropertiesPartNotUtf8,
            AiRejection::PropertiesPartNotJson,
            AiRejection::ConflictingProperties,
            AiRejection::EventMissingProperties,
            AiRejection::BlobContentTypeMissing("x".to_string()),
            AiRejection::BlobContentTypeUnsupported {
                field: "x".to_string(),
                content_type: "y".to_string(),
            },
            AiRejection::BlobEmpty("x".to_string()),
            AiRejection::BlobPropertyNested("x".to_string()),
            AiRejection::BlobPropertyDuplicate("x".to_string()),
            AiRejection::EventPartTooBig { size: 1, max: 0 },
            AiRejection::EventAndPropertiesTooBig { size: 1, max: 0 },
            AiRejection::SumOfPartsTooBig { size: 1, max: 0 },
            AiRejection::EventMissingName,
            AiRejection::EventNameRequired,
            AiRejection::EventNameEmpty,
            AiRejection::EventMissingDistinctId,
            AiRejection::DistinctIdRequired,
            AiRejection::DistinctIdEmpty,
            AiRejection::EventUuidRequired,
            AiRejection::EventUuidInvalid("x".to_string()),
            AiRejection::EventNameNotAllowed("x".to_string()),
            AiRejection::AiModelMissing,
            AiRejection::AiModelNotString,
            AiRejection::AiModelEmpty,
        ];

        for rejection in &all {
            let warning = warning_for_ai_rejection(rejection);
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
    fn blob_rejection_names_the_part_but_not_the_error_message() {
        let emitter = CollectingEmitter::default();
        emit_ai_failure_warning(
            Some(&emitter),
            &request(),
            &AiFailure::Rejected(AiRejection::BlobContentTypeUnsupported {
                field: "event.properties.image".to_string(),
                content_type: "image/png".to_string(),
            }),
        );

        let emitted = emitter.emitted();
        assert_eq!(emitted.len(), 1);
        assert_eq!(
            emitted[0].extra_details.get("part"),
            Some(&json!("event.properties.image"))
        );
        assert_eq!(
            emitted[0].extra_details.get("contentType"),
            Some(&json!("image/png"))
        );
        assert!(!emitted[0].extra_details.contains_key("message"));
    }

    #[test]
    fn oversize_rejection_reports_size_against_the_limit() {
        let emitter = CollectingEmitter::default();
        emit_ai_failure_warning(
            Some(&emitter),
            &request(),
            &AiFailure::Rejected(AiRejection::SumOfPartsTooBig {
                size: 30_000_000,
                max: 26_214_400,
            }),
        );

        let emitted = emitter.emitted();
        assert_eq!(emitted[0].warning, WarningType::MessageSizeTooLarge);
        assert_eq!(
            emitted[0].extra_details.get("size"),
            Some(&json!(30_000_000))
        );
        assert_eq!(
            emitted[0].extra_details.get("limit"),
            Some(&json!(26_214_400))
        );
    }

    // The gzip decompressor raises EventTooBig after the token is read, so it is
    // attributable even though it is not an AiRejection.
    #[test]
    fn oversize_decompressed_body_warns() {
        let emitter = CollectingEmitter::default();
        emit_ai_failure_warning(
            Some(&emitter),
            &request(),
            &AiFailure::Other(CaptureError::EventTooBig("too big".to_string())),
        );

        let emitted = emitter.emitted();
        assert_eq!(emitted.len(), 1);
        assert_eq!(emitted[0].warning, WarningType::MessageSizeTooLarge);
    }

    #[rstest]
    #[case::quota(CaptureError::BillingLimit)]
    #[case::blob_storage(CaptureError::ServiceUnavailable("no s3".to_string()))]
    #[case::s3_upload(CaptureError::NonRetryableSinkError)]
    #[case::kafka(CaptureError::RetryableSinkError)]
    #[case::internal(CaptureError::InternalError("boom".to_string()))]
    fn our_failures_never_warn(#[case] err: CaptureError) {
        let emitter = CollectingEmitter::default();
        emit_ai_failure_warning(Some(&emitter), &request(), &AiFailure::Other(err));
        assert!(emitter.emitted().is_empty());
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
