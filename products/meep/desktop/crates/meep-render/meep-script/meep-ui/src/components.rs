//! Native View design system. Pixel-based rhythm, semantic text, quiet surfaces.
pub mod forms;
pub mod motion;
pub mod nav;
pub use crate::design::{BODY, CAPTION, NAV_ROW, PAGE_INSET, TITLE};
pub use crate::theme::{self, marker_color};
use gpui_kit::assets::IconName;
use gpui_kit::component::{
    Icon, Sizable,
    button::{Button, ButtonVariants},
};
use gpui_kit::prelude::FluentBuilder;
use gpui_kit::*;

pub const INK: u32 = 0x252525;
pub const SECONDARY: u32 = theme::DEFAULT[1];
pub const TERTIARY: u32 = 0x929292;
pub const CANVAS: u32 = 0xffffff;
pub const INSET: u32 = 0xf5f5f5;
pub const RULE: u32 = theme::DEFAULT[5];
pub const SPACE: [f32; 10] = [4., 8., 12., 16., 20., 24., 32., 40., 48., 64.];
pub const CONTROL: f32 = 32.;
pub const ROW: f32 = 56.;
pub const RADIUS: f32 = 6.;
pub const CONTROL_RADIUS: f32 = 8.;
pub const ICON_RADIUS: f32 = 6.;
pub const SURFACE_RADIUS: f32 = 8.;
pub const CHROME_INSET: f32 = 6.;
pub const PANEL_TITLE: f32 = 14.;
pub const SMALL: f32 = 11.;
pub const MONO: f32 = 11.5;
pub const HIT_TARGET: f32 = 28.;
pub const CHROME: u32 = 0xf6f6f6;
pub const SELECTED: u32 = 0xe9e9e9;
pub const HAIRLINE: u32 = 0x0000000c;
/// The theme's ink at `alpha` (0–255): hovers, wells and hairlines that darken
/// a light surface and lighten a dark one. Plain black vanishes on dark themes.
pub fn ink(alpha: u32) -> Rgba {
    rgba((theme::get(0) << 8) | (alpha & 0xff))
}
pub const HOVER: u32 = 0x00000008;
pub const PANEL_INSET: f32 = 16.;
pub const FORM_MEASURE: f32 = 480.;
pub const READING_MEASURE: f32 = 720.;

#[track_caller]
pub fn row() -> Div {
    div().flex().items_center().min_w_0().gap(px(8.))
}
#[track_caller]
pub fn column() -> Div {
    div().flex().flex_col().min_w_0().gap(px(8.))
}
#[track_caller]
pub fn page() -> Div {
    column()
        .size_full()
        .min_h_0()
        .bg(rgb(crate::components::theme::color(CANVAS)))
        .text_color(rgb(crate::components::theme::color(INK)))
        .font_family(system_font())
        .text_size(px(BODY))
        .line_height(relative(1.5))
        .px(px(PAGE_INSET))
        .py(px(PAGE_INSET))
}
#[track_caller]
pub fn reading_column() -> Div {
    column()
        .w_full()
        .max_w(px(READING_MEASURE))
        .flex_1()
        .min_h_0()
        .gap(px(24.))
}
#[track_caller]
pub fn heading(id: impl Into<ElementId>, label: impl Into<SharedString>) -> Stateful<Div> {
    let label = label.into();
    heading_style()
        .id(id)
        .role(Role::Heading)
        .aria_label(label.clone())
        .child(label)
}
/// A heading's type, for text that brings its own run (selectable text).
#[track_caller]
pub fn heading_style() -> Div {
    div()
        .text_size(px(TITLE))
        .font_weight(FontWeight::SEMIBOLD)
        .line_height(relative(1.35))
}
#[track_caller]
pub fn body(id: impl Into<ElementId>, label: impl Into<SharedString>) -> Stateful<Div> {
    let label = label.into();
    div()
        .id(id)
        .role(Role::Label)
        .aria_label(label.clone())
        .text_size(px(BODY))
        .line_height(relative(1.5))
        .child(label)
}
#[track_caller]
pub fn caption(label: impl Into<SharedString>) -> Div {
    caption_style().child(label.into())
}
#[track_caller]
pub fn mono(label: impl Into<SharedString>) -> Div {
    mono_style().child(label.into())
}
/// A caption's type, for text that brings its own run (selectable text).
#[track_caller]
pub fn caption_style() -> Div {
    div()
        .text_size(px(CAPTION))
        .text_color(rgb(crate::components::theme::color(SECONDARY)))
        .line_height(relative(1.5))
}
/// Monospaced caption type, for text that brings its own run.
#[track_caller]
pub fn mono_style() -> Div {
    caption_style().font_family(mono_font()).text_size(px(MONO))
}
#[track_caller]
pub fn section_label(label: impl Into<SharedString>) -> Div {
    caption(label)
        .font_weight(FontWeight::MEDIUM)
        .pt(px(8.))
        .pb(px(4.))
}
#[track_caller]
pub fn toolbar() -> Div {
    row().w_full().h(px(36.)).gap(px(12.))
}

/// The header belongs to the view, never to a second layer of host chrome.
#[track_caller]
pub fn page_header(
    id: impl Into<ElementId>,
    title: impl Into<SharedString>,
    description: impl Into<SharedString>,
    actions: impl IntoElement,
) -> Div {
    let description = description.into();
    row()
        .w_full()
        .items_start()
        .gap(px(16.))
        .pb(px(24.))
        .child(
            column()
                .flex_1()
                .gap(px(4.))
                .child(heading(id, title))
                .when(!description.is_empty(), |el| el.child(caption(description))),
        )
        .child(row().flex_shrink_0().gap(px(4.)).child(actions))
}

/// Connection forms have a readable measure and a stable vertical label axis.
/// Unlike a preference toggle, a text entry should not compete with its label.
#[track_caller]
pub fn field(
    title: impl Into<SharedString>,
    description: impl Into<SharedString>,
    control: impl IntoElement,
) -> Div {
    let description = description.into();
    column()
        .w_full()
        .max_w(px(FORM_MEASURE))
        .gap(px(8.))
        .pb(px(20.))
        .child(
            div()
                .text_size(px(BODY))
                .font_weight(FontWeight::MEDIUM)
                .child(title.into()),
        )
        .child(div().w_full().min_w_0().child(control))
        .when(!description.is_empty(), |el| el.child(caption(description)))
}

#[track_caller]
pub fn list_row(
    id: impl Into<ElementId>,
    title: impl Into<SharedString>,
    subtitle: impl Into<SharedString>,
) -> Stateful<Div> {
    let title = title.into();
    let subtitle = subtitle.into();
    row()
        .id(id)
        .role(Role::ListItem)
        .aria_label(title.clone())
        .aria_description(subtitle.clone())
        .w_full()
        .h(px(ROW))
        .border_b_1()
        .border_color(rgb(crate::components::theme::color(RULE)))
        .gap(px(16.))
        .child(
            column()
                .flex_1()
                .gap(px(3.))
                .child(div().text_size(px(BODY)).truncate().child(title))
                .child(caption(subtitle).truncate()),
        )
}
/// Horizontal padding of a small ghost button. A ghost button that ends a row
/// takes it as a negative trailing margin, so its text lands on the same edge
/// as the rules, fields and toggles around it instead of 8pt inside it.
pub const GHOST_INSET: f32 = 8.;

#[track_caller]
pub fn button(id: impl Into<ElementId>, label: impl Into<SharedString>) -> Button {
    Button::new(id)
        .small()
        .ghost()
        .h(px(CONTROL))
        .text_size(px(BODY))
        .rounded(px(CONTROL_RADIUS))
        .label(label)
}
/// A primary button that may be unavailable. Disabled, it gives up the
/// accent entirely: a neutral wash with quiet text and no key shadow, rather
/// than a faded tint of the accent that reads as a broken colour.
#[track_caller]
pub fn primary_button_state(
    id: impl Into<ElementId>,
    label: impl Into<SharedString>,
    disabled: bool,
) -> Button {
    if !disabled {
        return primary_button(id, label);
    }
    use gpui_kit::component::Disableable as _;
    Button::new(id)
        .small()
        .ghost()
        .h(px(CONTROL))
        .px(px(14.))
        .text_size(px(BODY))
        .font_weight(FontWeight::MEDIUM)
        .rounded(px(CONTROL_RADIUS))
        .bg(ink(0x0d))
        .text_color(rgb(theme::get(2)))
        .label(label)
        .disabled(true)
}

/// Copies `value`, then says so: the glyph turns into a green check that
/// grows in, and returns to the copy glyph a moment later.
#[derive(IntoElement)]
pub struct CopyButton {
    id: ElementId,
    label: SharedString,
    value: SharedString,
}
#[track_caller]
pub fn copy_button(
    id: impl Into<ElementId>,
    label: impl Into<SharedString>,
    value: impl Into<SharedString>,
) -> CopyButton {
    CopyButton {
        id: id.into(),
        label: label.into(),
        value: value.into(),
    }
}
impl RenderOnce for CopyButton {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let copied = window.use_keyed_state(
            ElementId::NamedChild(self.id.clone().into(), "copied".into()),
            cx,
            |_, _| 0u64,
        );
        let generation = *copied.read(cx);
        let value = self.value.clone();
        let state = copied.clone();
        let label = self.label.clone();
        Button::new(self.id)
            .small()
            .ghost()
            .size(px(HIT_TARGET))
            .rounded(px(ICON_RADIUS))
            .accessibility_label(label.clone())
            .tooltip(if generation > 0 {
                "Copied".into()
            } else {
                label
            })
            .child(if generation > 0 {
                div()
                    .size(px(14.))
                    .flex()
                    .items_center()
                    .justify_center()
                    .child(
                        Icon::new(IconName::Check)
                            .size(px(14.))
                            .text_color(rgb(theme::named("positive").unwrap_or(0x2f9e5b))),
                    )
                    .with_animation(
                        ElementId::Integer(generation),
                        Animation::new(std::time::Duration::from_millis(220))
                            .with_easing(ease_in_out),
                        |el, t| el.opacity(t).mt(px((1. - t) * 3.)),
                    )
                    .into_any_element()
            } else {
                Icon::new(IconName::Copy).size(px(14.)).into_any_element()
            })
            .on_click(move |_, _, cx| {
                cx.write_to_clipboard(ClipboardItem::new_string(value.to_string()));
                let next = state.update(cx, |n, cx| {
                    *n += 1;
                    cx.notify();
                    *n
                });
                let state = state.clone();
                cx.spawn(async move |cx| {
                    cx.background_executor()
                        .timer(std::time::Duration::from_millis(1500))
                        .await;
                    state.update(cx, |n, cx| {
                        // A newer copy keeps its own check.
                        if *n == next {
                            *n = 0;
                            cx.notify();
                        }
                    });
                })
                .detach();
            })
    }
}

#[track_caller]
pub fn primary_button(id: impl Into<ElementId>, label: impl Into<SharedString>) -> Button {
    Button::new(id)
        .small()
        .primary()
        .h(px(CONTROL))
        // Room either side of the words, as a Mac default button has.
        .px(px(14.))
        .text_size(px(BODY))
        .font_weight(FontWeight::MEDIUM)
        .rounded(px(CONTROL_RADIUS))
        // Flat, like the app's own primary actions: the accent carries it.
        .label(label)
}
#[track_caller]
pub fn icon_button(
    id: impl Into<ElementId>,
    icon: IconName,
    label: impl Into<SharedString>,
) -> Button {
    let label = label.into();
    Button::new(id)
        .small()
        .ghost()
        .size(px(HIT_TARGET))
        .rounded(px(ICON_RADIUS))
        .icon(Icon::new(icon).size(px(14.)))
        .accessibility_label(label.clone())
        .tooltip(label)
}

/// Quiet row actions stay visible for selection, attention and keyboard focus.
/// Reserve their width so hovering never moves the row's text.
pub fn contextual_icon_button(
    id: impl Into<ElementId>,
    icon: IconName,
    label: impl Into<SharedString>,
    group: impl Into<SharedString>,
    revealed: bool,
) -> Button {
    icon_button(id, icon, label)
        .opacity(if revealed { 1. } else { 0. })
        .group_hover(group, |style| style.opacity(1.))
        .focus_visible(|style| style.opacity(1.))
}

/// The destructive and attention red, shared with invalid fields (6.6:1 on white).
pub const DANGER: u32 = forms::INVALID;

/// Healthy state (4.6:1 on white): a connection that is up, a check that passed.
pub const POSITIVE: u32 = 0x248a3d;

/// A state with a colored dot, so "Connected" and "Disconnected" never look
/// alike. Problems also color their word; healthy states keep it quiet.
#[track_caller]
pub fn status(
    id: impl Into<ElementId>,
    label: impl Into<SharedString>,
    healthy: bool,
) -> Stateful<Div> {
    let label = label.into();
    let tone = if healthy { POSITIVE } else { DANGER };
    row()
        .id(id)
        .role(Role::Label)
        .aria_label(label.clone())
        .flex_none()
        .gap(px(6.))
        .child(div().flex_none().size(px(7.)).rounded_full().bg(rgb(tone)))
        .child(
            div()
                .text_size(px(BODY))
                .text_color(rgb(if healthy { SECONDARY } else { DANGER }))
                .child(label),
        )
}

/// An error the user has to notice: the danger red with an alert glyph,
/// announced as an alert. Never the helper-text gray, so it cannot be read as
/// a hint sitting next to one.
#[track_caller]
pub fn error_message(id: impl Into<ElementId>, detail: impl Into<SharedString>) -> Stateful<Div> {
    let detail = detail.into();
    row()
        .id(id)
        .role(Role::Alert)
        .aria_label(detail.clone())
        .items_start()
        .gap(px(6.))
        .child(
            div().flex_none().pt(px(2.5)).child(
                Icon::new(IconName::CircleAlert)
                    .size(px(13.))
                    .text_color(rgb(crate::components::theme::color(DANGER))),
            ),
        )
        .child(
            div()
                .flex_1()
                .min_w_0()
                .text_size(px(BODY))
                .line_height(relative(1.45))
                .text_color(rgb(crate::components::theme::color(DANGER)))
                .child(detail),
        )
}

#[track_caller]
pub fn notice(title: impl Into<SharedString>, detail: impl Into<SharedString>) -> Div {
    column()
        .w_full()
        .max_w(px(FORM_MEASURE))
        .gap(px(6.))
        .py(px(24.))
        .child(
            div()
                .text_size(px(BODY))
                .font_weight(FontWeight::MEDIUM)
                .child(title.into()),
        )
        .child(caption(detail))
}
#[track_caller]
pub fn empty(title: impl Into<SharedString>, detail: impl Into<SharedString>) -> Div {
    notice(title, detail)
}
#[track_caller]
pub fn loading() -> Div {
    column()
        .size_full()
        .items_center()
        .justify_center()
        .child(caption("Loading"))
}
#[track_caller]
pub fn error(detail: impl Into<SharedString>) -> Div {
    notice("Couldn’t refresh", detail)
}

/// An opaque reading surface inside native glass chrome.
#[track_caller]
pub fn surface() -> Div {
    column()
        .gap(px(0.))
        .bg(rgb(crate::components::theme::color(CANVAS)))
        .rounded(px(SURFACE_RADIUS))
        .border_1()
        .border_color(rgba((theme::get(0) << 8) | (HAIRLINE & 0xff)))
        .overflow_hidden()
}
/// Floating controls share one surface and elevation, never nested card shadows.
#[track_caller]
pub fn floating_surface() -> Div {
    column()
        .bg(rgb(crate::components::theme::color(CANVAS)))
        .rounded(px(SURFACE_RADIUS))
        .border_1()
        .border_color(rgba((theme::get(0) << 8) | (HAIRLINE & 0xff)))
        .shadow_md()
}
/// Native tabs: a baseline bar for page navigation, a segmented control for a
/// local mode. Drawn here rather than through GPUI Kit's TabBar so the
/// indicator, hover and focus treatment follow View's own rhythm.
type TabChange = std::rc::Rc<dyn Fn(&usize, &mut Window, &mut App)>;
/// Underline tabs pad their hover well by this much, and hang it into the
/// gutter by the same amount so the first label sits on the leading axis.
const TAB_INSET: f32 = 8.;
/// The well's height; the bar adds room below it for the indicator.
const TAB_WELL: f32 = 28.;
const TAB_RULE_GAP: f32 = 4.;
#[derive(IntoElement)]
pub struct NativeTabs {
    id: ElementId,
    labels: Vec<SharedString>,
    selected: usize,
    on_change: Option<TabChange>,
    style: StyleRefinement,
    underline: bool,
}
impl NativeTabs {
    /// Page navigation uses a baseline; segmented controls choose a mode.
    pub fn underline(mut self) -> Self {
        self.underline = true;
        self
    }
    pub fn on_click(mut self, callback: impl Fn(&usize, &mut Window, &mut App) + 'static) -> Self {
        self.on_change = Some(std::rc::Rc::new(callback));
        self
    }
}
impl Styled for NativeTabs {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}
/// Where each tab landed last frame, relative to the strip that holds them,
/// and where the indicator was placed from that measurement.
#[derive(Default)]
struct TabLayout {
    strip: Bounds<Pixels>,
    tabs: Vec<Bounds<Pixels>>,
    placed: Option<(Pixels, Pixels)>,
}
impl TabLayout {
    fn target(&self, selected: usize) -> Option<(Pixels, Pixels)> {
        let tab = self.tabs.get(selected)?;
        (self.strip.size.width > px(0.) && tab.size.width > px(0.))
            .then(|| (tab.origin.x - self.strip.origin.x, tab.size.width))
    }
}
/// The raised segment of a segmented control.
fn tab_thumb<E: Styled>(el: E) -> E {
    if theme::is_dark() {
        el.bg(ink(0x1f)).border_1().border_color(ink(0x0c))
    } else {
        el.bg(rgb(theme::get(3)))
            .border_1()
            .border_color(ink(0x0f))
            .shadow(vec![BoxShadow {
                color: rgba(0x0000001a).into(),
                offset: point(px(0.), px(1.)),
                blur_radius: px(2.),
                spread_radius: px(0.),
                inset: false,
            }])
    }
}
fn focus_ring() -> Vec<BoxShadow> {
    vec![BoxShadow {
        color: rgba((theme::get(10) << 8) | 0x80).into(),
        offset: point(px(0.), px(0.)),
        blur_radius: px(0.),
        spread_radius: px(2.),
        inset: false,
    }]
}
impl RenderOnce for NativeTabs {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        use gpui_kit::base::ElementExt;
        let count = self.labels.len();
        let selected = self.selected.min(count.saturating_sub(1));
        let underline = self.underline;
        let key =
            |part: &str| ElementId::NamedChild(self.id.clone().into(), part.to_owned().into());
        let focus_state =
            window.use_keyed_state(key("tab-focus"), cx, |_, _| Vec::<FocusHandle>::new());
        focus_state.update(cx, |handles, cx| {
            while handles.len() < count {
                handles.push(cx.focus_handle());
            }
            handles.truncate(count);
        });
        let handles = focus_state.read(cx).clone();
        let layout = window
            .use_keyed_state(key("tab-layout"), cx, |_, _| {
                std::rc::Rc::new(std::cell::RefCell::new(TabLayout::default()))
            })
            .read(cx)
            .clone();
        layout.borrow_mut().tabs.resize(count, Bounds::default());

        // The indicator slides between measured tabs. Until the tabs have been
        // measured once, the selected tab paints its own indicator in place.
        let target = layout.borrow().target(selected);
        layout.borrow_mut().placed = target;
        let policy = gpui_kit::component::ActiveTheme::theme(cx)
            .motion_tokens()
            .spring_move;
        let indicator = target.map(|(left, width)| {
            let left =
                gpui_kit::base::spring((key("tab-indicator"), "left"), left, policy, window, cx);
            let width =
                gpui_kit::base::spring((key("tab-indicator"), "width"), width, policy, window, cx);
            (left, width)
        });
        let sliding = indicator.is_some();

        let ink_color = rgb(theme::get(0));
        let secondary = rgb(theme::get(1));
        let view = window.current_view();
        let mut strip = div()
            .relative()
            .flex()
            .flex_row()
            .items_start()
            .min_w_0()
            .when(underline, |el| el.ml(px(-TAB_INSET)))
            .when(!underline, |el| el.h_full());
        if let Some((left, width)) = indicator {
            strip = strip.child(if underline {
                div()
                    .absolute()
                    .bottom_0()
                    .left(left + px(TAB_INSET))
                    .w((width - px(TAB_INSET * 2.)).max(px(0.)))
                    .h(px(2.))
                    .rounded(px(1.))
                    .bg(ink_color)
            } else {
                tab_thumb(
                    div()
                        .absolute()
                        .top_0()
                        .bottom_0()
                        .left(left)
                        .w(width)
                        .rounded(px(6.)),
                )
            });
        }
        for (index, label) in self.labels.into_iter().enumerate() {
            let is_selected = index == selected;
            let keyboard_handles = handles.clone();
            let key_change = self.on_change.clone();
            let click_change = self.on_change.clone();
            let click_handle = handles[index].clone();
            let measure = layout.clone();
            let tab = div()
                .id(("tab", index))
                .role(Role::Tab)
                .aria_label(label.clone())
                .aria_selected(is_selected)
                .track_focus(&handles[index].clone().tab_index(0).tab_stop(is_selected))
                .relative()
                .flex()
                .items_center()
                .justify_center()
                .h(px(if underline { TAB_WELL } else { CONTROL - 4. }))
                .px(px(if underline { TAB_INSET } else { 12. }))
                .rounded(px(6.))
                .whitespace_nowrap()
                .text_size(px(BODY))
                .font_weight(FontWeight::MEDIUM)
                .cursor_pointer()
                .text_color(if is_selected { ink_color } else { secondary })
                .when(!is_selected, |el| {
                    el.hover(|style| {
                        let style = style.text_color(ink_color);
                        if underline {
                            style.bg(ink(0x0a))
                        } else {
                            style
                        }
                    })
                    .active(|style| {
                        if underline {
                            style.bg(ink(0x12))
                        } else {
                            style.text_color(ink_color)
                        }
                    })
                })
                .when(underline && is_selected, |el| {
                    el.hover(|style| style.bg(ink(0x0a)))
                })
                .focus_visible(|style| style.shadow(focus_ring()))
                // First frame only: the selected tab draws its own indicator
                // until the strip has been measured.
                .when(is_selected && !sliding && !underline, tab_thumb)
                .child(label)
                .on_click(move |_, window, cx| {
                    click_handle.focus(window, cx);
                    if let Some(callback) = &click_change {
                        callback(&index, window, cx);
                    }
                })
                .on_key_down(move |event, window, cx| {
                    if event.keystroke.modifiers != Modifiers::default() {
                        return;
                    }
                    let next = match event.keystroke.key.as_str() {
                        "left" => (index + count - 1) % count,
                        "right" => (index + 1) % count,
                        "home" => 0,
                        "end" => count - 1,
                        "enter" | "space" => index,
                        _ => return,
                    };
                    window.prevent_default();
                    cx.stop_propagation();
                    keyboard_handles[next].focus(window, cx);
                    if let Some(callback) = &key_change {
                        callback(&next, window, cx);
                    }
                });
            let separator =
                !underline && index + 1 < count && index != selected && index + 1 != selected;
            strip = strip
                .child(
                    div()
                        .relative()
                        .flex_none()
                        .when(underline, |el| el.pb(px(TAB_RULE_GAP + 2.)))
                        .when(underline && is_selected && !sliding, |el| {
                            el.child(
                                div()
                                    .absolute()
                                    .bottom_0()
                                    .left(px(TAB_INSET))
                                    .right(px(TAB_INSET))
                                    .h(px(2.))
                                    .rounded(px(1.))
                                    .bg(ink_color),
                            )
                        })
                        .child(tab)
                        .on_prepaint(move |bounds, _, _| {
                            if let Some(slot) = measure.borrow_mut().tabs.get_mut(index) {
                                *slot = bounds;
                            }
                        }),
                )
                .when(!underline && index + 1 < count, |el| {
                    el.child(
                        div().flex_none().h_full().flex().items_center().child(
                            div()
                                .w(px(1.))
                                .h(px(12.))
                                .when(separator, |el| el.bg(ink(0x1a))),
                        ),
                    )
                });
        }
        // Prepaint runs after the tabs', so the whole strip is measured here.
        // A view that nothing changed may not render again, so when the
        // indicator was placed from stale bounds, render once more.
        let measure = layout;
        strip = strip.on_prepaint(move |bounds, window, _| {
            let mut layout = measure.borrow_mut();
            layout.strip = bounds;
            if layout.target(selected) != layout.placed {
                window.on_next_frame(move |_, cx| cx.notify(view));
            }
        });

        let mut bar = div()
            .id(self.id)
            .role(Role::TabList)
            .relative()
            .flex()
            .flex_none()
            .min_w_0()
            .font_family(system_font())
            .line_height(relative(1.25));
        bar = if underline {
            bar.items_end().child(
                // The baseline runs under the whole bar; the indicator sits on it.
                div()
                    .absolute()
                    .left_0()
                    .right_0()
                    .bottom_0()
                    .h(px(1.))
                    .bg(ink(0x14)),
            )
        } else {
            bar.h(px(CONTROL)).p(px(2.)).rounded(px(8.)).bg(ink(0x0d))
        };
        bar.child(strip).map(|mut bar| {
            bar.style().refine(&self.style);
            bar
        })
    }
}
pub fn tabs(id: impl Into<ElementId>, labels: &[&str], selected: usize) -> NativeTabs {
    NativeTabs {
        id: id.into(),
        labels: labels
            .iter()
            .map(|label| (*label).to_owned().into())
            .collect(),
        selected,
        on_change: None,
        style: StyleRefinement::default(),
        underline: false,
    }
}

/// Use the bundled, unmodified Inter face on the web; macOS keeps its system face.
pub fn system_font() -> &'static str {
    if cfg!(target_family = "wasm") {
        "Inter"
    } else {
        ".SystemUIFont"
    }
}

/// The browser's bundled OFL mono face; macOS keeps Menlo.
pub fn mono_font() -> &'static str {
    if cfg!(target_family = "wasm") {
        "JetBrains Mono"
    } else {
        "Menlo"
    }
}
