//! The ordering guarantee a produced record preserves.
//!
//! Shared by both produce paths so they name one concept: the v0 sink's
//! `route()` and the v1 `Event::ordering` impls each decide a guarantee, and
//! each sink realizes it as a Kafka partition key. Keeping the vocabulary in
//! one place is what lets the two paths be compared case for case by the
//! cross-path overflow parity suite.

/// The ordering guarantee a route preserves, which is what the customer can
/// rely on. A sink realizes it as a Kafka partition key; the deciding layer
/// only chooses the guarantee.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrderingGuarantee {
    /// Ordering preserved per distinct id — the guarantee for every
    /// non-replay lane. Partitions on the event's canonical key
    /// ([`common_types::CapturedEvent::key`]): `token:distinct_id`, or
    /// `token:ip` in cookieless mode, where the ip stands in for the distinct
    /// id derived later in the pipeline.
    PerDistinctId,
    /// Ordering preserved per replay session: partitions on the raw
    /// `session_id`, no token prefix (a missing id is rejected by the deciding layer).
    PerSession,
    /// No guarantee — no partition key, round-robin; ordering is
    /// intentionally dropped to spread load.
    None,
}

/// Drop the guarantee when person processing is skipped, otherwise keep
/// per-distinct-id ordering.
///
/// This is the shared half of the ordering rule both paths implement: on the
/// analytics and AI main/overflow lanes, taking person processing away also
/// takes the ordering guarantee away, because the stage that disabled person
/// processing did so to spread a hot key. Lanes whose consumers need the key
/// regardless (historical, dlq, custom redirects, the AI main topic) never
/// consult this.
pub fn person_ordering(skip_person_processing: bool) -> OrderingGuarantee {
    if skip_person_processing {
        OrderingGuarantee::None
    } else {
        OrderingGuarantee::PerDistinctId
    }
}
