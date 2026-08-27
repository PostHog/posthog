//! Personhog's gRPC protocol semantics. The generic serving layer —
//! metrics, load shedding, connection tracking, caller task-locals —
//! lives in `common-grpc`.

use std::sync::Arc;

use common_grpc::current_client_name;
use metrics::gauge;

/// Metadata key marking a FAILED_PRECONDITION as a definitive semantic
/// refusal rather than a routing-race rejection. The router bounces and
/// retries bare FAILED_PRECONDITION (handoff fences, ownership races,
/// person fences — conditions that clear in watch or healer time) and
/// surfaces exhaustion as retriable UNAVAILABLE; a response carrying this
/// key is a final answer about the request itself and must pass through
/// to the caller unchanged, or a fail-closed refusal degrades into an
/// infinite retry loop. The value is a short reason slug for
/// observability.
pub const SEMANTIC_REFUSAL_METADATA_KEY: &str = "x-semantic-refusal";

/// Build a semantic refusal. The reason is a short slug used as a metric
/// label.
pub fn semantic_refusal(message: impl Into<String>, reason: &'static str) -> tonic::Status {
    let mut status = tonic::Status::failed_precondition(message.into());
    if let Ok(value) = reason.parse() {
        status
            .metadata_mut()
            .insert(SEMANTIC_REFUSAL_METADATA_KEY, value);
    }
    status
}

/// Whether a status is a definitive semantic refusal rather than a
/// transient failure a retry can outlive.
pub fn is_semantic_refusal(status: &tonic::Status) -> bool {
    status.code() == tonic::Code::FailedPrecondition
        && status
            .metadata()
            .contains_key(SEMANTIC_REFUSAL_METADATA_KEY)
}

/// The refusal's reason slug, when present.
pub fn semantic_refusal_reason(status: &tonic::Status) -> Option<&str> {
    status
        .metadata()
        .get(SEMANTIC_REFUSAL_METADATA_KEY)
        .and_then(|v| v.to_str().ok())
}

/// Drop guard that decrements a client-side in-flight gauge on drop,
/// ensuring cancellation-safety for outbound request tracking.
pub struct ClientInFlightGuard {
    pub backend: &'static str,
    client: Arc<str>,
}

impl ClientInFlightGuard {
    pub fn new(backend: &'static str) -> Self {
        let client = current_client_name();
        gauge!("personhog_router_client_requests_in_flight", "backend" => backend, "client" => client.clone())
            .increment(1.0);
        Self { backend, client }
    }
}

impl Drop for ClientInFlightGuard {
    fn drop(&mut self) {
        gauge!("personhog_router_client_requests_in_flight", "backend" => self.backend, "client" => self.client.clone())
            .decrement(1.0);
    }
}
