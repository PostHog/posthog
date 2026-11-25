use std::rc::Rc;

use gpui::{
    App, Axis, ElementId, InteractiveElement as _, IntoElement, ParentElement, RenderOnce,
    StyleRefinement, Styled, Window, div, prelude::FluentBuilder as _,
};

use crate::{AxisExt, Sizable, Size, StyledExt as _, stepper::StepperItem};

/// A step-by-step progress for users to navigate through a series of steps or stages.
#[derive(IntoElement)]
pub struct Stepper {
    id: ElementId,
    style: StyleRefinement,
    items: Vec<StepperItem>,
    step: usize,
    layout: Axis,
    disabled: bool,
    size: Size,
    text_center: bool,
    on_click: Rc<dyn Fn(&usize, &mut Window, &mut App) + 'static>,
}

impl Stepper {
    /// Creates a new stepper with the given ID.
    ///
    /// Default use is horizontal layout with step 0 selected.
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            style: StyleRefinement::default(),
            items: Vec::new(),
            step: 0,
            layout: Axis::Horizontal,
            disabled: false,
            size: Size::default(),
            text_center: false,
            on_click: Rc::new(|_, _, _| {}),
        }
    }

    /// Set whether to center the text within each stepper item.
    pub fn text_center(mut self, center: bool) -> Self {
        self.text_center = center;
        self
    }

    /// Set the layout of the stepper, default is horizontal.
    pub fn layout(mut self, layout: Axis) -> Self {
        self.layout = layout;
        self
    }

    /// Sets the layout of the stepper to Vertical.
    pub fn vertical(mut self) -> Self {
        self.layout = Axis::Vertical;
        self
    }

    /// Sets the selected index of the stepper, default is 0.
    pub fn selected_index(mut self, index: usize) -> Self {
        self.step = index;
        self
    }

    /// Adds a stepper item to the stepper.
    pub fn item(mut self, item: StepperItem) -> Self {
        self.items.push(item);
        self
    }

    /// Add multiple stepper items to the stepper.
    pub fn items(mut self, items: impl IntoIterator<Item = StepperItem>) -> Self {
        self.items.extend(items);
        self
    }

    /// Set the disabled state of the stepper, default is false.
    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Add an on_click handler for when a step is clicked.
    ///
    /// The first parameter is the `step` of currently clicked item.
    pub fn on_click<F>(mut self, f: F) -> Self
    where
        F: Fn(&usize, &mut Window, &mut App) + 'static,
    {
        self.on_click = Rc::new(f);
        self
    }
}

impl Sizable for Stepper {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Styled for Stepper {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Stepper {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let total_items = self.items.len();
        div()
            .id(self.id)
            .w_full()
            .when(self.layout.is_horizontal(), |this| this.h_flex())
            .when(self.layout.is_vertical(), |this| this.v_flex())
            .refine_style(&self.style)
            .children(self.items.into_iter().enumerate().map(|(step, item)| {
                let is_last = step + 1 == total_items;
                item.step(step)
                    .with_size(self.size)
                    .checked_step(self.step)
                    .layout(self.layout)
                    .text_center(self.text_center)
                    .when(self.disabled, |this| this.disabled(true))
                    .is_last(is_last)
                    .on_click({
                        let on_click = self.on_click.clone();
                        move |_, window, cx| {
                            on_click(&step, window, cx);
                        }
                    })
            }))
    }
}
