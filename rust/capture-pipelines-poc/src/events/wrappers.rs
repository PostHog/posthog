//! Phase and enrichment wrapper types, and their capability forwarding.
//!
//! Each wrapper adds state (or a type-level tag) to an event as it advances through the
//! pipeline while forwarding the capabilities of its inner event. Forwarding is one
//! line per wrapper via the registry macros (see [`crate::events::capabilities`]).
//!
//! Pure phase tags that add *no data* (e.g. "validated") all share a single generic
//! [`Tagged`] wrapper, so one forwarding site covers every tag. Wrappers that carry
//! data ([`WithGeo`], [`Restricted`]) or a type-level lane ([`Laned`]) stay concrete.

use super::capabilities::{HasGeo, HasLane, Main};
use crate::{impl_passthrough_caps, impl_passthrough_caps_laned, impl_passthrough_caps_tagged};
use std::marker::PhantomData;

/// A phase tag that carries no data — just marks that an event reached a phase. All
/// pure phase tags reuse [`Tagged`], so adding one costs zero forwarding impls.
pub struct Tagged<Tag, In> {
    /// The inner event.
    pub inner: In,
    _tag: PhantomData<Tag>,
}

impl<Tag, In: Clone> Clone for Tagged<Tag, In> {
    fn clone(&self) -> Self {
        Tagged {
            inner: self.inner.clone(),
            _tag: PhantomData,
        }
    }
}

impl<Tag, In> Tagged<Tag, In> {
    /// Tag an event with phase `Tag`.
    pub fn new(inner: In) -> Self {
        Tagged {
            inner,
            _tag: PhantomData,
        }
    }
}

/// Phase tag: the event passed shape validation/normalization.
pub struct ValidatedTag;

/// Phase wrapper alias: shape-validated. Reads the same as a bespoke wrapper in step
/// signatures, but shares [`Tagged`]'s single forwarding site.
pub type Validated<In> = Tagged<ValidatedTag, In>;

/// Phase wrapper: event restrictions have been applied. Carries the stamped flags a
/// later output-resolution step acts on, so it stays concrete.
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

// Standard-capability forwarding: one line per wrapper, driven by the registry.
impl_passthrough_caps_tagged!(Tagged); // covers Validated and any future phase tag
impl_passthrough_caps!(Restricted);
impl_passthrough_caps!(WithGeo);
impl_passthrough_caps_laned!(Laned);

// `HasGeo` is a *providing* capability (WithGeo supplies it), so it is outside the
// standard registry. A `macro_rules!` registry can't say "forward all except HasGeo",
// so the wrappers that merely pass it through forward it by hand. A production
// framework would express this as `#[derive(Passthrough)]` with `except(HasGeo)`.
impl<Tag, In: HasGeo> HasGeo for Tagged<Tag, In> {
    fn geo(&self) -> &str {
        self.inner.geo()
    }
}
impl<In: HasGeo> HasGeo for Restricted<In> {
    fn geo(&self) -> &str {
        self.inner.geo()
    }
}
impl<In: HasGeo, L> HasGeo for Laned<In, L> {
    fn geo(&self) -> &str {
        self.inner.geo()
    }
}

#[cfg(test)]
mod tests {
    use super::super::capabilities::{HasEventName, HasToken};
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
