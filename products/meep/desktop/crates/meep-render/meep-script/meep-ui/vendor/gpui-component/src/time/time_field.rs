use std::sync::Arc;

use gpui::{
    App, ElementId, Entity, Focusable as _, FontFeatures, IntoElement, ParentElement as _,
    RenderOnce, StyleRefinement, Styled, Window, div, prelude::FluentBuilder as _,
};

use crate::{
    ActiveTheme as _, Disableable, Sizable, Size, StyleSized as _, StyledExt as _,
    ThemeStyled as _, input::input_style,
};

use gpui_base::TimeField as BaseTimeField;
pub use gpui_base::{HourCycle, TimeFieldEvent, TimeFieldState, TimePrecision, TimeSegment};

/// Digits of equal width (OpenType `tnum`), so a value that changes while it
/// is edited keeps its width instead of shifting with each digit.
pub(crate) fn tabular_figures() -> FontFeatures {
    FontFeatures(Arc::new(vec![("tnum".into(), 1)]))
}

/// Both period labels stacked in one grid cell, the inactive one transparent,
/// so the segment is as wide as the wider label whichever is shown.
fn period_label(pm: bool) -> impl IntoElement {
    let label = |text: &'static str, active: bool| {
        div()
            .col_start(1)
            .row_start(1)
            .when(!active, |this| this.text_color(gpui::transparent_black()))
            .child(text)
    };
    div()
        .grid()
        .grid_cols(1)
        .child(label("AM", !pm))
        .child(label("PM", pm))
}

/// A segmented time editor, e.g. `09:30`, `09:30:15` or `09:30 PM`.
///
/// The value lives in [`TimeFieldState`]; see it for the keyboard model.
#[derive(IntoElement)]
pub struct TimeField {
    id: ElementId,
    state: Entity<TimeFieldState>,
    size: Size,
    style: StyleRefinement,
    disabled: bool,
    invalid: bool,
}

impl TimeField {
    pub fn new(state: &Entity<TimeFieldState>) -> Self {
        Self {
            id: ("time-field", state.entity_id()).into(),
            state: state.clone(),
            size: Size::default(),
            style: StyleRefinement::default(),
            disabled: false,
            invalid: false,
        }
    }

    pub(crate) fn with_id(mut self, id: impl Into<ElementId>) -> Self {
        self.id = id.into();
        self
    }

    /// Display the caller's validation result. This does not reject edits.
    pub fn invalid(mut self, invalid: bool) -> Self {
        self.invalid = invalid;
        self
    }
}

impl Sizable for TimeField {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Disableable for TimeField {
    fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }
}

impl Styled for TimeField {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for TimeField {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let focused = self.state.read(cx).focus_handle(cx).is_focused(window);
        let (bg, fg) = input_style(self.disabled, cx);
        let segment_radius = cx.theme().radius / 2.;

        div()
            .flex()
            .items_center()
            .flex_none()
            .font_features(tabular_figures())
            .bg(bg)
            .text_color(fg)
            .border_1()
            .border_color(cx.theme().input)
            .rounded(cx.theme().radius)
            .input_text_size(self.size)
            .input_h(self.size)
            .when(self.disabled, |this| this.opacity(0.5))
            .when(focused && !self.disabled, |this| {
                this.focus_ring_style(window, cx)
            })
            .when(self.invalid, |this| this.border_color(cx.theme().danger))
            .child(
                BaseTimeField::new(self.id, &self.state)
                    .disabled(self.disabled)
                    // The base field fills the frame, so a press anywhere inside it lands on the
                    // field rather than on the frame around it.
                    .flex()
                    .size_full()
                    .px_1()
                    .items_center()
                    .render_segment(move |segment, state, _, cx| {
                        segment
                            .px_0p5()
                            .when(state.segment() == TimeSegment::Period, |this| {
                                this.ml_1()
                                    .clear_children()
                                    .child(period_label(state.value() == 1))
                            })
                            .rounded(segment_radius)
                            .when(state.is_selected(), |this| this.bg(cx.theme().selection))
                            .into_any_element()
                    }),
            )
            .refine_style(&self.style)
    }
}

#[cfg(test)]
mod tests {
    use gpui::{AppContext as _, px};

    use super::*;

    #[gpui::test]
    fn test_time_field_builder(cx: &mut gpui::TestAppContext) {
        let window = cx.add_empty_window();
        let state = window.update(|window, cx| {
            cx.new(|cx| {
                TimeFieldState::new(window, cx)
                    .precision(TimePrecision::Second)
                    .hour_cycle(HourCycle::H12)
            })
        });
        let field = TimeField::new(&state)
            .with_id("start")
            .large()
            .disabled(true)
            .invalid(true)
            .w(px(120.));

        assert_eq!(field.id, "start".into());
        assert_eq!(field.size, Size::Large);
        assert!(field.disabled);
        assert!(field.invalid);
    }

    #[cfg(feature = "test-support")]
    struct FieldHarness {
        state: Entity<TimeFieldState>,
    }

    #[cfg(feature = "test-support")]
    impl gpui::Render for FieldHarness {
        fn render(&mut self, _: &mut Window, _: &mut gpui::Context<Self>) -> impl IntoElement {
            div().child(TimeField::new(&self.state).with_id("time").w(px(200.)))
        }
    }

    #[cfg(feature = "test-support")]
    fn click_at(cx: &mut gpui::VisualTestContext, position: gpui::Point<gpui::Pixels>) {
        cx.simulate_click(position, gpui::Modifiers::default());
        cx.update(|window, cx| window.draw(cx).clear(cx));
    }

    #[cfg(feature = "test-support")]
    #[gpui::test]
    fn pressing_outside_the_segments_focuses_the_first_segment(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        let (view, cx) = cx.add_window_view(|window, cx| FieldHarness {
            state: cx.new(|cx| TimeFieldState::new(window, cx)),
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let state = cx.update(|_, cx| view.read(cx).state.clone());
        let segment = |cx: &mut gpui::VisualTestContext, id: &'static str| {
            cx.update(|window, _| {
                gpui_base::test_support::find(window, &[], &ElementId::from(id))
                    .expect("segment is painted")
                    .bounds()
                    .center()
            })
        };
        let blank = gpui::point(px(180.), segment(cx, "hour").y);

        click_at(cx, blank);
        cx.update(|window, cx| {
            assert!(state.read(cx).focus_handle(cx).is_focused(window));
        });
        assert_eq!(
            cx.update(|_, cx| state.read(cx).selected_segment()),
            TimeSegment::Hour
        );

        // A press on a segment still selects that segment, not the first one.
        let minute = segment(cx, "minute");
        click_at(cx, minute);
        assert_eq!(
            cx.update(|_, cx| state.read(cx).selected_segment()),
            TimeSegment::Minute
        );

        click_at(cx, blank);
        assert_eq!(
            cx.update(|_, cx| state.read(cx).selected_segment()),
            TimeSegment::Hour
        );
    }
}
