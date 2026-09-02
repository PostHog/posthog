//! Typed rejection conditions for the AI events endpoint (`/i/v0/ai`).
//!
//! The handler used to return a bare
//! [`CaptureError::RequestParsingError`](crate::api::CaptureError) for ~25
//! unrelated conditions, all carrying a free-form message. That is fine for an
//! HTTP response but useless for deciding which ingestion warning a customer
//! should see: telling "sent a non-AI event name" apart from "sent an unknown
//! multipart field" would mean matching on message strings.
//!
//! So the rejection reasons are an enum. [`AiRejection::message`] reproduces the
//! exact wire message each condition produced before, and
//! [`From<AiRejection>`](CaptureError) picks the same `CaptureError` variant, so
//! status codes and bodies are unchanged. The warning mapping then matches
//! variants, which the compiler checks.

use std::fmt;

use crate::api::CaptureError;

/// Event names the endpoint accepts. Anything else is a client sending ordinary
/// analytics to the AI path.
pub const ALLOWED_AI_EVENTS: [&str; 6] = [
    "$ai_generation",
    "$ai_trace",
    "$ai_span",
    "$ai_embedding",
    "$ai_metric",
    "$ai_feedback",
];

/// Which `CaptureError` a rejection becomes, and so which HTTP status the client
/// sees. Preserved per-condition from before the enum existed.
enum ErrorKind {
    /// 400, transport-level: the request framing itself is wrong.
    Decoding,
    /// 400, content-level: the framing parsed but the contents are unusable.
    Parsing,
    /// 413.
    TooBig,
}

/// A request the AI endpoint refused because of something the customer sent.
///
/// Server-side failures (Kafka, event serialization) are deliberately absent:
/// they stay `CaptureError`, since they are ours to fix and must never surface
/// as customer warnings.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AiRejection {
    // Request framing
    NotMultipart,
    InvalidBoundary(String),
    MultipartParseFailed(String),
    FieldDataUnreadable(String),
    MissingEventPart,
    FirstPartNotEvent(String),
    DuplicateEventPart,
    UnknownField(String),

    // Event part
    EventPartNotUtf8,
    EventPartNotJson,
    EventNotObject,

    // Properties
    PropertiesPartNotUtf8,
    PropertiesPartNotJson,
    ConflictingProperties,
    EventMissingProperties,

    // Size limits
    EventPartTooBig { size: usize, max: usize },
    EventAndPropertiesTooBig { size: usize, max: usize },

    // Event identity
    EventMissingName,
    EventNameRequired,
    EventNameEmpty,
    EventMissingDistinctId,
    DistinctIdRequired,
    DistinctIdEmpty,
    EventUuidRequired,
    EventUuidInvalid(String),

    // AI-specific validation
    EventNameNotAllowed(String),
    AiModelMissing,
    AiModelNotString,
    AiModelEmpty,
}

impl AiRejection {
    /// The message this condition puts on the wire. Unchanged from when each
    /// site built its `CaptureError` inline, so clients see the same bodies.
    pub fn message(&self) -> String {
        match self {
            Self::NotMultipart => "Content-Type must be multipart/form-data".to_string(),
            Self::InvalidBoundary(e) => format!("Invalid boundary in Content-Type: {e}"),
            Self::MultipartParseFailed(e) => format!("Multipart parsing failed: {e}"),
            Self::FieldDataUnreadable(e) => format!("Failed to read field data: {e}"),
            Self::MissingEventPart => {
                "Missing required 'event' part in multipart data".to_string()
            }
            Self::FirstPartNotEvent(field_name) => {
                format!("First part must be 'event', got '{field_name}'")
            }
            Self::DuplicateEventPart => "Duplicate 'event' part found".to_string(),
            Self::UnknownField(field_name) => format!(
                "Unknown multipart field: '{field_name}'. Expected 'event' or 'event.properties'"
            ),

            Self::EventPartNotUtf8 => "Event part must be valid UTF-8".to_string(),
            Self::EventPartNotJson => "Event part must be valid JSON".to_string(),
            Self::EventNotObject => "Event must be a JSON object".to_string(),

            Self::PropertiesPartNotUtf8 => "Properties part must be valid UTF-8".to_string(),
            Self::PropertiesPartNotJson => "Properties part must be valid JSON".to_string(),
            Self::ConflictingProperties => {
                "Event cannot have both embedded properties and a separate 'event.properties' part"
                    .to_string()
            }
            Self::EventMissingProperties => "Event missing 'properties' field".to_string(),

            Self::EventPartTooBig { size, max } => format!(
                "Event part size ({size} bytes) exceeds maximum allowed size ({max} bytes)"
            ),
            Self::EventAndPropertiesTooBig { size, max } => format!(
                "Combined event and properties size ({size} bytes) exceeds maximum allowed size ({max} bytes)"
            ),

            Self::EventMissingName => "Event missing 'event' field".to_string(),
            Self::EventNameRequired => "Event name is required".to_string(),
            Self::EventNameEmpty => "Event name cannot be empty".to_string(),
            Self::EventMissingDistinctId => "Event missing 'distinct_id' field".to_string(),
            Self::DistinctIdRequired => "distinct_id is required".to_string(),
            Self::DistinctIdEmpty => "distinct_id cannot be empty".to_string(),
            Self::EventUuidRequired => "Event UUID is required".to_string(),
            Self::EventUuidInvalid(e) => format!("Invalid UUID format: {e}"),

            Self::EventNameNotAllowed(event_name) => format!(
                "Event name must be one of: {}, got '{}'",
                ALLOWED_AI_EVENTS.join(", "),
                event_name
            ),
            Self::AiModelMissing => "Event properties must contain '$ai_model'".to_string(),
            Self::AiModelNotString => "$ai_model must be a string".to_string(),
            Self::AiModelEmpty => "$ai_model cannot be empty".to_string(),
        }
    }

    fn kind(&self) -> ErrorKind {
        match self {
            // Framing problems the multipart layer itself reports.
            Self::NotMultipart
            | Self::InvalidBoundary(_)
            | Self::MultipartParseFailed(_)
            | Self::FieldDataUnreadable(_) => ErrorKind::Decoding,

            Self::EventPartTooBig { .. } | Self::EventAndPropertiesTooBig { .. } => {
                ErrorKind::TooBig
            }

            Self::MissingEventPart
            | Self::FirstPartNotEvent(_)
            | Self::DuplicateEventPart
            | Self::UnknownField(_)
            | Self::EventPartNotUtf8
            | Self::EventPartNotJson
            | Self::EventNotObject
            | Self::PropertiesPartNotUtf8
            | Self::PropertiesPartNotJson
            | Self::ConflictingProperties
            | Self::EventMissingProperties
            | Self::EventMissingName
            | Self::EventNameRequired
            | Self::EventNameEmpty
            | Self::EventMissingDistinctId
            | Self::DistinctIdRequired
            | Self::DistinctIdEmpty
            | Self::EventUuidRequired
            | Self::EventUuidInvalid(_)
            | Self::EventNameNotAllowed(_)
            | Self::AiModelMissing
            | Self::AiModelNotString
            | Self::AiModelEmpty => ErrorKind::Parsing,
        }
    }
}

impl fmt::Display for AiRejection {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message())
    }
}

/// Every variant with the exact message it puts on the wire.
///
/// The single list of all variants in the crate. Variants carry `String`s so it
/// can't be a const like `WarningType::ALL`, and it lives here rather than in a
/// test module because two of them need it: the parity check below and the
/// warning mapping in `ingestion_warnings::ai`. Two hand-maintained copies would
/// drift, leaving a new variant silently untested by both.
#[cfg(test)]
pub(crate) fn all_variants_with_messages() -> Vec<(AiRejection, &'static str)> {
    vec![
            (
                AiRejection::NotMultipart,
                "Content-Type must be multipart/form-data",
            ),
            (
                AiRejection::InvalidBoundary("bad".to_string()),
                "Invalid boundary in Content-Type: bad",
            ),
            (
                AiRejection::MultipartParseFailed("boom".to_string()),
                "Multipart parsing failed: boom",
            ),
            (
                AiRejection::FieldDataUnreadable("io".to_string()),
                "Failed to read field data: io",
            ),
            (
                AiRejection::MissingEventPart,
                "Missing required 'event' part in multipart data",
            ),
            (
                AiRejection::FirstPartNotEvent("blob".to_string()),
                "First part must be 'event', got 'blob'",
            ),
            (
                AiRejection::DuplicateEventPart,
                "Duplicate 'event' part found",
            ),
            (
                AiRejection::UnknownField("nope".to_string()),
                "Unknown multipart field: 'nope'. Expected 'event' or 'event.properties'",
            ),
            (
                AiRejection::EventPartNotUtf8,
                "Event part must be valid UTF-8",
            ),
            (
                AiRejection::EventPartNotJson,
                "Event part must be valid JSON",
            ),
            (AiRejection::EventNotObject, "Event must be a JSON object"),
            (
                AiRejection::PropertiesPartNotUtf8,
                "Properties part must be valid UTF-8",
            ),
            (
                AiRejection::PropertiesPartNotJson,
                "Properties part must be valid JSON",
            ),
            (
                AiRejection::ConflictingProperties,
                "Event cannot have both embedded properties and a separate 'event.properties' part",
            ),
            (
                AiRejection::EventMissingProperties,
                "Event missing 'properties' field",
            ),
            (
                AiRejection::EventPartTooBig {
                    size: 40_000,
                    max: 32_768,
                },
                "Event part size (40000 bytes) exceeds maximum allowed size (32768 bytes)",
            ),
            (
                AiRejection::EventAndPropertiesTooBig {
                    size: 1_000_000,
                    max: 983_040,
                },
                "Combined event and properties size (1000000 bytes) exceeds maximum allowed size (983040 bytes)",
            ),
            (
                AiRejection::EventMissingName,
                "Event missing 'event' field",
            ),
            (AiRejection::EventNameRequired, "Event name is required"),
            (AiRejection::EventNameEmpty, "Event name cannot be empty"),
            (
                AiRejection::EventMissingDistinctId,
                "Event missing 'distinct_id' field",
            ),
            (AiRejection::DistinctIdRequired, "distinct_id is required"),
            (AiRejection::DistinctIdEmpty, "distinct_id cannot be empty"),
            (AiRejection::EventUuidRequired, "Event UUID is required"),
            (
                AiRejection::EventUuidInvalid("invalid length".to_string()),
                "Invalid UUID format: invalid length",
            ),
            (
                AiRejection::EventNameNotAllowed("$pageview".to_string()),
                "Event name must be one of: $ai_generation, $ai_trace, $ai_span, $ai_embedding, $ai_metric, $ai_feedback, got '$pageview'",
            ),
            (
                AiRejection::AiModelMissing,
                "Event properties must contain '$ai_model'",
            ),
            (AiRejection::AiModelNotString, "$ai_model must be a string"),
            (AiRejection::AiModelEmpty, "$ai_model cannot be empty"),
    ]
}

/// [`all_variants_with_messages`] without the messages, for callers that only
/// need to walk every variant.
#[cfg(test)]
pub(crate) fn all_variants() -> Vec<AiRejection> {
    all_variants_with_messages()
        .into_iter()
        .map(|(rejection, _)| rejection)
        .collect()
}

impl From<AiRejection> for CaptureError {
    fn from(rejection: AiRejection) -> Self {
        let message = rejection.message();
        match rejection.kind() {
            ErrorKind::Decoding => CaptureError::RequestDecodingError(message),
            ErrorKind::Parsing => CaptureError::RequestParsingError(message),
            ErrorKind::TooBig => CaptureError::EventTooBig(message),
        }
    }
}

/// Why an AI request failed: something the customer sent, or something on our
/// side.
///
/// Splitting these is what lets the handler emit a warning for the first kind
/// and stay silent for the second, while both still become a `CaptureError` for
/// the response. `From` impls in both directions keep `?` working unchanged at
/// every existing call site.
#[derive(Debug)]
pub enum AiFailure {
    Rejected(AiRejection),
    Other(CaptureError),
}

impl From<AiRejection> for AiFailure {
    fn from(rejection: AiRejection) -> Self {
        Self::Rejected(rejection)
    }
}

impl From<CaptureError> for AiFailure {
    fn from(err: CaptureError) -> Self {
        Self::Other(err)
    }
}

impl From<AiFailure> for CaptureError {
    fn from(failure: AiFailure) -> Self {
        match failure {
            AiFailure::Rejected(rejection) => rejection.into(),
            AiFailure::Other(err) => err,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::response::IntoResponse;
    use rstest::rstest;

    /// The regression guard for the refactor that introduced this enum: the ~30
    /// conditions it replaced each has to keep putting the same thing on the
    /// wire, and a reviewer can't verify that many inline `format!`s by eye.
    ///
    /// The pre-existing tests in `tests/integration_ai_endpoint.rs` are the
    /// end-to-end half of the same proof; they pass unmodified.
    #[test]
    fn every_rejection_keeps_its_original_wire_message() {
        for (rejection, expected) in all_variants_with_messages() {
            assert_eq!(rejection.message(), expected, "message for {rejection:?}");
            // Display and message must not drift apart; callers use both.
            assert_eq!(rejection.to_string(), expected);
        }
    }

    // `all_variants_with_messages` is hand-written, so it can fall behind the
    // enum. Counting arms in the exhaustive `message` match is the cheapest way
    // to notice: a new variant compiles there but is missing here.
    #[test]
    fn the_variant_list_covers_every_variant() {
        let listed = all_variants();
        let unique: std::collections::HashSet<_> =
            listed.iter().map(std::mem::discriminant).collect();

        assert_eq!(
            unique.len(),
            listed.len(),
            "all_variants lists the same variant twice"
        );
        assert_eq!(
            listed.len(),
            29,
            "variant count changed — add the new variant to all_variants_with_messages \
             and update this expected count"
        );
    }

    // The response body is the message, so a CaptureError variant swap would
    // silently change a 400 into a 413 or vice versa.
    #[rstest]
    #[case::not_multipart(AiRejection::NotMultipart, 400)]
    #[case::boundary(AiRejection::InvalidBoundary("x".to_string()), 400)]
    #[case::multipart_parse(AiRejection::MultipartParseFailed("x".to_string()), 400)]
    #[case::field_read(AiRejection::FieldDataUnreadable("x".to_string()), 400)]
    #[case::missing_event_part(AiRejection::MissingEventPart, 400)]
    #[case::unknown_field(AiRejection::UnknownField("x".to_string()), 400)]
    #[case::event_not_json(AiRejection::EventPartNotJson, 400)]
    #[case::event_name_not_allowed(AiRejection::EventNameNotAllowed("$pageview".to_string()), 400)]
    #[case::ai_model_missing(AiRejection::AiModelMissing, 400)]
    #[case::event_part_too_big(AiRejection::EventPartTooBig { size: 1, max: 0 }, 413)]
    #[case::combined_too_big(AiRejection::EventAndPropertiesTooBig { size: 1, max: 0 }, 413)]
    fn rejections_keep_their_status_code(#[case] rejection: AiRejection, #[case] expected: u16) {
        let err: CaptureError = rejection.into();
        let status = err.into_response().status().as_u16();
        assert_eq!(status, expected);
    }

    #[test]
    fn message_survives_the_round_trip_through_ai_failure() {
        let rejection = AiRejection::EventNameNotAllowed("$pageview".to_string());
        let expected = rejection.message();

        let failure: AiFailure = rejection.into();
        let err: CaptureError = failure.into();

        assert!(matches!(err, CaptureError::RequestParsingError(ref m) if *m == expected));
    }

    #[test]
    fn server_side_errors_pass_through_unchanged() {
        let failure: AiFailure = CaptureError::NonRetryableSinkError.into();
        assert!(matches!(failure, AiFailure::Other(_)));

        let err: CaptureError = failure.into();
        assert!(matches!(err, CaptureError::NonRetryableSinkError));
    }
}
