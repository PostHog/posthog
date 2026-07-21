//! Capability traits and lane markers — the minimal-input vocabulary steps bound on.
//!
//! A step declares exactly the fields it reads as trait bounds on its input — not a
//! concrete event struct. `ApplyQuota` bounds `In: HasToken + HasEventName`; it does
//! not care what else the event carries. This is the "input open to extension"
//! property: wrappers can enrich an event (adding fields/capabilities) without breaking
//! the bounds a downstream step already relies on.
//!
//! Lanes are encoded at the *type* level ([`Main`]/[`Overflow`]/[`Historical`]), so
//! "historical never overflows" becomes a compile error: an overflow step bounds its
//! input `HasLane<Lane = Main>`, and a `Laned<_, Historical>` simply does not satisfy
//! it.

/// The event carries an ingest token.
pub trait HasToken {
    /// The ingest token.
    fn token(&self) -> &str;
}

/// The event carries an event name.
pub trait HasEventName {
    /// The event name (e.g. `$pageview`).
    fn event_name(&self) -> &str;
}

/// The event carries a distinct id (may be absent).
pub trait HasDistinctId {
    /// The distinct id, if present.
    fn distinct_id(&self) -> Option<&str>;
}

/// The event carries a timestamp (unix millis, for the POC).
pub trait HasTimestamp {
    /// The event timestamp in unix milliseconds.
    fn timestamp(&self) -> i64;
}

/// The event carries an owning team id (attribution for warnings).
pub trait HasTeamId {
    /// The owning team id.
    fn team_id(&self) -> u64;
}

/// The event carries a resolved geo country — an *enrichment* capability added by an
/// upstream step ([`Enrich`](crate::steps::enrich::Enrich)), used to demonstrate open
/// extension.
pub trait HasGeo {
    /// The resolved geo country code.
    fn geo(&self) -> &str;
}

/// The event's processing lane, encoded at the type level via the associated type.
pub trait HasLane {
    /// The lane marker ([`Main`], [`Overflow`], or [`Historical`]).
    type Lane;
}

/// Main processing lane.
pub struct Main;
/// Overflow lane (hot keys rerouted off the main lane).
pub struct Overflow;
/// Historical lane (bulk imports kept off the live path — never overflows).
pub struct Historical;
