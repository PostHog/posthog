//! Capability traits: minimal-input bounds, phase wrappers, and lane markers.
//!
//! A step declares exactly the fields it reads as trait bounds on its input — not a
//! concrete event struct. `ApplyQuota` bounds `In: HasToken + HasEventName`; it does
//! not care what else the event carries. This is the "input open to extension"
//! property: wrappers can enrich an event (adding fields) without breaking the bounds
//! a downstream step already relies on.
//!
//! Phase progression is modeled with wrapper types ([`Validated`], [`Restricted`],
//! [`Laned`]). Each wrapper forwards the capabilities of its inner type — but hand-
//! writing that forwarding for every wrapper × every capability is exactly the
//! boilerplate [`impl_passthrough_caps!`] eliminates.
//!
//! Lanes are encoded at the *type* level ([`Main`]/[`Overflow`]/[`Historical`]), so
//! "historical never overflows" becomes a compile error: an overflow step bounds its
//! input `HasLane<Lane = Main>`, and a `Laned<_, Historical>` simply does not satisfy
//! it.

use std::marker::PhantomData;

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

/// Forward the value-capability traits ([`HasToken`], [`HasEventName`],
/// [`HasDistinctId`], [`HasTimestamp`]) through a single-type-parameter wrapper whose
/// inner event lives in a field named `inner`.
///
/// This is the "wrappers extend without breaking downstream bounds" property, made
/// mechanical: one macro invocation per wrapper instead of four hand-written impls.
///
/// ```
/// use capture_pipelines_poc::capability::{HasToken, HasEventName, HasDistinctId, HasTimestamp};
/// use capture_pipelines_poc::impl_passthrough_caps;
///
/// struct MyWrapper<In> { inner: In }
/// impl_passthrough_caps!(MyWrapper);
/// ```
#[macro_export]
macro_rules! impl_passthrough_caps {
    ($wrapper:ident) => {
        impl<In: $crate::capability::HasToken> $crate::capability::HasToken for $wrapper<In> {
            fn token(&self) -> &str {
                self.inner.token()
            }
        }
        impl<In: $crate::capability::HasEventName> $crate::capability::HasEventName
            for $wrapper<In>
        {
            fn event_name(&self) -> &str {
                self.inner.event_name()
            }
        }
        impl<In: $crate::capability::HasDistinctId> $crate::capability::HasDistinctId
            for $wrapper<In>
        {
            fn distinct_id(&self) -> Option<&str> {
                self.inner.distinct_id()
            }
        }
        impl<In: $crate::capability::HasTimestamp> $crate::capability::HasTimestamp
            for $wrapper<In>
        {
            fn timestamp(&self) -> i64 {
                self.inner.timestamp()
            }
        }
    };
}

impl_passthrough_caps!(Validated);
impl_passthrough_caps!(Restricted);

// `Laned` carries an extra lane type parameter, so its value-capability forwarding is
// written directly rather than through the single-parameter macro.
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
