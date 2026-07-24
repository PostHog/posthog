//! Openness machinery: forwarding one capability impl through a wrapper type.
//!
//! This is the domain-agnostic half of the "input open to extension" property. It
//! emits a *single* capability-forwarding impl given the wrapper's generic shape, the
//! trait, and its accessor signature — it names no domain traits itself (those are
//! supplied by the capability registry in [`crate::events::capabilities`], which drives
//! this via a callback). The wrapper's inner event must live in a field named `inner`.
//!
//! Three shapes cover the demo wrappers:
//! - `single` — `W<In>` (a wrapper with one type parameter, e.g. `WithGeo`, `Restricted`).
//! - `tagged` — `Tagged<Tag, In>` (one forwarding site covers every pure phase tag).
//! - `laned` — `Laned<In, Lane>` (a wrapper carrying a type-level lane).
//!
//! In a production framework this whole file collapses into a `#[derive(Passthrough)]`
//! proc-macro; `macro_rules!` is the POC stand-in.

/// Emit one capability-forwarding impl. Selected by a leading shape keyword; the trait,
/// accessor name, and return type come from the registry callback.
#[doc(hidden)]
#[macro_export]
macro_rules! forward_one_capability {
    (single $wrapper:ident $trait:path, $method:ident, $ret:ty) => {
        impl<In: $trait> $trait for $wrapper<In> {
            fn $method(&self) -> $ret {
                self.inner.$method()
            }
        }
    };
    (tagged $wrapper:ident $trait:path, $method:ident, $ret:ty) => {
        impl<Tag, In: $trait> $trait for $wrapper<Tag, In> {
            fn $method(&self) -> $ret {
                self.inner.$method()
            }
        }
    };
    (laned $wrapper:ident $trait:path, $method:ident, $ret:ty) => {
        impl<In: $trait, Lane> $trait for $wrapper<In, Lane> {
            fn $method(&self) -> $ret {
                self.inner.$method()
            }
        }
    };
}
