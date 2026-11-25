//! The settings design kit, shared by app settings and view settings so both
//! read as one place: a page header, sections, filled groups of rows, and pill
//! buttons. Two edges, never more: everything outside a group (titles,
//! headings, notes, switches, buttons) sits on the group's own edge, and
//! everything inside it on the group's 16pt inner padding.
use crate::components::{self, CANVAS, INK};
use gpui_kit::assets::IconName as Glyph;
use gpui_kit::component::{
    Icon, Sizable,
    button::{Button, ButtonVariants},
};
use gpui_kit::prelude::FluentBuilder;
use gpui_kit::*;

fn row() -> Div {
    components::row().gap(px(0.))
}
fn col() -> Div {
    components::column().gap(px(0.))
}
fn text(value: impl Into<SharedString>) -> Div {
    div().child(value.into())
}

/// Reading measure of a settings page.
pub const MEASURE: f32 = 640.;
/// Side padding of a settings page.
pub const PAGE_X: f32 = 40.;
pub const PAGE_TOP: f32 = 36.;
/// Inner padding of a group; the edge every trailing control sits on.
pub const ROW_X: f32 = 16.;
pub const GROUP_RADIUS: f32 = 12.;
pub const PILL: f32 = 28.;
/// Group fill and the hairline between its rows, as ink over the page so
/// dark themes lighten where light ones darken.
pub const FILL: u32 = 0x08;
const DIVIDER: u32 = 0x0e;

fn ink() -> Rgba {
    rgb(crate::components::theme::color(INK))
}
fn secondary() -> Rgba {
    rgb(crate::components::theme::get(1))
}

/// Page title, one line of description, and an optional action on the
/// title's line.
pub fn header(
    title: impl Into<SharedString>,
    description: impl Into<SharedString>,
    action: Option<AnyElement>,
) -> Div {
    let description: SharedString = description.into();
    row()
        .w_full()
        .items_start()
        .gap(px(16.))
        .pb(px(28.))
        .child(
            col()
                .flex_1()
                .min_w_0()
                .gap(px(6.))
                .child(
                    text(title)
                        .text_size(px(22.))
                        .line_height(px(28.))
                        .font_weight(FontWeight::SEMIBOLD)
                        .text_color(ink()),
                )
                .when(!description.is_empty(), |el| {
                    el.child(
                        text(description)
                            .max_w(px(520.))
                            .text_size(px(13.))
                            .line_height(px(19.))
                            .text_color(secondary()),
                    )
                }),
        )
        .when_some(action, |el, action| {
            // Centred on the title's 28pt line.
            el.child(
                div()
                    .flex_none()
                    .h(px(28.))
                    .flex()
                    .items_center()
                    .child(action),
            )
        })
}

/// A labelled block of the page. The first section on a page passes
/// `first` so the header's spacing is not doubled.
pub fn section(
    title: impl Into<SharedString>,
    description: impl Into<SharedString>,
    action: Option<AnyElement>,
    first: bool,
) -> Div {
    let description: SharedString = description.into();
    let has_action = action.is_some();
    row()
        .w_full()
        .items_start()
        .gap(px(16.))
        .when(!first, |el| el.pt(px(32.)))
        .pb(px(if has_action { 16. } else { 10. }))
        .child(
            col()
                .flex_1()
                .min_w_0()
                .gap(px(2.))
                .child(
                    // With an action the title line takes the button's 28pt
                    // height, so the pill sits within the header instead of
                    // hanging over the list below.
                    div()
                        .when(has_action, |el| el.h(px(28.)).flex().items_center())
                        .child(
                            text(title)
                                .text_size(px(13.))
                                .line_height(px(18.))
                                .font_weight(FontWeight::SEMIBOLD)
                                .text_color(ink()),
                        ),
                )
                .when(!description.is_empty(), |el| {
                    el.child(
                        text(description)
                            .text_size(px(12.))
                            .line_height(px(17.))
                            .text_color(secondary()),
                    )
                }),
        )
        .when_some(action, |el, action| {
            el.child(
                div()
                    .flex_none()
                    .h(px(28.))
                    .flex()
                    .items_center()
                    .child(action),
            )
        })
}

/// Rows on one soft filled plate, separated by inset hairlines.
pub fn group(rows: impl IntoIterator<Item = AnyElement>) -> Div {
    let mut plate = col()
        .w_full()
        .gap(px(0.))
        .rounded(px(GROUP_RADIUS))
        .bg(crate::components::ink(FILL))
        .overflow_hidden();
    for (n, row) in rows.into_iter().enumerate() {
        if n > 0 {
            plate = plate.child(
                div()
                    .mx(px(ROW_X))
                    .h(px(1.))
                    .flex_none()
                    .bg(crate::components::ink(DIVIDER)),
            );
        }
        plate = plate.child(row);
    }
    plate
}

/// Title and secondary line of a row.
pub fn copy(title: impl Into<SharedString>, detail: impl Into<SharedString>) -> Div {
    let detail: SharedString = detail.into();
    col()
        .flex_1()
        .min_w_0()
        .gap(px(2.))
        .child(
            text(title)
                .truncate()
                .text_size(px(13.))
                .line_height(px(18.))
                .font_weight(FontWeight::MEDIUM)
                .text_color(ink()),
        )
        .when(!detail.is_empty(), |el| {
            el.child(
                text(detail)
                    .text_size(px(12.))
                    .line_height(px(17.))
                    .text_color(secondary()),
            )
        })
}

/// One row of a group: copy on the left, a control on the trailing edge.
pub fn item(
    title: impl Into<SharedString>,
    detail: impl Into<SharedString>,
    control: impl IntoElement,
) -> Div {
    let detail: SharedString = detail.into();
    row()
        .w_full()
        .min_h(px(if detail.is_empty() { 48. } else { 60. }))
        .px(px(ROW_X))
        .py(px(10.))
        .gap(px(16.))
        // The label keeps room for a word or two; a wide control (a text
        // field) gives way before the label truncates.
        .child(copy(title, detail).min_w(px(64.)))
        .child(row().flex_shrink(1.).min_w_0().gap(px(8.)).child(control))
}

/// One form row of a group: the label above a full-width field, for text
/// entry that would otherwise be squeezed against the trailing edge.
pub fn field(
    title: impl Into<SharedString>,
    detail: impl Into<SharedString>,
    control: impl IntoElement,
) -> Div {
    col()
        .w_full()
        .px(px(ROW_X))
        .py(px(12.))
        .gap(px(8.))
        .child(copy(title, detail).flex_none())
        .child(div().w_full().min_w_0().child(control))
}

/// The closing row of a form group: its actions on the trailing edge.
pub fn footer(actions: impl IntoElement) -> Div {
    row()
        .w_full()
        .justify_end()
        .gap(px(8.))
        .px(px(ROW_X))
        .py(px(12.))
        .child(actions)
}

/// A row that opens a page: the whole row is the target, with a value and a
/// chevron on the trailing edge.
pub fn link(
    id: impl Into<ElementId>,
    title: impl Into<SharedString>,
    detail: impl Into<SharedString>,
    value: impl Into<SharedString>,
) -> Stateful<Div> {
    let title: SharedString = title.into();
    let value: SharedString = value.into();
    let detail: SharedString = detail.into();
    row()
        .id(id)
        .role(Role::Button)
        .aria_label(title.clone())
        .w_full()
        .min_h(px(if detail.is_empty() { 48. } else { 60. }))
        .px(px(ROW_X))
        .py(px(10.))
        .gap(px(12.))
        .cursor_pointer()
        .hover(|s| s.bg(crate::components::ink(0x05)))
        .active(|s| s.bg(crate::components::ink(0x0a)))
        .child(copy(title, detail))
        .when(!value.is_empty(), |el| el.child(value_text(value)))
        .child(
            Icon::new(Glyph::ChevronRight)
                .size(px(14.))
                .text_color(rgb(crate::components::theme::get(2))),
        )
}

/// A suggestion in an empty group: a leading tile, what it is, an
/// optional quiet value, and a chevron. The whole row starts it.
pub fn suggestion(
    id: impl Into<ElementId>,
    tile: impl IntoElement,
    title: impl Into<SharedString>,
    detail: impl Into<SharedString>,
    value: impl Into<SharedString>,
) -> Stateful<Div> {
    let value: SharedString = value.into();
    suggestion_with(
        id,
        tile,
        title,
        detail,
        (!value.is_empty()).then(|| value_text(value).into_any_element()),
    )
}

/// A suggestion whose trailing value is an element, such as a [`status`].
pub fn suggestion_with(
    id: impl Into<ElementId>,
    tile: impl IntoElement,
    title: impl Into<SharedString>,
    detail: impl Into<SharedString>,
    value: Option<AnyElement>,
) -> Stateful<Div> {
    let title: SharedString = title.into();
    row()
        .id(id)
        .role(Role::Button)
        .aria_label(title.clone())
        .w_full()
        .h(px(60.))
        .px(px(ROW_X))
        .gap(px(12.))
        .cursor_pointer()
        .hover(|s| s.bg(crate::components::ink(0x05)))
        .active(|s| s.bg(crate::components::ink(0x0a)))
        .child(tile)
        .child(copy(title, detail))
        .when_some(value, |el, value| el.child(div().flex_none().child(value)))
        .child(
            Icon::new(Glyph::ChevronRight)
                .size(px(14.))
                .text_color(rgb(crate::components::theme::get(2))),
        )
}

/// A small canvas tile, raised off a group's fill.
pub fn tile() -> Div {
    div()
        .size(px(32.))
        .flex_none()
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(8.))
        .bg(rgb(crate::components::theme::color(
            crate::components::CANVAS,
        )))
}

/// A tile for a third-party logo. `brands::legible` lifts monochrome and dark
/// marks to the theme's ink in a dark theme, so the tile there is a subtle
/// dark well rather than a light plate that would swallow those white marks.
pub fn logo_tile() -> Div {
    let tile = div()
        .size(px(32.))
        .flex_none()
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(8.));
    if crate::theme::is_dark() {
        tile.bg(crate::components::ink(0x14))
    } else {
        tile.bg(rgb(crate::components::theme::color(CANVAS)))
    }
    .border_1()
    .border_color(crate::components::ink(0x10))
}

/// What a status reports, and so the colour of its dot.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Tone {
    Neutral,
    Positive,
    Warning,
    Danger,
}

fn tone_color(tone: Tone) -> Rgba {
    rgb(match tone {
        Tone::Neutral => crate::components::theme::get(2),
        Tone::Positive => crate::theme::named("positive").unwrap_or(0x248a3d),
        Tone::Warning => crate::theme::named("orange").unwrap_or(0xc2610c),
        Tone::Danger => crate::theme::named("danger").unwrap_or(0xa33932),
    })
}

/// A trailing status: a 6pt dot in its tone, then the words. A danger status
/// also colours its words.
pub fn status(value: impl Into<SharedString>, tone: Tone) -> Div {
    row()
        .flex_none()
        .gap(px(6.))
        .child(
            div()
                .flex_none()
                .size(px(6.))
                .rounded_full()
                .bg(tone_color(tone)),
        )
        .child(value_text(value).when(tone == Tone::Danger, |el| {
            el.text_color(tone_color(Tone::Danger))
        }))
}

/// Make a button the destructive action: a solid danger fill with white
/// words, a shade darker on hover. It replaces any earlier variant, primary
/// included, so a confirm reads as the live action rather than a disabled one.
pub fn danger(button: Button, cx: &App) -> Button {
    let fill: Hsla = tone_color(Tone::Danger).into();
    let shade = |by: f32| Hsla {
        l: (fill.l - by).max(0.),
        ..fill
    };
    button
        .custom(
            gpui_kit::component::button::ButtonCustomVariant::new(cx)
                .color(fill)
                .foreground(rgb(0xffffff).into())
                .hover(shade(0.05))
                .active(shade(0.1)),
        )
        // A custom variant's resting fill is mixed down to 20% alpha, which
        // reads as disabled. The explicit fill keeps it solid; hover and
        // press still apply their own shades over it.
        .bg(fill)
        .text_color(rgb(0xffffff))
        .border_0()
}

/// A quiet trailing value: a count, a status.
pub fn value_text(value: impl Into<SharedString>) -> Div {
    text(value)
        .flex_none()
        .text_size(px(13.))
        .text_color(secondary())
}

/// The secondary pill: a raised paper key that reads on the page and on a
/// group's fill alike.
pub fn pill(id: impl Into<ElementId>, label: impl Into<SharedString>, cx: &App) -> Button {
    Button::new(id)
        .custom(
            gpui_kit::component::button::ButtonCustomVariant::new(cx)
                .color(rgb(crate::components::theme::color(CANVAS)).into())
                .foreground(ink().into())
                .hover(crate::components::ink(0x0a).into())
                .active(crate::components::ink(0x12).into()),
        )
        .small()
        .h(px(PILL))
        .px(px(12.))
        .border_1()
        .border_color(crate::components::ink(0x1a))
        .rounded(px(PILL / 2.))
        .text_size(px(12.5))
        .font_weight(FontWeight::MEDIUM)
        .label(label)
}

/// The one emphasised action on a page.
pub fn primary_pill(id: impl Into<ElementId>, label: impl Into<SharedString>) -> Button {
    Button::new(id)
        .small()
        .primary()
        .h(px(PILL))
        .px(px(14.))
        .rounded(px(PILL / 2.))
        .text_size(px(12.5))
        .font_weight(FontWeight::MEDIUM)
        .label(label)
}

/// A soft placeholder for a group with nothing in it yet.
pub fn empty(title: impl Into<SharedString>, detail: impl Into<SharedString>) -> Div {
    col()
        .w_full()
        .items_center()
        .gap(px(4.))
        .py(px(32.))
        .px(px(24.))
        .rounded(px(GROUP_RADIUS))
        .bg(crate::components::ink(0x05))
        .child(
            text(title)
                .text_size(px(13.))
                .font_weight(FontWeight::MEDIUM)
                .text_color(ink()),
        )
        .child(
            // Centred under its centred title, at a line length that reads.
            text(detail)
                .max_w(px(420.))
                .text_center()
                .text_size(px(12.))
                .line_height(px(17.))
                .text_color(secondary()),
        )
}

/// A footnote under a group.
pub fn note(value: impl Into<SharedString>) -> Div {
    text(value)
        .pt(px(10.))
        .text_size(px(12.))
        .line_height(px(17.))
        .text_color(rgb(crate::components::theme::get(2)))
}

/// A pill segmented control: one choice of a few, the chosen one raised.
pub fn segmented(
    id: &str,
    labels: &[&'static str],
    selected: Option<usize>,
    on_select: impl Fn(usize, &mut Window, &mut App) + 'static,
) -> Div {
    let labels: Vec<SharedString> = labels.iter().map(|l| SharedString::from(*l)).collect();
    segmented_labels(id, &labels, selected, on_select)
}

/// The same control with labels known only at run time (machine names).
pub fn segmented_labels(
    id: &str,
    labels: &[SharedString],
    selected: Option<usize>,
    on_select: impl Fn(usize, &mut Window, &mut App) + 'static,
) -> Div {
    let on_select = std::rc::Rc::new(on_select);
    let mut track = row()
        .flex_none()
        .h(px(PILL))
        .p(px(2.))
        .gap(px(0.))
        .rounded(px(PILL / 2.))
        .bg(crate::components::ink(0x0c));
    for (index, title) in labels.iter().enumerate() {
        let chosen = selected == Some(index);
        let on_select = on_select.clone();
        track = track.child(
            div()
                .id(SharedString::from(format!("{id}-{index}")))
                .role(Role::RadioButton)
                .aria_label(title.clone())
                .aria_selected(chosen)
                .h_full()
                .px(px(11.))
                .flex()
                .items_center()
                .rounded(px(PILL / 2. - 2.))
                .cursor_pointer()
                .text_size(px(12.))
                .font_weight(FontWeight::MEDIUM)
                .text_color(rgb(crate::components::theme::get(if chosen {
                    0
                } else {
                    1
                })))
                .when(chosen, raised)
                .when(!chosen, |chip| chip.hover(|s| s.text_color(ink())))
                .child(title.clone())
                .on_click(move |_, window, cx| on_select(index, window, cx)),
        );
    }
    track
}

/// The raised chip of a segmented control.
pub fn raised<E: Styled>(chip: E) -> E {
    chip.bg(rgb(crate::components::theme::color(CANVAS)))
        .shadow(vec![
            BoxShadow {
                color: rgba(0x00000014).into(),
                offset: point(px(0.), px(1.)),
                blur_radius: px(2.),
                spread_radius: px(0.),
                inset: false,
            },
            BoxShadow {
                color: rgba(0x0000000a).into(),
                offset: point(px(0.), px(0.)),
                blur_radius: px(0.),
                spread_radius: px(0.5),
                inset: false,
            },
        ])
}

/// A pill that opens a menu: the choice, then a chevron after it.
pub fn menu_pill(id: impl Into<ElementId>, label: impl Into<SharedString>, cx: &App) -> Button {
    let label: SharedString = label.into();
    Button::new(id)
        .custom(
            gpui_kit::component::button::ButtonCustomVariant::new(cx)
                .color(rgb(crate::components::theme::color(CANVAS)).into())
                .foreground(ink().into())
                .hover(crate::components::ink(0x0a).into())
                .active(crate::components::ink(0x12).into()),
        )
        .small()
        .h(px(PILL))
        .pl(px(12.))
        .pr(px(9.))
        .rounded(px(PILL / 2.))
        .border_1()
        .border_color(crate::components::ink(0x1a))
        .accessibility_label(label.clone())
        .child(
            row()
                .min_w_0()
                .gap(px(6.))
                .child(
                    text(label)
                        .min_w_0()
                        .truncate()
                        .text_size(px(12.5))
                        .font_weight(FontWeight::MEDIUM),
                )
                .child(
                    Icon::new(Glyph::ChevronDown)
                        .size(px(12.))
                        .text_color(secondary()),
                ),
        )
}

pub use crate::controls::Unavailable;
