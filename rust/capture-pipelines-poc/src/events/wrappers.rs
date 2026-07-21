//! Phase and enrichment wrapper types, and their capability forwarding.
//!
//! Each wrapper adds state to an event as it advances through the pipeline while
//! forwarding the capabilities of its inner event via
//! [`impl_passthrough_caps!`](crate::impl_passthrough_caps) — so a step downstream of
//! the wrapper keeps compiling against the same bounds. Forwarding is *conditional*:
//! `Validated<In>` exposes [`HasGeo`] only when its `In` does, never fabricating a
//! capability the inner event lacks.

use super::capabilities::{
    HasDistinctId, HasEventName, HasGeo, HasLane, HasTeamId, HasTimestamp, HasToken, Main,
};
use crate::impl_passthrough_caps;
use std::marker::PhantomData;

/// Phase wrapper: the event passed shape validation/normalization.
#[derive(Clone)]
pub struct Validated<In> {
    /// The validated inner event.
    pub inner: In,
}

impl<In> Validated<In> {
    /// Wrap a validated event.
    pub fn new(inner: In) -> Self {
        Validated { inner }
    }
}

/// Phase wrapper: event restrictions have been applied. Carries the stamped flags a
/// later output-resolution step acts on.
pub struct Restricted<In> {
    /// The inner event.
    pub inner: In,
    /// Whether person processing should be skipped downstream.
    pub skip_person: bool,
    /// A lane the event was forced onto by restriction config, if any.
    pub forced_lane: Option<&'static str>,
}

impl<In> Restricted<In> {
    /// Wrap an event whose restrictions have been resolved.
    pub fn new(inner: In, skip_person: bool, forced_lane: Option<&'static str>) -> Self {
        Restricted {
            inner,
            skip_person,
            forced_lane,
        }
    }
}

/// Enrichment wrapper: adds a resolved geo country to an event. Demonstrates that an
/// upstream step can add a *new capability* ([`HasGeo`]) that downstream steps read,
/// without any other step changing.
pub struct WithGeo<In> {
    /// The inner event.
    pub inner: In,
    /// The resolved geo country code.
    pub geo: String,
}

impl<In> WithGeo<In> {
    /// Wrap an event with a resolved geo country.
    pub fn new(inner: In, geo: impl Into<String>) -> Self {
        WithGeo {
            inner,
            geo: geo.into(),
        }
    }
}

impl<In> HasGeo for WithGeo<In> {
    fn geo(&self) -> &str {
        &self.geo
    }
}

/// Phase wrapper carrying a *type-level* lane `L`. Restamping the lane changes the
/// type (`Laned<In, Main>` → `Laned<In, Historical>`), so lane invariants are checked
/// by the compiler.
pub struct Laned<In, L = Main> {
    /// The inner event.
    pub inner: In,
    _lane: PhantomData<L>,
}

impl<In, L> Laned<In, L> {
    /// Wrap an event onto lane `L`.
    pub fn new(inner: In) -> Self {
        Laned {
            inner,
            _lane: PhantomData,
        }
    }
}

impl<In, L> HasLane for Laned<In, L> {
    type Lane = L;
}

// Forward every capability through the single-parameter wrappers. `HasGeo` is included
// so an enriched event's geo survives further wrapping (conditional on the inner
// carrying it).
impl_passthrough_caps!(Validated {
    HasToken: fn token(&self) -> &str,
    HasEventName: fn event_name(&self) -> &str,
    HasDistinctId: fn distinct_id(&self) -> Option<&str>,
    HasTimestamp: fn timestamp(&self) -> i64,
    HasTeamId: fn team_id(&self) -> u64,
    HasGeo: fn geo(&self) -> &str,
});
impl_passthrough_caps!(Restricted {
    HasToken: fn token(&self) -> &str,
    HasEventName: fn event_name(&self) -> &str,
    HasDistinctId: fn distinct_id(&self) -> Option<&str>,
    HasTimestamp: fn timestamp(&self) -> i64,
    HasTeamId: fn team_id(&self) -> u64,
    HasGeo: fn geo(&self) -> &str,
});
// `WithGeo` provides `HasGeo` itself; it forwards the standard event capabilities.
impl_passthrough_caps!(WithGeo {
    HasToken: fn token(&self) -> &str,
    HasEventName: fn event_name(&self) -> &str,
    HasDistinctId: fn distinct_id(&self) -> Option<&str>,
    HasTimestamp: fn timestamp(&self) -> i64,
    HasTeamId: fn team_id(&self) -> u64,
});

// `Laned` carries an extra lane type parameter, so the single-parameter macro doesn't
// fit; its forwarding is written directly.
impl<In: HasToken, L> HasToken for Laned<In, L> {
    fn token(&self) -> &str {
        self.inner.token()
    }
}
impl<In: HasEventName, L> HasEventName for Laned<In, L> {
    fn event_name(&self) -> &str {
        self.inner.event_name()
    }
}
impl<In: HasDistinctId, L> HasDistinctId for Laned<In, L> {
    fn distinct_id(&self) -> Option<&str> {
        self.inner.distinct_id()
    }
}
impl<In: HasTimestamp, L> HasTimestamp for Laned<In, L> {
    fn timestamp(&self) -> i64 {
        self.inner.timestamp()
    }
}
impl<In: HasTeamId, L> HasTeamId for Laned<In, L> {
    fn team_id(&self) -> u64 {
        self.inner.team_id()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Raw {
        token: String,
        event: String,
    }
    impl HasToken for Raw {
        fn token(&self) -> &str {
            &self.token
        }
    }
    impl HasEventName for Raw {
        fn event_name(&self) -> &str {
            &self.event
        }
    }
    impl HasLane for Raw {
        type Lane = Main;
    }

    #[test]
    fn wrappers_forward_capabilities() {
        let raw = Raw {
            token: "tok".into(),
            event: "$pageview".into(),
        };
        // Bounds satisfied transitively through two wrapper layers.
        let wrapped = Restricted::new(Validated::new(raw), false, None);
        assert_eq!(wrapped.token(), "tok");
        assert_eq!(wrapped.event_name(), "$pageview");
    }

    #[test]
    fn added_capability_survives_further_wrapping() {
        let raw = Raw {
            token: "tok".into(),
            event: "$pageview".into(),
        };
        // Enrich adds HasGeo; wrapping in Validated then Restricted keeps it readable.
        let enriched = Restricted::new(Validated::new(WithGeo::new(raw, "US")), false, None);
        assert_eq!(enriched.geo(), "US");
        assert_eq!(enriched.token(), "tok"); // original caps still forwarded
    }

    // A step that only accepts main-lane input — the type-level "historical never
    // overflows" guard. `Laned<_, Historical>` would not satisfy `HasLane<Lane = Main>`.
    fn requires_main_lane<E: HasLane<Lane = Main>>(_e: &E) {}

    #[test]
    fn lane_is_a_compile_time_property() {
        let main: Laned<Raw, Main> = Laned::new(Raw {
            token: "t".into(),
            event: "e".into(),
        });
        requires_main_lane(&main);
        // requires_main_lane(&Laned::<Raw, Historical>::new(...)) would NOT compile.
    }
}
