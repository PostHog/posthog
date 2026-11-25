use gpui::{
    AnyElement, App, Axis, Div, ElementId, InteractiveElement, Interactivity, IntoElement,
    ParentElement, RenderOnce, Role, Stateful, StatefulInteractiveElement, StyleRefinement, Styled,
    Window, accesskit, div,
};
use smallvec::SmallVec;

use crate::StyledExt as _;

/// An unstyled container for a set of radio elements.
#[derive(IntoElement)]
pub struct RadioGroup {
    base: Stateful<Div>,
    style: StyleRefinement,
    axis: Axis,
    children: SmallVec<[AnyElement; 4]>,
}

impl RadioGroup {
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            base: div().id(id.into()),
            style: StyleRefinement::default(),
            axis: Axis::Vertical,
            children: SmallVec::new(),
        }
    }

    /// Sets the semantic axis of the group.
    pub fn axis(mut self, axis: Axis) -> Self {
        self.axis = axis;
        self
    }
}

impl Styled for RadioGroup {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for RadioGroup {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl InteractiveElement for RadioGroup {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }
}

impl StatefulInteractiveElement for RadioGroup {}

impl RenderOnce for RadioGroup {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.base
            .role(Role::RadioGroup)
            .aria_orientation(match self.axis {
                Axis::Horizontal => accesskit::Orientation::Horizontal,
                Axis::Vertical => accesskit::Orientation::Vertical,
            })
            .children(self.children)
            .refine_style(&self.style)
    }
}
