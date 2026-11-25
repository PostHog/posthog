use gpui::{
    AnyElement, App, Bounds, Element, ElementId, GlobalElementId, InspectorElementId, IntoElement,
    LayoutId, Pixels, Window,
};

use super::InputGroupButton;

// Preserve this explicit part until its addon applies inherited state. Only
// immediate InputGroupButton children are inspected, never arbitrary descendants.
pub(super) struct InputGroupButtonElement {
    button: Option<InputGroupButton>,
    disabled: bool,
}

impl InputGroupButtonElement {
    pub(super) fn new(button: InputGroupButton) -> Self {
        Self {
            button: Some(button),
            disabled: false,
        }
    }

    pub(super) fn disable(&mut self, disabled: bool) {
        self.disabled |= disabled;
    }

    pub(super) fn from_element(mut element: &mut AnyElement) -> Option<&mut Self> {
        // ParentElement::child may erase an already-erased IntoElement again.
        // Unwrap only those type-erasure layers, never an element's children.
        element = unwrapped_element(element);
        element.downcast_mut::<Self>()
    }
}

pub(super) fn unwrapped_element(mut element: &mut AnyElement) -> &mut AnyElement {
    while element.downcast_mut::<AnyElement>().is_some() {
        element = element.downcast_mut::<AnyElement>().unwrap();
    }
    element
}

impl IntoElement for InputGroupButtonElement {
    type Element = Self;

    fn into_element(self) -> Self {
        self
    }
}

impl Element for InputGroupButtonElement {
    type RequestLayoutState = AnyElement;
    type PrepaintState = ();

    fn id(&self) -> Option<ElementId> {
        None
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, AnyElement) {
        let mut element = self
            .button
            .take()
            .expect("input group button already rendered")
            .render_in_group(self.disabled, window, cx);
        (element.request_layout(window, cx), element)
    }

    fn prepaint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        _: Bounds<Pixels>,
        element: &mut AnyElement,
        window: &mut Window,
        cx: &mut App,
    ) {
        element.prepaint(window, cx);
    }

    fn paint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        _: Bounds<Pixels>,
        element: &mut AnyElement,
        _: &mut (),
        window: &mut Window,
        cx: &mut App,
    ) {
        element.paint(window, cx);
    }
}
