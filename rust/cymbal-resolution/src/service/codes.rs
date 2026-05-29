//! Error and retry code constants surfaced to the caller in v1. Defined near the
//! handler so test fixtures and client retry classification stay in sync as the
//! taxonomy evolves. See cymbal-proto's ItemOutcome.Error/Retry for envelope.

/// The caller-supplied exception/debug-image payload could not be parsed.
pub const ERROR_INVALID_PAYLOAD: &str = "invalid_payload";
/// The handler encountered an unhandled internal error while resolving.
pub const ERROR_UNHANDLED: &str = "unhandled";
/// The service refused the item because it could not acquire a
/// symbol-resolution permit before its deadline. Cymbal may retry the
/// item against another endpoint per caller-side policy.
pub const RETRY_OVERLOADED: &str = "overloaded";
