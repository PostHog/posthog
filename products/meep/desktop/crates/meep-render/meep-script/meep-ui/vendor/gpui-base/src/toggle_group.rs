use gpui::{
    AnyElement, App, Axis, Div, ElementId, InteractiveElement, Interactivity, IntoElement,
    ParentElement, RenderOnce, Role, Stateful, StatefulInteractiveElement, StyleRefinement, Styled,
    Window, accesskit, div,
};
use smallvec::SmallVec;

use crate::StyledExt as _;

/// An unstyled container for a set of toggle elements.
#[derive(IntoElement)]
pub struct ToggleGroup {
    base: Stateful<Div>,
    style: StyleRefinement,
    axis: Axis,
    children: SmallVec<[AnyElement; 4]>,
}

impl ToggleGroup {
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            base: div().id(id.into()),
            style: StyleRefinement::default(),
            axis: Axis::Horizontal,
            children: SmallVec::new(),
        }
    }

    /// Sets the semantic axis of the group.
    pub fn axis(mut self, axis: Axis) -> Self {
        self.axis = axis;
        self
    }
}

impl Styled for ToggleGroup {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for ToggleGroup {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl InteractiveElement for ToggleGroup {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }
}

impl StatefulInteractiveElement for ToggleGroup {}

impl RenderOnce for ToggleGroup {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.base
            .role(Role::Toolbar)
            .aria_orientation(match self.axis {
                Axis::Horizontal => accesskit::Orientation::Horizontal,
                Axis::Vertical => accesskit::Orientation::Vertical,
            })
            .children(self.children)
            .refine_style(&self.style)
    }
}
