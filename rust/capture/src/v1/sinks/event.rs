use crate::v1::context::Context;
use crate::v1::sinks::Destination;

/// Transport-agnostic trait declaring an event's identity, routing intent,
/// metadata, and serialization. The [`Sink`](super::sink::Sink) implementation
/// resolves `destination()` to a concrete backend target using its own config.
pub trait Event: Send + Sync {
    /// UUID of the originating event -- correlation key for mapping results back.
    fn uuid_key(&self) -> &str;

    /// Whether this event should be published. Events returning false are
    /// silently skipped by the Sink -- no `SinkResult` is returned for them.
    fn should_publish(&self) -> bool;

    /// Semantic routing destination. The Sink resolves this to a concrete
    /// backend target (e.g. Kafka topic) using its own config.
    fn destination(&self) -> &Destination;

    /// Event-owned metadata as key-value pairs. The Sink merges these with
    /// context-level headers before converting to transport-specific format.
    fn headers(&self) -> Vec<(String, String)>;

    /// Write the partition/routing key into a caller-provided buffer.
    /// The caller clears `buf` between events; implementations just append.
    fn write_partition_key(&self, ctx: &Context, buf: &mut String);

    /// Serialize the event payload into a caller-provided buffer.
    /// The caller clears `buf` between events; implementations just append.
    fn serialize_into(&self, ctx: &Context, buf: &mut String) -> Result<(), String>;
}

/// Build the context-level headers that are identical for every event in a
/// batch: token, server timestamp, and (optionally) historical_migration.
/// Called once per batch; event-level headers are merged separately.
pub fn build_context_headers(ctx: &Context) -> Vec<(String, String)> {
    let mut headers = Vec::with_capacity(3);
    headers.push(("token".into(), ctx.api_token.clone()));
    headers.push(("now".into(), ctx.server_received_at.to_rfc3339()));
    if ctx.historical_migration {
        headers.push(("historical_migration".into(), "true".into()));
    }
    headers
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::v1::test_utils;

    fn header_val(headers: &[(String, String)], key: &str) -> Option<String> {
        headers
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v.clone())
    }

    #[test]
    fn context_headers_include_token_and_now() {
        let ctx = test_utils::test_context();
        let headers = build_context_headers(&ctx);
        assert_eq!(header_val(&headers, "token"), Some(ctx.api_token.clone()));
        assert!(header_val(&headers, "now").is_some());
    }

    #[test]
    fn context_headers_include_historical_migration_when_set() {
        let mut ctx = test_utils::test_context();
        ctx.historical_migration = true;
        let headers = build_context_headers(&ctx);
        assert_eq!(
            header_val(&headers, "historical_migration"),
            Some("true".into())
        );
    }

    #[test]
    fn context_headers_omit_historical_migration_when_false() {
        let mut ctx = test_utils::test_context();
        ctx.historical_migration = false;
        let headers = build_context_headers(&ctx);
        assert!(header_val(&headers, "historical_migration").is_none());
    }
}
