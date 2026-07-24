//! Capability traits, lane markers, and the capability registry.
//!
//! A step declares exactly the fields it reads as trait bounds on its input — not a
//! concrete event struct. This is the "input open to extension" property: wrappers can
//! enrich an event without breaking the bounds a downstream step already relies on.
//!
//! ## The forwarding registry
//!
//! Every wrapper must forward the capabilities of its inner event. Rather than hand-
//! write `wrappers × capabilities` impls, the standard capabilities are listed **once**
//! in [`for_each_capability!`], and each wrapper forwards them all with a one-line
//! invocation ([`impl_passthrough_caps!`] and friends). Adding a capability is one
//! registry line; adding a wrapper is one invocation. See `README.md`, "The forwarding
//! problem", for the full ladder.

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
/// upstream step ([`Enrich`](crate::steps::enrich::Enrich)). Deliberately **not** part
/// of the standard registry: it is provided by one wrapper and forwarded by hand where
/// needed (a `macro_rules!` registry can't express "forward all except this one" — see
/// the forwarding-problem note in the README).
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

/// The capability registry: every standard capability, listed **exactly once** as
/// `(Trait, accessor, ReturnType)`.
///
/// Callback pattern: `for_each_capability!({ path::to::cb } (prefix))` expands to one
/// `cb!(prefix Trait, accessor, ReturnType)` per capability. (The callback is wrapped
/// in braces so a `$crate::`-qualified path can be used — a bare `path!` can't follow a
/// `:path` fragment.) Extending the vocabulary is a single line here that every
/// wrapper's forwarding picks up automatically.
#[macro_export]
macro_rules! for_each_capability {
    ({ $($cb:tt)* } ( $($prefix:tt)* )) => {
        $($cb)*!($($prefix)* $crate::events::capabilities::HasToken, token, &str);
        $($cb)*!($($prefix)* $crate::events::capabilities::HasEventName, event_name, &str);
        $($cb)*!(
            $($prefix)* $crate::events::capabilities::HasDistinctId,
            distinct_id,
            ::core::option::Option<&str>
        );
        $($cb)*!($($prefix)* $crate::events::capabilities::HasTimestamp, timestamp, i64);
        $($cb)*!($($prefix)* $crate::events::capabilities::HasTeamId, team_id, u64);
    };
}

/// Forward every standard capability through a single-type-parameter wrapper `W<In>`
/// whose inner event is in a field named `inner`. One line per wrapper.
#[macro_export]
macro_rules! impl_passthrough_caps {
    ($wrapper:ident) => {
        $crate::for_each_capability!({ $crate::forward_one_capability } (single $wrapper));
    };
}

/// Forward every standard capability through a phase-tag wrapper `Tagged<Tag, In>`.
/// One invocation covers **all** pure phase tags at once.
#[macro_export]
macro_rules! impl_passthrough_caps_tagged {
    ($wrapper:ident) => {
        $crate::for_each_capability!({ $crate::forward_one_capability } (tagged $wrapper));
    };
}

/// Forward every standard capability through a lane-carrying wrapper `Laned<In, Lane>`.
#[macro_export]
macro_rules! impl_passthrough_caps_laned {
    ($wrapper:ident) => {
        $crate::for_each_capability!({ $crate::forward_one_capability } (laned $wrapper));
    };
}
