use crate::input::InputState;
use std::rc::Rc;

use gpui::{
    AnyElement, App, AppContext as _, ClickEvent, Context, Div, ElementId, Entity, EventEmitter,
    FocusHandle, Focusable, Hsla, InteractiveElement, Interactivity, IntoElement, KeyBinding,
    ParentElement, Render, RenderOnce, Rgba, Role, SharedString, Stateful,
    StatefulInteractiveElement, StyleRefinement, Styled, Subscription, Toggled, Window, div, hsla,
    prelude::FluentBuilder as _,
};
use smallvec::SmallVec;

use crate::{
    RoleOverride, StyledExt as _,
    actions::{Cancel, Confirm},
    input::InputEvent,
    slider::{SliderEvent, SliderState},
};

const CONTEXT: &str = "ColorPicker";

/// The hex values this picker's text field accepts while being typed.
const HEX_PATTERN: &str = r"^#[0-9a-fA-F]{0,8}$";

pub(crate) fn init(cx: &mut App) {
    cx.bind_keys([
        KeyBinding::new("enter", Confirm { secondary: false }, Some(CONTEXT)),
        KeyBinding::new("escape", Cancel, Some(CONTEXT)),
    ]);
}

/// Parses `#rgb`, `#rgba`, `#rrggbb`, and `#rrggbbaa`, with or without the `#`.
fn parse_hex(value: &str) -> Option<Hsla> {
    let value = value.strip_prefix('#').unwrap_or(value);
    // `from_str_radix` accepts a leading sign, so reject anything that is not
    // purely hexadecimal before slicing components out of it.
    if !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return None;
    }

    let (width, has_alpha) = match value.len() {
        3 => (1, false),
        4 => (1, true),
        6 => (2, false),
        8 => (2, true),
        _ => return None,
    };

    let component = |index: usize| {
        let start = index * width;
        let raw = u8::from_str_radix(&value[start..start + width], 16).ok()?;
        // A single digit repeats itself rather than scaling, so `#fff` is white.
        let raw = if width == 1 { raw * 0x11 } else { raw };
        Some(raw as f32 / 255.0)
    };

    Some(
        Rgba {
            r: component(0)?,
            g: component(1)?,
            b: component(2)?,
            a: if has_alpha { component(3)? } else { 1.0 },
        }
        .into(),
    )
}

/// Formats a color as `#RRGGBB`, or `#RRGGBBAA` when it is translucent.
fn hex_string(color: Hsla) -> String {
    let rgba = Rgba::from(color);
    let channel = |value: f32| (value.clamp(0., 1.) * 255.).round() as u8;
    if rgba.a < 1. {
        format!(
            "#{:02X}{:02X}{:02X}{:02X}",
            channel(rgba.r),
            channel(rgba.g),
            channel(rgba.b),
            channel(rgba.a)
        )
    } else {
        format!(
            "#{:02X}{:02X}{:02X}",
            channel(rgba.r),
            channel(rgba.g),
            channel(rgba.b)
        )
    }
}

/// Events emitted by a [`ColorPickerState`].
#[derive(Clone)]
pub enum ColorPickerEvent {
    /// The committed color changed.
    Change(Option<Hsla>),
}

/// The four component sliders owned by a [`ColorPickerState`].
///
/// Applications render these with their own slider presentation; the picker
/// keeps them in sync with the committed color.
#[derive(Clone)]
pub struct HslaSliders {
    hue: Entity<SliderState>,
    saturation: Entity<SliderState>,
    lightness: Entity<SliderState>,
    alpha: Entity<SliderState>,
}

impl HslaSliders {
    fn new(cx: &mut App) -> Self {
        let component = |cx: &mut App| {
            cx.new(|_| {
                SliderState::new()
                    .min(0.)
                    .max(1.)
                    .step(0.01)
                    .default_value(0.)
            })
        };

        Self {
            hue: component(cx),
            saturation: component(cx),
            lightness: component(cx),
            alpha: component(cx),
        }
    }

    /// The hue slider, in `0..=1`.
    pub fn hue(&self) -> &Entity<SliderState> {
        &self.hue
    }

    /// The saturation slider, in `0..=1`.
    pub fn saturation(&self) -> &Entity<SliderState> {
        &self.saturation
    }

    /// The lightness slider, in `0..=1`.
    pub fn lightness(&self) -> &Entity<SliderState> {
        &self.lightness
    }

    /// The alpha slider, in `0..=1`.
    pub fn alpha(&self) -> &Entity<SliderState> {
        &self.alpha
    }

    fn read(&self, cx: &App) -> Hsla {
        hsla(
            self.hue.read(cx).value().start(),
            self.saturation.read(cx).value().start(),
            self.lightness.read(cx).value().start(),
            self.alpha.read(cx).value().start(),
        )
    }

    fn write(&self, color: Hsla, window: &mut Window, cx: &mut App) {
        let components = [
            (&self.hue, color.h),
            (&self.saturation, color.s),
            (&self.lightness, color.l),
            (&self.alpha, color.a),
        ];
        for (slider, value) in components {
            slider.update(cx, |slider, cx| slider.set_value(value, window, cx));
        }
    }
}

/// State and interaction model for a color picker.
///
/// This owns the committed color, the transient preview shown while the user
/// hovers or edits, the controlled open state, the active panel, and the hex
/// field and component sliders that stay in sync with all of them. The
/// application owns the palette, popup, layout, and every visual decision.
pub struct ColorPickerState {
    focus_handle: FocusHandle,
    value: Option<Hsla>,
    preview: Option<Hsla>,
    open: bool,
    active_tab: usize,
    hex_input: Entity<InputState>,
    sliders: HslaSliders,
    /// A builder-supplied value cannot reach the sliders without a `Window`,
    /// so the first render flushes it through [`Self::sync_pending_value`].
    needs_slider_sync: bool,
    _subscriptions: Vec<Subscription>,
}

impl ColorPickerState {
    /// Creates an empty, closed picker.
    pub fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        let hex_input = cx
            .new(|cx| InputState::new(window, cx).pattern(regex::Regex::new(HEX_PATTERN).unwrap()));
        let sliders = HslaSliders::new(cx);

        let mut subscriptions = vec![cx.subscribe_in(
            &hex_input,
            window,
            |this, input, event: &InputEvent, window, cx| match event {
                InputEvent::Change => {
                    let value = input.read(cx).value();
                    if this.preview_hex(value.as_str(), window, cx) {
                        let color = this.preview.expect("valid hex leaves a preview");
                        this.sliders.write(color, window, cx);
                    }
                }
                InputEvent::PressEnter { .. } => {
                    let value = input.read(cx).value();
                    this.commit_hex(value.as_str(), window, cx);
                }
                _ => {}
            },
        )];

        subscriptions.extend(
            [
                sliders.hue.clone(),
                sliders.saturation.clone(),
                sliders.lightness.clone(),
                sliders.alpha.clone(),
            ]
            .iter()
            .map(|slider| {
                cx.subscribe_in(slider, window, |this, _, _: &SliderEvent, window, cx| {
                    let color = this.sliders.read(cx);
                    this.update_value_from_slider(color, window, cx);
                })
            }),
        );

        Self {
            focus_handle: cx.focus_handle(),
            value: None,
            preview: None,
            open: false,
            active_tab: 0,
            hex_input,
            sliders,
            needs_slider_sync: false,
            _subscriptions: subscriptions,
        }
    }

    /// Sets the initial committed and previewed color.
    pub fn default_value(mut self, value: impl Into<Hsla>) -> Self {
        let value = value.into();
        self.value = Some(value);
        self.preview = Some(value);
        self.needs_slider_sync = true;
        self
    }

    /// Returns the committed color.
    pub fn value(&self) -> Option<Hsla> {
        self.value
    }

    /// Returns the color currently being previewed.
    pub fn preview(&self) -> Option<Hsla> {
        self.preview
    }

    /// Returns the previewed color, falling back to the committed color.
    pub fn displayed_color(&self) -> Option<Hsla> {
        self.preview.or(self.value)
    }

    /// The hex text field. Render it with an application-owned input element.
    pub fn hex_input(&self) -> &Entity<InputState> {
        &self.hex_input
    }

    /// The HSLA component sliders.
    pub fn sliders(&self) -> &HslaSliders {
        &self.sliders
    }

    /// Replaces the committed color without emitting a change.
    pub fn set_value(
        &mut self,
        value: impl Into<Hsla>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.update_value(Some(value.into()), false, window, cx);
    }

    /// Clears the committed color without emitting a change.
    pub fn clear_value(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.update_value(None, false, window, cx);
    }

    /// Applies a value supplied to [`Self::default_value`] to the hex field and
    /// sliders. Call this from render; it is a no-op once nothing is pending.
    pub fn sync_pending_value(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.needs_slider_sync {
            self.update_value(self.value, false, window, cx);
        }
    }

    /// Updates the transient preview color and the hex field that shows it.
    pub fn preview_color(&mut self, value: Hsla, window: &mut Window, cx: &mut Context<Self>) {
        self.preview = Some(value);
        self.write_hex_input(Some(value), window, cx);
        cx.notify();
    }

    /// Drops the transient preview, restoring the committed color.
    pub fn clear_preview(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.preview == self.value {
            return;
        }
        self.preview = self.value;
        self.write_hex_input(self.value, window, cx);
        cx.notify();
    }

    /// Parses a hex color into the transient preview.
    ///
    /// Invalid or incomplete input leaves the current preview unchanged. This
    /// does not write the hex field, so it is safe to call while typing in it.
    pub fn preview_hex(&mut self, value: &str, _: &mut Window, cx: &mut Context<Self>) -> bool {
        let Some(value) = parse_hex(value) else {
            return false;
        };
        self.preview = Some(value);
        cx.notify();
        true
    }

    /// Parses and commits a hex color, closing the picker on success.
    pub fn commit_hex(
        &mut self,
        value: &str,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Option<Hsla> {
        let value = parse_hex(value)?;
        self.select_color(value, window, cx);
        Some(value)
    }

    /// Commits a color and closes the picker, as a palette selection does.
    pub fn select_color(&mut self, value: Hsla, window: &mut Window, cx: &mut Context<Self>) {
        self.open = false;
        self.update_value(Some(value), true, window, cx);
    }

    /// Commits a color without changing the open state, as a slider drag does.
    pub fn update_color(&mut self, value: Hsla, window: &mut Window, cx: &mut Context<Self>) {
        self.update_value(Some(value), true, window, cx);
    }

    /// Sets whether the picker popup is open.
    pub fn set_open(&mut self, open: bool, cx: &mut Context<Self>) {
        if self.open == open {
            return;
        }
        self.open = open;
        cx.notify();
    }

    /// Toggles the picker popup.
    pub fn toggle_open(&mut self, cx: &mut Context<Self>) {
        self.open = !self.open;
        cx.notify();
    }

    /// Returns whether the picker popup is open.
    pub fn is_open(&self) -> bool {
        self.open
    }

    /// Selects the application-defined picker panel.
    pub fn set_active_tab(&mut self, tab: usize, cx: &mut Context<Self>) {
        if self.active_tab == tab {
            return;
        }
        self.active_tab = tab;
        cx.notify();
    }

    /// Returns the selected application-defined picker panel.
    pub fn active_tab(&self) -> usize {
        self.active_tab
    }

    fn update_value(
        &mut self,
        value: Option<Hsla>,
        emit: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.needs_slider_sync = false;
        self.value = value;
        self.preview = value;
        self.write_hex_input(value, window, cx);
        // Drive the sliders from the full-precision color rather than letting
        // the hex round-trip do it.
        if let Some(value) = value {
            self.sliders.write(value, window, cx);
        }
        if emit {
            cx.emit(ColorPickerEvent::Change(value));
        }
        cx.notify();
    }

    fn update_value_from_slider(
        &mut self,
        value: Hsla,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.needs_slider_sync = false;
        self.value = Some(value);
        self.preview = Some(value);
        // Write the hex field, but leave the sliders alone: they are the source
        // of this change and rewriting them would fight the drag in progress.
        self.write_hex_input(Some(value), window, cx);
        cx.emit(ColorPickerEvent::Change(Some(value)));
        cx.notify();
    }

    /// Writes the hex field. `InputState::set_value` emits no change event,
    /// so nothing feeds back, and the next typed edit still previews.
    fn write_hex_input(&mut self, value: Option<Hsla>, window: &mut Window, cx: &mut App) {
        let text = value.map(hex_string).unwrap_or_default();
        self.hex_input
            .update(cx, |input, cx| input.set_value(text, window, cx));
    }
}

impl EventEmitter<ColorPickerEvent> for ColorPickerState {}

impl Focusable for ColorPickerState {
    fn focus_handle(&self, _: &App) -> FocusHandle {
        self.focus_handle.clone()
    }
}

impl Render for ColorPickerState {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        self.hex_input.clone()
    }
}

type OpenChangeHandler = Rc<dyn Fn(bool, &mut Window, &mut App)>;

/// An unstyled controlled color-picker root.
///
/// Applications own the trigger, palette, popup, and every visual decision.
/// This root owns focus, accessibility semantics, and the keyboard behavior
/// that opens and dismisses the picker.
#[derive(IntoElement)]
pub struct ColorPicker {
    base: Stateful<Div>,
    open: bool,
    disabled: bool,
    focus_handle: Option<FocusHandle>,
    accessibility_label: Option<SharedString>,
    style: StyleRefinement,
    children: SmallVec<[AnyElement; 2]>,
    on_open_change: Option<OpenChangeHandler>,
    key_context: &'static str,
    role: RoleOverride,
}

impl ColorPicker {
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            base: div().id(id),
            open: false,
            disabled: false,
            focus_handle: None,
            accessibility_label: None,
            style: StyleRefinement::default(),
            children: SmallVec::new(),
            on_open_change: None,
            key_context: CONTEXT,
            role: RoleOverride::Implicit,
        }
    }

    /// Sets the application-controlled open state.
    pub fn open(mut self, open: bool) -> Self {
        self.open = open;
        self
    }

    /// Prevents keyboard interaction and removes the trigger from tab traversal.
    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Supplies the focus handle for the picker trigger.
    pub fn track_focus(mut self, focus_handle: &FocusHandle) -> Self {
        self.focus_handle = Some(focus_handle.clone());
        self
    }

    /// Sets the accessible name exposed by the controlled root.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }

    /// Overrides the accessibility role. The default is [`Role::Button`].
    pub fn role(mut self, role: impl Into<RoleOverride>) -> Self {
        self.role = role.into();
        self
    }

    /// Handles requests to update the controlled open state.
    ///
    /// Confirm toggles the picker and Cancel dismisses an open one.
    pub fn on_open_change(
        mut self,
        handler: impl Fn(bool, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_open_change = Some(Rc::new(handler));
        self
    }

    #[doc(hidden)]
    pub fn key_context(mut self, key_context: &'static str) -> Self {
        self.key_context = key_context;
        self
    }
}

impl Styled for ColorPicker {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for ColorPicker {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl InteractiveElement for ColorPicker {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }
}

impl StatefulInteractiveElement for ColorPicker {}

impl RenderOnce for ColorPicker {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let open = self.open;
        let disabled = self.disabled;
        let handler = self.on_open_change;

        self.base
            .when_some(self.role.resolve(|| Role::Button), |this, role| {
                this.role(role)
            })
            .aria_expanded(open)
            .when_some(self.accessibility_label, |this, label| {
                this.aria_label(label)
            })
            .key_context(self.key_context)
            .when_some(
                self.focus_handle.filter(|_| !disabled),
                |this, focus_handle| this.track_focus(&focus_handle.tab_stop(true)),
            )
            .on_action({
                let handler = handler.clone();
                move |_: &Confirm, window, cx| {
                    if disabled {
                        cx.propagate();
                        return;
                    }
                    if let Some(handler) = handler.as_ref() {
                        handler(!open, window, cx);
                    }
                }
            })
            .on_action(move |_: &Cancel, window, cx| {
                if !open {
                    cx.propagate();
                    return;
                }
                cx.stop_propagation();
                if let Some(handler) = handler.as_ref() {
                    handler(false, window, cx);
                }
            })
            .children(self.children)
            .refine_style(&self.style)
    }
}

type SwatchClickHandler = Rc<dyn Fn(Hsla, &ClickEvent, &mut Window, &mut App)>;
type SwatchHoverHandler = Rc<dyn Fn(Hsla, bool, &mut Window, &mut App)>;

/// An unstyled selectable color in a picker's palette.
///
/// The application paints the color; this part carries the radio semantics,
/// the accessible hex name, and the hover and activation callbacks a picker
/// uses to preview and commit a color.
#[derive(IntoElement)]
pub struct ColorSwatch {
    id: ElementId,
    base: Stateful<Div>,
    color: Hsla,
    selected: bool,
    disabled: bool,
    style: StyleRefinement,
    children: SmallVec<[AnyElement; 1]>,
    accessibility_label: Option<SharedString>,
    on_click: Option<SwatchClickHandler>,
    on_hover: Option<SwatchHoverHandler>,
    tab_index: isize,
    tab_stop: bool,
    role: RoleOverride,
}

impl ColorSwatch {
    pub fn new(id: impl Into<ElementId>, color: Hsla) -> Self {
        let id = id.into();
        Self {
            base: div().id(id.clone()),
            id,
            color,
            selected: false,
            disabled: false,
            style: StyleRefinement::default(),
            children: SmallVec::new(),
            accessibility_label: None,
            on_click: None,
            on_hover: None,
            tab_index: 0,
            tab_stop: true,
            role: RoleOverride::Implicit,
        }
    }

    /// The color this swatch represents.
    pub fn color(&self) -> Hsla {
        self.color
    }

    /// Marks this swatch as the picker's current color.
    pub fn selected(mut self, selected: bool) -> Self {
        self.selected = selected;
        self
    }

    /// Sets whether pointer and keyboard activation are ignored.
    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Overrides the accessible name. The default is the color's hex value.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }

    /// Overrides the accessibility role. The default is [`Role::RadioButton`].
    pub fn role(mut self, role: impl Into<RoleOverride>) -> Self {
        self.role = role.into();
        self
    }

    /// Handles activation with the swatch's color.
    pub fn on_click(
        mut self,
        handler: impl Fn(Hsla, &ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_click = Some(Rc::new(handler));
        self
    }

    /// Handles hover enter and exit with the swatch's color.
    pub fn on_hover(
        mut self,
        handler: impl Fn(Hsla, bool, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_hover = Some(Rc::new(handler));
        self
    }

    /// Sets the focus traversal index. The default is `0`.
    pub fn tab_index(mut self, tab_index: isize) -> Self {
        self.tab_index = tab_index;
        self
    }

    /// Sets whether this swatch participates in keyboard focus traversal.
    pub fn tab_stop(mut self, tab_stop: bool) -> Self {
        self.tab_stop = tab_stop;
        self
    }
}

impl Styled for ColorSwatch {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for ColorSwatch {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl InteractiveElement for ColorSwatch {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }
}

impl StatefulInteractiveElement for ColorSwatch {}

impl RenderOnce for ColorSwatch {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let color = self.color;
        let disabled = self.disabled;
        let selected = self.selected;
        let label = self
            .accessibility_label
            .unwrap_or_else(|| hex_string(color).into());
        let focus_handle = window
            .use_keyed_state(self.id.clone(), cx, |_, cx| cx.focus_handle())
            .read(cx)
            .clone();

        self.base
            .when_some(self.role.resolve(|| Role::RadioButton), |this, role| {
                this.role(role)
            })
            .aria_label(label)
            // A palette color is both "toggled" and "selected"; assistive
            // technology reads one or the other, so state both.
            .aria_toggled(if selected {
                Toggled::True
            } else {
                Toggled::False
            })
            .aria_selected(selected)
            .when(!disabled, |this| {
                this.track_focus(
                    &focus_handle
                        .tab_index(self.tab_index)
                        .tab_stop(self.tab_stop),
                )
            })
            .when_some(
                (!disabled).then_some(self.on_hover).flatten(),
                |this, on_hover| {
                    this.on_hover(move |entered, window, cx| on_hover(color, *entered, window, cx))
                },
            )
            .when_some(
                (!disabled).then_some(self.on_click).flatten(),
                |this, on_click| {
                    this.on_click(move |event, window, cx| on_click(color, event, window, cx))
                },
            )
            .children(self.children)
            .refine_style(&self.style)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{TestAppContext, hsla, px};
    use std::{cell::RefCell, rc::Rc};

    #[test]
    fn parses_every_supported_hex_width() {
        let white = parse_hex("#fff").unwrap();
        assert_eq!(hex_string(white), "#FFFFFF");
        assert_eq!(parse_hex("ffffff"), Some(white));

        let half = parse_hex("#ff000080").unwrap();
        assert!((half.a - 0.5).abs() < 0.01);
        assert_eq!(parse_hex("#f008").map(|c| c.h), Some(half.h));
    }

    #[test]
    fn rejects_malformed_hex() {
        for value in ["#nope", "#12", "#1234567", "", "#+f0000", "#-fffff"] {
            assert_eq!(parse_hex(value), None, "{value} should not parse");
        }
    }

    #[test]
    fn formats_alpha_only_when_translucent() {
        assert_eq!(hex_string(hsla(0., 1., 0.5, 1.)), "#FF0000");
        assert_eq!(hex_string(hsla(0., 1., 0.5, 0.5)), "#FF000080");
    }

    fn state(cx: &mut TestAppContext) -> (Entity<ColorPickerState>, &mut gpui::VisualTestContext) {
        let (state, cx) = cx.add_window_view(ColorPickerState::new);
        cx.update(|window, cx| window.draw(cx).clear(cx));
        (state, cx)
    }

    #[gpui::test]
    fn default_value_reaches_the_hex_field_and_sliders(cx: &mut TestAppContext) {
        let (state, cx) = cx.add_window_view(|window, cx| {
            ColorPickerState::new(window, cx).default_value(hsla(0., 1., 0.5, 1.))
        });
        cx.update(|window, cx| {
            state.update(cx, |state, cx| state.sync_pending_value(window, cx));
        });

        state.read_with(cx, |state, cx| {
            assert_eq!(state.hex_input().read(cx).value().as_str(), "#FF0000");
            assert_eq!(state.sliders().lightness().read(cx).value().start(), 0.5);
        });
    }

    #[gpui::test]
    fn preview_does_not_change_the_committed_value(cx: &mut TestAppContext) {
        let (state, cx) = state(cx);
        let committed = hsla(0.1, 0.2, 0.3, 1.);
        let previewed = hsla(0.6, 0.7, 0.8, 1.);

        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.set_value(committed, window, cx);
                state.preview_color(previewed, window, cx);
            });
        });

        state.read_with(cx, |state, _| {
            assert_eq!(state.value(), Some(committed));
            assert_eq!(state.displayed_color(), Some(previewed));
        });

        cx.update(|window, cx| {
            state.update(cx, |state, cx| state.clear_preview(window, cx));
        });
        state.read_with(cx, |state, _| {
            assert_eq!(state.displayed_color(), Some(committed));
        });
    }

    #[gpui::test]
    fn first_hex_edit_after_set_value_previews(cx: &mut TestAppContext) {
        let (state, cx) = state(cx);
        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.set_value(hsla(0., 1., 0.5, 1.), window, cx)
            });
            // A typed edit: new text and the change event it brings.
            let input = state.read(cx).hex_input().clone();
            input.update(cx, |input, cx| {
                input.set_value("#00FF00", window, cx);
                cx.emit(InputEvent::Change);
            });
        });

        state.read_with(cx, |state, _| {
            assert_eq!(state.preview().map(hex_string).as_deref(), Some("#00FF00"));
        });
    }

    #[gpui::test]
    fn invalid_hex_leaves_preview_and_value_alone(cx: &mut TestAppContext) {
        let (state, cx) = state(cx);
        let color = hsla(0.1, 0.2, 0.3, 1.);

        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.set_value(color, window, cx);
                assert!(!state.preview_hex("#nope", window, cx));
                assert_eq!(state.commit_hex("#12", window, cx), None);
            });
        });

        state.read_with(cx, |state, _| {
            assert_eq!(state.preview(), Some(color));
            assert_eq!(state.value(), Some(color));
        });
    }

    #[gpui::test]
    fn palette_selection_closes_but_a_slider_update_stays_open(cx: &mut TestAppContext) {
        let (state, cx) = state(cx);
        let changes = Rc::new(RefCell::new(Vec::new()));
        let _subscription = cx.update(|_, cx| {
            let changes = changes.clone();
            cx.subscribe(&state, move |_, event: &ColorPickerEvent, _| {
                let ColorPickerEvent::Change(color) = event;
                changes.borrow_mut().push(*color);
            })
        });

        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.set_open(true, cx);
                state.update_color(hsla(0.2, 0.3, 0.4, 1.), window, cx);
            });
        });
        assert!(state.read_with(cx, |state, _| state.is_open()));

        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.select_color(hsla(0.5, 0.6, 0.7, 1.), window, cx);
            });
        });
        assert!(!state.read_with(cx, |state, _| state.is_open()));
        assert_eq!(changes.borrow().len(), 2);
    }

    #[gpui::test]
    fn committing_hex_updates_the_value_and_closes(cx: &mut TestAppContext) {
        let (state, cx) = state(cx);

        let committed = cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.set_open(true, cx);
                state.commit_hex("#ff0000", window, cx)
            })
        });

        state.read_with(cx, |state, _| {
            assert_eq!(state.value(), committed);
            assert_eq!(state.preview(), committed);
            assert!(!state.is_open());
        });
    }

    #[gpui::test]
    fn open_and_active_panel_are_controlled(cx: &mut TestAppContext) {
        let (state, cx) = state(cx);

        cx.update(|_, cx| {
            state.update(cx, |state, cx| {
                state.toggle_open(cx);
                state.set_active_tab(1, cx);
            });
        });

        state.read_with(cx, |state, _| {
            assert!(state.is_open());
            assert_eq!(state.active_tab(), 1);
        });
    }

    struct PickerHarness {
        open: bool,
        focus_handle: FocusHandle,
        changes: Rc<RefCell<Vec<bool>>>,
    }

    impl Render for PickerHarness {
        fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
            let entity = cx.entity();
            let changes = self.changes.clone();
            ColorPicker::new("picker")
                .open(self.open)
                .track_focus(&self.focus_handle)
                .size(px(20.))
                .on_open_change(move |open, _, cx| {
                    changes.borrow_mut().push(open);
                    entity.update(cx, |this, cx| {
                        this.open = open;
                        cx.notify();
                    });
                })
        }
    }

    #[gpui::test]
    fn confirm_toggles_and_cancel_dismisses(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let changes = Rc::new(RefCell::new(Vec::new()));
        let (state, cx) = cx.add_window_view({
            let changes = changes.clone();
            move |_, cx| PickerHarness {
                open: false,
                focus_handle: cx.focus_handle(),
                changes,
            }
        });
        cx.update(|window, cx| {
            state.read(cx).focus_handle.clone().focus(window, cx);
            window.draw(cx).clear(cx);
        });

        cx.simulate_keystrokes("enter");
        assert!(state.read_with(cx, |state, _| state.open));

        cx.simulate_keystrokes("enter");
        assert!(!state.read_with(cx, |state, _| state.open));

        cx.simulate_keystrokes("enter escape");
        assert!(!state.read_with(cx, |state, _| state.open));
        assert_eq!(&*changes.borrow(), &[true, false, true, false]);
    }
}
