//! Openness machinery: forwarding capability impls through wrapper types.
//!
//! The "input open to extension" property (a step bounds only the capabilities it
//! reads; wrappers extend an event without breaking downstream bounds) needs each
//! wrapper to forward the capabilities of its inner event. [`impl_passthrough_caps!`]
//! generates that forwarding.
//!
//! The macro is **domain-agnostic**: it takes the capability traits and their accessor
//! signatures as arguments, so `framework` stays decoupled from any particular event
//! vocabulary. The concrete event capabilities live in [`crate::events`], and the
//! wrappers there invoke this macro with them.

/// Forward a set of single-method capability traits through a single-type-parameter
/// wrapper whose inner event lives in a field named `inner`.
///
/// Each entry is `TraitPath: fn method(&self) -> ReturnType`. The generated impl is
/// conditional on the inner type implementing the trait, so it applies exactly when
/// the wrapped event has the capability — and never fabricates one it lacks.
///
/// ```
/// use capture_pipelines_poc::impl_passthrough_caps;
///
/// trait HasName {
///     fn name(&self) -> &str;
/// }
///
/// struct Wrapper<In> {
///     inner: In,
/// }
/// impl_passthrough_caps!(Wrapper {
///     HasName: fn name(&self) -> &str,
/// });
///
/// struct Base;
/// impl HasName for Base {
///     fn name(&self) -> &str {
///         "base"
///     }
/// }
///
/// let w = Wrapper { inner: Base };
/// assert_eq!(w.name(), "base"); // capability forwarded through the wrapper
/// ```
#[macro_export]
macro_rules! impl_passthrough_caps {
    ($wrapper:ident { $( $trait:path : fn $method:ident(&self) -> $ret:ty ),* $(,)? }) => {
        $(
            impl<In: $trait> $trait for $wrapper<In> {
                fn $method(&self) -> $ret {
                    self.inner.$method()
                }
            }
        )*
    };
}
