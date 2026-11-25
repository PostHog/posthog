//! Composable form defaults. Native controls retain their editing and keyboard
//! behavior; these builders only establish a consistent visual foundation.
use super::*;
use gpui_kit::component::input::{Input, InputState, Textarea, TextareaState};

pub const MEASURE: f32 = 440.;
pub const FIELD_GAP: f32 = 6.;
pub const FIELD_SPACE: f32 = 18.;
pub const BORDER: u32 = 0xd8d8d8;
pub const INVALID: u32 = 0xa33932;

/// A single-line native editor. GPUI Input::h only applies to multiline
/// inputs; min/max height also fixes single-line geometry at the control token.
#[track_caller]
pub fn input(state: &Entity<InputState>, label: impl Into<SharedString>) -> Input {
    Input::new(state)
        .small()
        .w_full()
        .min_w_0()
        .min_h(px(CONTROL))
        .max_h(px(CONTROL))
        .flex_shrink_0()
        .px(px(10.))
        .py(px(5.))
        .text_size(px(BODY))
        .line_height(relative(1.5))
        .rounded(px(CONTROL_RADIUS))
        .border_color(rgb(crate::components::theme::get(5)))
        .aria_label(label)
}

/// Use TextareaState::rows, not auto_grow, with this bounded scrollable editor.
#[track_caller]
pub fn textarea(
    state: &Entity<TextareaState>,
    label: impl Into<SharedString>,
    height: f32,
) -> Textarea {
    Textarea::new(state)
        .small()
        .w_full()
        .min_w_0()
        .h(px(height.max(CONTROL)))
        .flex_shrink_0()
        .overflow_hidden()
        .px(px(10.))
        .py(px(8.))
        .text_size(px(BODY))
        .line_height(relative(1.5))
        .rounded(px(CONTROL_RADIUS))
        .border_color(rgb(crate::components::theme::get(5)))
        .aria_label(label)
}

#[derive(IntoElement)]
pub struct Field {
    id: ElementId,
    title: SharedString,
    control: AnyElement,
    hint: SharedString,
    error: Option<SharedString>,
    optional: bool,
    focus: Option<FocusHandle>,
}
impl Field {
    pub fn new(
        id: impl Into<ElementId>,
        title: impl Into<SharedString>,
        control: impl IntoElement,
    ) -> Self {
        Self {
            id: id.into(),
            title: title.into(),
            control: control.into_any_element(),
            hint: "".into(),
            error: None,
            optional: false,
            focus: None,
        }
    }
    pub fn hint(mut self, hint: impl Into<SharedString>) -> Self {
        self.hint = hint.into();
        self
    }
    pub fn optional(mut self) -> Self {
        self.optional = true;
        self
    }
    pub fn error(mut self, error: impl Into<SharedString>) -> Self {
        self.error = Some(error.into());
        self
    }
    /// Clicking a field label focuses its editor. The editor still owns its
    /// accessible name and tab stop; the label adds no extra keyboard stop.
    pub fn focus(mut self, focus: &FocusHandle) -> Self {
        self.focus = Some(focus.clone());
        self
    }
}
impl RenderOnce for Field {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let label_id = ElementId::NamedChild(self.id.clone().into(), "label".into());
        let error_id = ElementId::NamedChild(self.id.clone().into(), "error".into());
        column()
            .id(self.id)
            .w_full()
            .gap(px(FIELD_GAP))
            .child(
                row()
                    .gap(px(6.))
                    .child(
                        div()
                            .id(label_id)
                            .text_size(px(BODY))
                            .font_weight(FontWeight::MEDIUM)
                            .child(self.title)
                            .when_some(self.focus, |el, focus| {
                                el.cursor_text().on_click(move |_, window, cx| {
                                    cx.stop_propagation();
                                    focus.focus(window, cx);
                                })
                            }),
                    )
                    .when(self.optional, |el| {
                        el.child(caption("Optional").text_size(px(SMALL)))
                    }),
            )
            .child(div().w_full().min_w_0().child(self.control))
            .map(|el| {
                if let Some(error) = self.error {
                    el.child(
                        caption(error)
                            .id(error_id)
                            .text_color(rgb(crate::components::theme::get(8)))
                            .role(Role::Alert),
                    )
                } else if !self.hint.is_empty() {
                    el.child(caption(self.hint))
                } else {
                    el
                }
            })
    }
}

/// Constrain the whole form once, rather than sizing each individual field.
#[track_caller]
pub fn form(id: impl Into<ElementId>) -> Stateful<Div> {
    column()
        .id(id)
        .w_full()
        .max_w(px(MEASURE))
        .gap(px(FIELD_SPACE))
}

#[track_caller]
pub fn section(title: impl Into<SharedString>, description: impl Into<SharedString>) -> Div {
    let description = description.into();
    column().w_full().gap(px(FIELD_SPACE)).child(
        column()
            .gap(px(4.))
            .child(
                div()
                    .text_size(px(PANEL_TITLE))
                    .font_weight(FontWeight::SEMIBOLD)
                    .child(title.into()),
            )
            .when(!description.is_empty(), |el| el.child(caption(description))),
    )
}

/// An outlined secondary action, paired with ui::primary_button for submission.
#[track_caller]
pub fn secondary_button(id: impl Into<ElementId>, label: impl Into<SharedString>) -> Button {
    button(id, label)
        .outline()
        .border_color(rgb(crate::components::theme::get(5)))
        .px(px(12.))
}

/// Attach a native dropdown_menu to this trigger. Use a searchable Combobox
/// for long option lists; a three-way mode can use ui::tabs(...).self_start().
#[track_caller]
pub fn select_trigger(
    id: impl Into<ElementId>,
    label: impl Into<SharedString>,
    value: impl Into<SharedString>,
) -> Button {
    secondary_button(id, "")
        .w_full()
        .justify_start()
        .accessibility_label(label)
        .child(
            row()
                .w_full()
                .gap(px(8.))
                .child(div().flex_1().min_w_0().truncate().child(value.into()))
                .child(
                    Icon::new(IconName::ChevronDown)
                        .size(px(12.))
                        .text_color(rgb(crate::components::theme::color(SECONDARY))),
                ),
        )
}

/// Compact immutable metadata, rather than a disabled input or another section.
#[track_caller]
pub fn read_only(
    id: impl Into<ElementId>,
    label: impl Into<SharedString>,
    value: impl Into<SharedString>,
) -> Div {
    let id = id.into();
    let value_id = ElementId::NamedChild(id.clone().into(), "value".into());
    let label = label.into();
    let value = value.into();
    let copy = value.to_string();
    row()
        .w_full()
        .gap(px(12.))
        .child(caption(label.clone()))
        .child(div().flex_1())
        .child(
            mono(value)
                .id(value_id)
                .text_color(rgb(crate::components::theme::color(INK)))
                .min_w_0()
                .overflow_x_scroll(),
        )
        .child(super::copy_button(id, format!("Copy {label}"), copy))
}

/// Keep within the form measure. Wrapping leaves actions reachable on narrow
/// canvases; put the whole form in a scrollable page for small window heights.
#[track_caller]
pub fn actions(status: impl Into<SharedString>, controls: impl IntoElement) -> Div {
    let status = status.into();
    row()
        .w_full()
        .flex_wrap()
        .justify_between()
        .gap(px(12.))
        .mt(px(6.))
        .pt(px(16.))
        .border_t_1()
        .border_color(rgb(crate::components::theme::color(RULE)))
        .when(!status.is_empty(), |el| el.child(caption(status)))
        .child(row().flex_shrink_0().gap(px(8.)).child(controls))
}

/// A bounded editor with a scrolling body and a persistent action row.
#[track_caller]
pub fn editor(id: impl Into<ElementId>) -> Stateful<Div> {
    form(id).flex_1().min_h_0()
}
