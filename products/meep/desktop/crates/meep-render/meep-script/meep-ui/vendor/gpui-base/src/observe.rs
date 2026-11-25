//! Registers native elements without accepting a second description of their state.
use gpui::{Element, Hitbox, InteractiveElement, IntoElement, SharedString};

#[doc(hidden)]
#[cfg(feature = "test-support")]
pub type ObservedElement<E> = crate::test_support::Observed<E>;
#[doc(hidden)]
#[cfg(not(feature = "test-support"))]
pub type ObservedElement<E> = E;

/// Registers an existing element for UI queries. Its native accessibility
/// properties are read automatically; there are no test-only property setters.
///
/// Test-only values cannot override the native control:
/// ```compile_fail
/// use gpui::{div, prelude::*};
/// use gpui_base::TestSupportExt;
/// div().id("input").test_support().test_props(|props| props.value("invented"));
/// ```
pub trait TestSupportExt:
    Element<PrepaintState = Option<Hitbox>> + InteractiveElement + Sized
{
    /// With `test-support`, observes the element without adding a layout node.
    /// Otherwise returns the original element with its exact native type.
    /// Call before `track_focus` so the actual focus binding can be observed.
    /// Querying focus on a focus-capable element with a missed binding panics.
    fn test_support(self) -> ObservedElement<Self> {
        #[cfg(feature = "test-support")]
        {
            crate::test_support::Observed::new(self)
        }
        #[cfg(not(feature = "test-support"))]
        {
            self
        }
    }
}
impl<E: Element<PrepaintState = Option<Hitbox>> + InteractiveElement> TestSupportExt for E {}

#[doc(hidden)]
#[cfg(feature = "test-support")]
pub type ObservedTextElement<E> = crate::test_support::ObservedText<E>;
#[doc(hidden)]
#[cfg(not(feature = "test-support"))]
pub type ObservedTextElement<E> = E;

/// Records the text an element displays, for text queries in UI tests.
/// Text components call it with the text they render, so plain text needs
/// no element id.
pub trait TestTextExt: IntoElement + Sized {
    /// With `test-support`, records `text` each time the element paints.
    /// Otherwise returns the element it builds.
    fn test_text(self, text: impl Into<SharedString>) -> ObservedTextElement<Self::Element> {
        #[cfg(feature = "test-support")]
        {
            crate::test_support::ObservedText::new(self.into_element(), text.into(), false)
        }
        #[cfg(not(feature = "test-support"))]
        {
            let _ = text;
            self.into_element()
        }
    }

    /// Like [`Self::test_text`] for an image's alternative text, which
    /// stands in for what the element draws.
    fn test_alt_text(self, text: impl Into<SharedString>) -> ObservedTextElement<Self::Element> {
        #[cfg(feature = "test-support")]
        {
            crate::test_support::ObservedText::new(self.into_element(), text.into(), true)
        }
        #[cfg(not(feature = "test-support"))]
        {
            let _ = text;
            self.into_element()
        }
    }
}
impl<E: IntoElement> TestTextExt for E {}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::div;

    #[test]
    fn observation_preserves_identity_and_native_type_in_normal_builds() {
        let element = div().id("target").test_support().test_support();
        assert_eq!(Element::id(&element), Some("target".into()));
        #[cfg(not(feature = "test-support"))]
        let _: gpui::Stateful<gpui::Div> = element;
    }

    #[test]
    fn text_observation_keeps_builder_methods() {
        use gpui::{ParentElement as _, Styled as _};

        let element = div()
            .test_text("example")
            .id("target")
            .text_sm()
            .child("example");
        assert_eq!(Element::id(&element), Some("target".into()));
    }
}
