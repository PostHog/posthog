use gpui::{
    AnyElement, App, Div, ElementId, InteractiveElement, Interactivity, IntoElement, ParentElement,
    RenderOnce, Role, SharedString, StatefulInteractiveElement, StyleRefinement, Styled, Window,
    div, prelude::FluentBuilder as _,
};
use smallvec::SmallVec;

use crate::{StyledExt as _, TestSupportExt as _};

/// An unstyled linear progress root with controlled value accessibility.
#[derive(IntoElement)]
pub struct Progress {
    base: crate::ObservedElement<gpui::Stateful<Div>>,
    style: StyleRefinement,
    value: f32,
    indeterminate: bool,
    accessibility_label: Option<SharedString>,
    children: SmallVec<[AnyElement; 2]>,
}

impl Progress {
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            base: div().id(id).test_support(),
            style: StyleRefinement::default(),
            value: 0.,
            indeterminate: false,
            accessibility_label: None,
            children: SmallVec::new(),
        }
    }

    /// Sets the controlled percentage value, clamped to `0..=100`.
    pub fn value(mut self, value: f32) -> Self {
        self.value = value.clamp(0., 100.);
        self
    }

    pub fn indeterminate(mut self, indeterminate: bool) -> Self {
        self.indeterminate = indeterminate;
        self
    }

    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }
}

impl Styled for Progress {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for Progress {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl InteractiveElement for Progress {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }
}

impl StatefulInteractiveElement for Progress {}

impl RenderOnce for Progress {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.base
            .role(Role::ProgressIndicator)
            .when_some(self.accessibility_label, |this, label| {
                this.aria_label(label)
            })
            .aria_min_numeric_value(0.)
            .aria_max_numeric_value(100.)
            .when(!self.indeterminate, |this| {
                this.aria_numeric_value(self.value as f64)
            })
            .children(self.children)
            .refine_style(&self.style)
    }
}

macro_rules! progress_part {
    ($name:ident, $docs:literal) => {
        #[doc = $docs]
        #[derive(IntoElement)]
        pub struct $name {
            base: Div,
            style: StyleRefinement,
            children: SmallVec<[AnyElement; 1]>,
        }

        impl $name {
            pub fn new() -> Self {
                Self {
                    base: div(),
                    style: StyleRefinement::default(),
                    children: SmallVec::new(),
                }
            }
        }

        impl Styled for $name {
            fn style(&mut self) -> &mut StyleRefinement {
                &mut self.style
            }
        }

        impl ParentElement for $name {
            fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
                self.children.extend(elements);
            }
        }

        impl RenderOnce for $name {
            fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
                self.base.children(self.children).refine_style(&self.style)
            }
        }
    };
}

progress_part!(ProgressTrack, "An unstyled progress track.");
progress_part!(ProgressIndicator, "An unstyled progress indicator.");

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{Element as _, accesskit};

    #[gpui::test]
    fn clamps_and_projects_numeric_accessibility(cx: &mut gpui::TestAppContext) {
        let window = cx.add_empty_window();
        window.update(|window, cx| {
            let mut node = accesskit::Node::new(Role::ProgressIndicator);
            Progress::new("progress")
                .value(120.)
                .render(window, cx)
                .into_element()
                .write_a11y_info(&mut node);

            assert_eq!(node.numeric_value(), Some(100.));
            assert_eq!(node.min_numeric_value(), Some(0.));
            assert_eq!(node.max_numeric_value(), Some(100.));
        });
    }

    #[gpui::test]
    fn indeterminate_progress_omits_numeric_value(cx: &mut gpui::TestAppContext) {
        let window = cx.add_empty_window();
        window.update(|window, cx| {
            let mut node = accesskit::Node::new(Role::ProgressIndicator);
            Progress::new("loading")
                .value(40.)
                .indeterminate(true)
                .render(window, cx)
                .into_element()
                .write_a11y_info(&mut node);

            assert_eq!(node.numeric_value(), None);
        });
    }

    #[gpui::test]
    fn progress_projects_its_accessible_name(cx: &mut gpui::TestAppContext) {
        let window = cx.add_empty_window();
        window.update(|window, cx| {
            let mut node = accesskit::Node::new(Role::ProgressIndicator);
            Progress::new("download")
                .accessibility_label("Downloading release")
                .render(window, cx)
                .into_element()
                .write_a11y_info(&mut node);

            assert_eq!(node.label(), Some("Downloading release"));
        });
    }
}
