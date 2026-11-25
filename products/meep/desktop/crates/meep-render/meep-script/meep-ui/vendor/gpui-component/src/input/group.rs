//! A shared frame around one text control and its addons.
//!
//! The parts follow shadcn's input group: [`InputGroup`] is the frame,
//! [`InputGroupInput`] and [`InputGroupTextarea`] are the ordinary [`Input`]
//! and [`Textarea`] placed in it, [`InputGroupAddon`] holds text, icons and
//! buttons on one of its four sides, [`InputGroupButton`] is a [`Button`] with
//! compact input-group presentation and [`InputGroupText`] is muted text. The
//! caller keeps the `InputState` or `TextareaState`; the group owns only
//! composition and the frame.

use std::time::Duration;

use gpui_base::TestSupportExt as _;

use gpui::{
    AnyElement, App, ElementId, InteractiveElement, Interactivity, IntoElement, MouseButton,
    ParentElement, RenderOnce, Role, SharedString, StatefulInteractiveElement as _,
    StyleRefinement, Styled, ViewElement, Window, div, prelude::FluentBuilder as _, px, rems,
};

use crate::{
    ActiveTheme as _, Disableable, FocusableExt as _, Icon, Selectable, Sizable, Size,
    StyleSized as _, StyledExt as _,
    button::{Button, ButtonCustomVariant, ButtonVariant, ButtonVariants},
    h_flex,
    input::{Input, Textarea},
    v_flex,
};

/// A shared frame around one text control and any number of explicitly aligned addons.
///
/// The caller retains the `InputState` or `TextareaState`. The group owns only
/// composition and presentation; the control keeps every `Input` capability
/// and renders without its own frame. `input` replaces the slot.
#[derive(IntoElement)]
pub struct InputGroup {
    id: ElementId,
    style: StyleRefinement,
    control: Option<Input>,
    addons: Vec<InputGroupAddon>,
    size: Size,
    disabled: bool,
    readonly: bool,
    invalid: bool,
    focus_ring: bool,
    aria_label: Option<SharedString>,
}

impl InputGroup {
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            style: StyleRefinement::default(),
            control: None,
            addons: Vec::new(),
            size: Size::default(),
            disabled: false,
            readonly: false,
            invalid: false,
            focus_ring: true,
            aria_label: None,
        }
    }

    /// Set the single-line input or textarea, replacing the previous control.
    pub fn input(mut self, input: impl Into<InputGroupControl>) -> Self {
        self.control = Some(input.into().0);
        self
    }

    /// Append an addon. Addons on the same side retain their insertion order.
    pub fn addon(mut self, addon: InputGroupAddon) -> Self {
        self.addons.push(addon);
        self
    }

    /// Prevent editing and interaction throughout this group.
    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Prevent editing while preserving selection, copying, and addon actions.
    pub fn readonly(mut self, readonly: bool) -> Self {
        self.readonly = readonly;
        self
    }

    /// Display the caller's validation result. This does not reject text edits.
    pub fn invalid(mut self, invalid: bool) -> Self {
        self.invalid = invalid;
        self
    }

    /// Set a name for the group. Name its text control separately with `aria_label`.
    pub fn aria_label(mut self, label: impl Into<SharedString>) -> Self {
        self.aria_label = Some(label.into());
        self
    }
}

impl Sizable for InputGroup {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl crate::FocusableExt for InputGroup {
    fn focus_ring(mut self, enabled: bool) -> Self {
        self.focus_ring = enabled;
        self
    }

    fn is_focus_ring_enabled(&self) -> bool {
        self.focus_ring
    }
}

impl Styled for InputGroup {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

/// What the addons and the control need to know about the group they sit in.
#[derive(Clone, Copy, Default)]
struct GroupPresentation {
    size: Size,
    disabled: bool,
    readonly: bool,
    inline_start: bool,
    inline_end: bool,
    block_start: bool,
    block_end: bool,
}

impl RenderOnce for InputGroup {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let state = self.control.as_ref().map(|input| input.state().clone());
        let disabled = self.disabled
            || self
                .control
                .as_ref()
                .is_some_and(|input| input.is_disabled());
        let focused = !disabled
            && state
                .as_ref()
                .is_some_and(|state| state.has_selection_focus(window, cx));
        let multiline = state
            .as_ref()
            .is_some_and(|state| state.presentation(cx).is_multi_line());
        let has = |alignment| self.addons.iter().any(|addon| addon.alignment == alignment);
        let presentation = GroupPresentation {
            size: self.size,
            disabled,
            readonly: self.readonly,
            inline_start: has(InputGroupAddonAlignment::InlineStart),
            inline_end: has(InputGroupAddonAlignment::InlineEnd),
            block_start: has(InputGroupAddonAlignment::BlockStart),
            block_end: has(InputGroupAddonAlignment::BlockEnd),
        };
        let mut inline_start = Vec::new();
        let mut inline_end = Vec::new();
        let mut block_start = Vec::new();
        let mut block_end = Vec::new();
        for addon in self.addons {
            let target = match addon.alignment {
                InputGroupAddonAlignment::InlineStart => &mut inline_start,
                InputGroupAddonAlignment::InlineEnd => &mut inline_end,
                InputGroupAddonAlignment::BlockStart => &mut block_start,
                InputGroupAddonAlignment::BlockEnd => &mut block_end,
            };
            target.push(addon.render_in_group(presentation, window, cx));
        }
        let control = self
            .control
            .map(|input| render_control(input, presentation, multiline));
        let theme = cx.theme();
        let appearance = GroupAppearance::new(theme, focused, disabled, self.invalid);
        let radius = theme.radius;
        let foreground = theme.foreground;
        let show_ring = theme.focus_ring && self.focus_ring;
        let motion = theme.motion_tokens();
        let duration = motion.duration_fast;
        let easing = motion.easing_move.clone();
        // The border and background colors transition; the ring outside them
        // changes immediately, like the standalone input's. A color cannot
        // overshoot its target, so the theme curve is clamped.
        let (border, background) = window.with_id(self.id.clone(), |window| {
            let transition = || {
                let easing = easing.clone();
                gpui_base::Transition::new(duration)
                    .ease(move |progress| easing.sample(progress).clamp(0., 1.))
            };
            (
                gpui_base::transition("border-color", appearance.border, transition(), window, cx),
                gpui_base::transition(
                    "background-color",
                    appearance.background,
                    transition(),
                    window,
                    cx,
                ),
            )
        });
        v_flex()
            .id(self.id)
            .test_support()
            .role(Role::Group)
            .when_some(self.aria_label, |this, label| this.aria_label(label))
            .relative()
            .w_full()
            .min_w_0()
            .when(
                !multiline && !presentation.block_start && !presentation.block_end,
                |this| this.input_h(self.size),
            )
            .rounded(radius)
            .border_1()
            .border_color(border)
            .bg(background)
            .text_color(foreground)
            .input_text_size(self.size)
            .shadow_none()
            .when(disabled, |this| {
                // Custom addon content must not bypass the group's disabled policy.
                this.capture_any_mouse_down(|_, _, cx| cx.stop_propagation())
                    .capture_key_down(|event, _, cx| {
                        if event.keystroke.key != "tab" {
                            cx.stop_propagation();
                        }
                    })
            })
            .refine_style(&self.style)
            .when(disabled, |this| this.bg(background).opacity(0.5))
            .when(appearance.ring.is_some(), |this| this.border_color(border))
            .when_some(appearance.ring.filter(|_| show_ring), |this, ring| {
                crate::styled::focus_ring(this, window, ring)
            })
            .when_some(state.filter(|_| !disabled), |this, state| {
                this.on_mouse_down(MouseButton::Left, move |_, window, cx| {
                    // Native buttons prevent the default mouse-down focus action.
                    // Respect that before focusing the editor from an addon or inset.
                    if !window.default_prevented() {
                        state.focus(window, cx);
                        window.prevent_default();
                    }
                })
            })
            .children(block_start)
            .child(
                h_flex()
                    .w_full()
                    .min_w_0()
                    .items_center()
                    .when(
                        !multiline && !presentation.block_start && !presentation.block_end,
                        |this| this.h_full(),
                    )
                    .children(inline_start)
                    .children(control)
                    .children(inline_end),
            )
            .children(block_end)
    }
}

/// The control rendered without its own frame: the group draws the border,
/// background and ring. An inline addon takes over part of the control's
/// horizontal inset, as in shadcn; the caller's own style still wins.
fn render_control(
    mut input: Input,
    presentation: GroupPresentation,
    multiline: bool,
) -> AnyElement {
    let style = std::mem::take(input.style());
    input
        .with_size(presentation.size)
        .appearance(false)
        .focus_bordered(false)
        .disabled(presentation.disabled)
        .readonly(presentation.readonly)
        .flex_1()
        .min_w_0()
        .when(multiline, |this| this.min_h_16())
        .when(!multiline, |this| {
            this.when(presentation.inline_start, |this| this.pl_2())
                .when(presentation.inline_end, |this| this.pr_2())
        })
        .refine_style(&style)
        .into_any_element()
}

struct GroupAppearance {
    background: gpui::Hsla,
    border: gpui::Hsla,
    ring: Option<gpui::Hsla>,
}

impl GroupAppearance {
    fn new(theme: &crate::Theme, focused: bool, disabled: bool, invalid: bool) -> Self {
        let background = if disabled {
            theme.input.opacity(if theme.is_dark() { 0.8 } else { 0.5 })
        } else if theme.is_dark() {
            theme.input.opacity(0.3)
        } else {
            theme.transparent
        };
        // Validation remains visible when editing is disabled. Focus alone never
        // reactivates a disabled control, and never replaces its validation color.
        let (border, ring) = if invalid {
            (
                theme.danger,
                Some(
                    theme
                        .danger
                        .opacity(if theme.is_dark() { 0.4 } else { 0.2 }),
                ),
            )
        } else if focused && !disabled {
            (theme.ring, Some(theme.ring.opacity(0.5)))
        } else {
            (theme.input, None)
        };
        Self {
            background,
            border,
            ring,
        }
    }
}

/// The logical side of an addon relative to the text control.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum InputGroupAddonAlignment {
    #[default]
    InlineStart,
    InlineEnd,
    BlockStart,
    BlockEnd,
}

/// Text, icons, buttons, or custom content on one side of an input group.
///
/// Children retain their insertion order. Direct `InputGroupButton` children
/// inherit the group's disabled state. Custom children retain their own semantics.
#[derive(IntoElement)]
pub struct InputGroupAddon {
    id: ElementId,
    alignment: InputGroupAddonAlignment,
    style: StyleRefinement,
    children: Vec<AnyElement>,
}

impl InputGroupAddon {
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            alignment: InputGroupAddonAlignment::default(),
            style: StyleRefinement::default(),
            children: Vec::new(),
        }
    }

    pub fn align(mut self, alignment: InputGroupAddonAlignment) -> Self {
        self.alignment = alignment;
        self
    }

    fn render_in_group(
        mut self,
        presentation: GroupPresentation,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        for child in &mut self.children {
            if let Some(button) = button_element::InputGroupButtonElement::from_element(child) {
                button.disable(presentation.disabled);
            }
        }
        let border_top = self
            .style
            .border_widths
            .top
            .is_some_and(|width| width.to_pixels(window.rem_size()) > px(0.));
        let border_bottom = self
            .style
            .border_widths
            .bottom
            .is_some_and(|width| width.to_pixels(window.rem_size()) > px(0.));
        // An inline addon keeps the same clearance from the frame's edge that
        // a compact button has from its top and bottom; block addons share the
        // control's horizontal inset so a leading icon or a trailing button
        // lines up with the text.
        let block_px = presentation.size.input_px();
        h_flex()
            .id(self.id)
            .test_support()
            .flex_none()
            .gap_2()
            .py_1p5()
            .when(
                matches!(presentation.size, Size::XSmall | Size::Small),
                |this| this.py_0(),
            )
            .justify_center()
            .font_medium()
            .input_text_size(presentation.size)
            .text_color(cx.theme().muted_foreground)
            .cursor_text()
            .map(|this| match self.alignment {
                InputGroupAddonAlignment::InlineStart => this.pl_1p5(),
                InputGroupAddonAlignment::InlineEnd => this.pr_1p5(),
                InputGroupAddonAlignment::BlockStart => this
                    .w_full()
                    .justify_start()
                    .px(block_px)
                    .pt_2()
                    .when(border_bottom, |this| this.pb_2()),
                InputGroupAddonAlignment::BlockEnd => this
                    .w_full()
                    .justify_start()
                    .px(block_px)
                    .pb_2()
                    .when(border_top, |this| this.pt_2()),
            })
            .refine_style(&self.style)
            .children(self.children.into_iter().map(addon_child))
            .into_any_element()
    }
}

impl ParentElement for InputGroupAddon {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for InputGroupAddon {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for InputGroupAddon {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        self.render_in_group(GroupPresentation::default(), window, cx)
    }
}

/// The single-line control of a group: an [`Input`] placed in the frame, with
/// every `Input` capability.
pub type InputGroupInput = Input;

/// The multi-line control of a group: a [`Textarea`] placed in the frame,
/// with every `Textarea` capability.
pub type InputGroupTextarea = Textarea;

/// A single-line input or textarea accepted by [`InputGroup::input`].
pub struct InputGroupControl(Input);

impl From<Input> for InputGroupControl {
    fn from(input: Input) -> Self {
        Self(input)
    }
}

impl From<Textarea> for InputGroupControl {
    fn from(textarea: Textarea) -> Self {
        Self(textarea.into_input())
    }
}

/// A [`Button`] with compact input-group presentation and disabled inheritance.
///
/// Ghost and extra-small by default, as in shadcn; `xsmall` and `small` are
/// the two compact sizes, and a button with only an icon is square at either.
pub struct InputGroupButton {
    button: Button,
    size: Size,
    style: StyleRefinement,
}

impl InputGroupButton {
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            button: Button::new(id).ghost(),
            size: Size::XSmall,
            style: StyleRefinement::default(),
        }
    }

    pub fn label(mut self, label: impl Into<SharedString>) -> Self {
        self.button = self.button.label(label);
        self
    }

    pub fn icon(mut self, icon: impl Into<Icon>) -> Self {
        self.button = self.button.icon(icon.into());
        self
    }

    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.button = self.button.accessibility_label(label);
        self
    }

    pub fn tooltip(mut self, tooltip: impl Into<SharedString>) -> Self {
        self.button = self.button.tooltip(tooltip);
        self
    }

    pub fn tooltip_show_delay(mut self, delay: Duration) -> Self {
        self.button = self.button.tooltip_show_delay(delay);
        self
    }

    pub fn loading(mut self, loading: bool) -> Self {
        self.button = self.button.loading(loading);
        self
    }

    pub fn loading_icon(mut self, icon: impl Into<Icon>) -> Self {
        self.button = self.button.loading_icon(icon);
        self
    }

    pub fn outline(mut self) -> Self {
        self.button = self.button.outline();
        self
    }

    pub fn tab_index(mut self, tab_index: isize) -> Self {
        self.button = self.button.tab_index(tab_index);
        self
    }

    pub fn dropdown_caret(mut self, dropdown_caret: bool) -> Self {
        self.button = self.button.dropdown_caret(dropdown_caret);
        self
    }

    pub fn on_click(
        mut self,
        handler: impl Fn(&gpui::ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.button = self.button.on_click(handler);
        self
    }

    fn render_in_group(self, disabled: bool, window: &mut Window, cx: &mut App) -> AnyElement {
        let disabled = disabled || self.button.is_disabled();
        let selected = self.button.is_selected();
        let icon_only = self.button.is_icon_only();
        let ghost =
            matches!(self.button.variant(), ButtonVariant::Ghost) && !self.button.is_outline();
        let muted = cx.theme().muted;
        let hover = muted.opacity(if cx.theme().is_dark() { 0.5 } else { 1. });
        let compact = matches!(self.size, Size::XSmall | Size::Small);
        let icon_size = match self.size {
            Size::XSmall => Size::Small,
            Size::Small => Size::Medium,
            size => size,
        };
        let content_style = div()
            .text_sm()
            .line_height(rems(1.25))
            .map(|this| match self.size {
                Size::XSmall => this.gap_1(),
                _ => this.gap_1p5(),
            })
            .style()
            .clone();
        self.button
            .when(disabled, |this| this.disabled(true))
            .map(|this| {
                if compact {
                    this.with_size(Size::Medium)
                        .content_style(content_style, icon_size)
                } else {
                    this.with_size(self.size)
                }
            })
            .when(ghost, |this| {
                this.custom(
                    ButtonCustomVariant::new(cx)
                        .color(cx.theme().transparent)
                        .foreground(cx.theme().foreground)
                        .hover(hover)
                        .active(if selected { muted } else { hover }),
                )
                .text_color(cx.theme().foreground)
                .when(disabled, |this| this.opacity(0.5))
            })
            .when(disabled, |this| this.focus_ring(false))
            .text_sm()
            .font_medium()
            .border_1()
            .shadow_none()
            .map(|this| match (self.size, icon_only) {
                (Size::XSmall, false) => this.h_6().px_2().rounded(cx.theme().radius_tokens().sm),
                (Size::XSmall, true) => this.size_6().p_0().rounded(cx.theme().radius_tokens().sm),
                (Size::Small, false) => this.h_8().px_2p5().rounded(cx.theme().radius),
                (Size::Small, true) => this.size_8().p_0().rounded(cx.theme().radius),
                _ => this,
            })
            .refine_style(&self.style)
            .render(window, cx)
            .into_any_element()
    }
}

impl Sizable for InputGroupButton {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl ButtonVariants for InputGroupButton {
    fn with_variant(mut self, variant: ButtonVariant) -> Self {
        self.button = self.button.with_variant(variant);
        self
    }
}

impl Disableable for InputGroupButton {
    fn disabled(mut self, disabled: bool) -> Self {
        self.button = self.button.disabled(disabled);
        self
    }
}

impl Selectable for InputGroupButton {
    fn selected(mut self, selected: bool) -> Self {
        self.button = self.button.selected(selected);
        self
    }

    fn is_selected(&self) -> bool {
        self.button.is_selected()
    }
}

impl InteractiveElement for InputGroupButton {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.button.interactivity()
    }
}

impl crate::menu::DropdownMenu for InputGroupButton {}

impl IntoElement for InputGroupButton {
    type Element = AnyElement;

    fn into_element(self) -> Self::Element {
        button_element::InputGroupButtonElement::new(self).into_any_element()
    }

    fn into_any_element(self) -> AnyElement {
        self.into_element()
    }
}

impl Styled for InputGroupButton {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for InputGroupButton {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.button.extend(elements);
    }
}

impl RenderOnce for InputGroupButton {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        self.render_in_group(false, window, cx)
    }
}

/// Muted helper text, optionally combined with icons, inside an input group.
#[derive(IntoElement, Default)]
pub struct InputGroupText {
    style: StyleRefinement,
    children: Vec<AnyElement>,
}

impl InputGroupText {
    pub fn new() -> Self {
        Self::default()
    }
}

impl ParentElement for InputGroupText {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for InputGroupText {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for InputGroupText {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        h_flex()
            .gap_2()
            .text_sm()
            .text_color(cx.theme().muted_foreground)
            .refine_style(&self.style)
            .children(self.children.into_iter().map(addon_child))
    }
}

fn addon_child(mut child: AnyElement) -> AnyElement {
    if button_element::unwrapped_element(&mut child)
        .downcast_mut::<ViewElement<Icon>>()
        .is_some()
    {
        // An icon without an explicit size follows the addon's one-rem
        // default; an explicit size stays with the icon.
        div()
            .flex_none()
            .text_base()
            .child(child)
            .into_any_element()
    } else {
        child
    }
}

#[cfg(test)]
mod tests;

mod button_element;
