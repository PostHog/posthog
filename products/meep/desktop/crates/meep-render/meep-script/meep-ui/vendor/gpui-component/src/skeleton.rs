use crate::{ActiveTheme, StyledExt};
use gpui::{
    Animation, AnimationExt, IntoElement, RenderOnce, StyleRefinement, Styled, bounce, div,
    ease_in_out,
};
use instant::Duration;

/// A skeleton loading placeholder element.
#[derive(IntoElement)]
pub struct Skeleton {
    style: StyleRefinement,
    secondary: bool,
}

impl Skeleton {
    /// Create a new Skeleton element.
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            secondary: false,
        }
    }

    /// Set use secondary color.
    pub fn secondary(mut self) -> Self {
        self.secondary = true;
        self
    }
}

impl Styled for Skeleton {
    fn style(&mut self) -> &mut gpui::StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Skeleton {
    fn render(self, _: &mut gpui::Window, cx: &mut gpui::App) -> impl IntoElement {
        div()
            .w_full()
            .h_4()
            .bg(if self.secondary {
                cx.theme().skeleton.opacity(0.5).into()
            } else {
                cx.theme().skeleton
            })
            .refine_style(&self.style)
            .with_animation(
                "skeleton",
                Animation::new(Duration::from_secs(2))
                    .repeat()
                    .with_easing(bounce(ease_in_out)),
                move |this, delta| {
                    let v = 1.0 - delta * 0.5;
                    this.opacity(v)
                },
            )
    }
}
