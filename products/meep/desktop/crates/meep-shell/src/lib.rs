//! Native GPUI shell components for desktop hosts.
pub mod agent_panel;
pub mod appearance;
pub mod chat;
/// Drafts and controls for composing session messages.
pub mod composer;
pub mod puppet;
pub mod transcript;
const MUTED: u32 = ui::SECONDARY;
const LINE: u32 = ui::RULE;
fn text(s: impl Into<SharedString>) -> Div {
    div().child(s.into())
}
fn label(s: impl Into<SharedString>) -> Div {
    ui::caption(s)
}
fn icon(glyph: Glyph) -> Icon {
    Icon::new(glyph).size(px(14.))
}
pub use meep_ui::{controls, settings};
pub mod icons;
pub mod material;
pub mod model_picker;
pub mod shortcuts;
pub mod wallpaper;
pub mod workspace;
use gpui_kit::assets::IconName as Glyph;
use gpui_kit::component::{Icon, Sizable, button::Button};
use gpui_kit::prelude::FluentBuilder;
use gpui_kit::*;
use meep_ui::components as ui;
const PAPER: u32 = 0xffffff;
const INK: u32 = ui::INK;
fn row() -> Div {
    ui::row().gap(px(0.))
}
fn col() -> Div {
    ui::column().gap(px(0.))
}
/// One gutter separates every floating surface from the window and from each
/// other, so the glass reads as a single plane with panes resting on it.
pub const GUTTER: f32 = 8.;
/// Vertical centre of the AppKit traffic lights (origin y 20, 14pt tall), so
/// titlebar controls sit on the same line.
pub const TRAFFIC_LIGHT_CENTER: f32 = 27.;
/// Right edge of the traffic lights; titlebar controls start after it.
pub const TRAFFIC_LIGHT_END: f32 = 80.;
/// Below this the view yields: the sidebar hides before the view gets narrower.
pub const MIN_VIEW_WIDTH: f32 = 420.;
/// The window glass corner (see the root material). Surfaces share one radius
/// so the view and the agent panel read as siblings, not a card and a slab.
pub const WINDOW_RADIUS: f32 = 12.;
/// Corner radius shared by floating content panes.
pub const PANE_RADIUS: f32 = 12.;

/// A pane resting on the window glass: opaque paper, one radius, and elevation
/// instead of a hairline. The edge is a half-point contact shadow (one device
/// pixel on Retina), so the boundary stays crisp without drawing a border box.
pub fn pane_shadow() -> Vec<BoxShadow> {
    vec![
        BoxShadow {
            color: rgba(0x0000000f).into(),
            offset: point(px(0.), px(0.)),
            blur_radius: px(0.),
            spread_radius: px(0.5),
            inset: false,
        },
        BoxShadow {
            color: rgba(0x0000000a).into(),
            offset: point(px(0.), px(1.)),
            blur_radius: px(2.),
            spread_radius: px(0.),
            inset: false,
        },
        BoxShadow {
            color: rgba(0x00000008).into(),
            offset: point(px(0.), px(4.)),
            blur_radius: px(14.),
            spread_radius: px(-2.),
            inset: false,
        },
    ]
}
/// Titlebar-row geometry. Every control is centred on the traffic lights and
/// the gaps between inks repeat: lights, 14pt, sidebar toggle, 13pt, title.
pub mod titlebar {
    use super::*;
    /// Hit target of a titlebar control; its hover plate.
    pub const BUTTON: f32 = 24.;
    /// Glyph size. Panel glyphs draw a 13pt ink inside it, a point under the lights.
    pub const ICON: f32 = 15.;
    /// Ink width of the plus glyph.
    pub const PLUS_INK: f32 = 10.;
    /// Where the sidebar toggle's hit target starts.
    pub const TOGGLE_LEFT: f32 = TRAFFIC_LIGHT_END + 7.;
    /// From the last toolbar button's hit target to the title's first
    /// letter: far enough that the title doesn't read as the button's label.
    pub const TITLE_GAP: f32 = 12.;
    /// Height of the glass band above the panes when the sidebar is hidden:
    /// the lights get as much air below as above.
    pub fn band() -> f32 {
        (2. * TRAFFIC_LIGHT_CENTER).max(meep_ui::design::current().toolbar)
    }

    /// Build an icon button sized for the window titlebar.
    #[track_caller]
    pub fn button(id: &'static str, glyph: Glyph, label: impl Into<SharedString>) -> Button {
        ui::icon_button(id, glyph, label)
            // Button draws its icon at three quarters of its size.
            .with_size(px(ICON / 0.75))
            .size(px(BUTTON))
            .rounded(px(ui::ICON_RADIUS))
            .text_color(rgb(ui::theme::color(ui::SECONDARY)))
    }
}
/// The pane shadow while a pane fades. GPUI applies opacity per primitive, so a
/// full shadow would show through the half-transparent pane; it ramps cubically.
pub fn pane_shadow_at(progress: f32) -> Vec<BoxShadow> {
    let ink = progress.clamp(0., 1.).powi(3);
    pane_shadow()
        .into_iter()
        .map(|mut shadow| {
            shadow.color = shadow.color.opacity(ink);
            shadow
        })
        .collect()
}
/// The pane's own colour laid over its contents, painted after them. Raising
/// it reads as the contents fading while the pane itself stays solid.
pub fn veil(amount: f32) -> impl IntoElement {
    deferred(
        div()
            .absolute()
            .inset_0()
            .rounded(px(PANE_RADIUS))
            .bg(rgb(ui::theme::color(PAPER)))
            .opacity(amount),
    )
}

/// Apply the shell's paper background, border and elevation to a pane.
pub fn pane(el: Div) -> Div {
    el.bg(rgb(ui::theme::color(PAPER)))
        // A hairline edge, so a pane reads as a sheet laid on the patterned
        // glass rather than a hole in it.
        .border_1()
        .border_color(ui::ink(0x14))
        .rounded(px(PANE_RADIUS))
        .shadow(pane_shadow())
        .overflow_hidden()
}

/// Build the glass-backed root element for a workspace.
pub fn root() -> Div {
    row()
        .relative()
        .size_full()
        .text_color(rgb(ui::theme::color(INK)))
        .text_size(px(ui::BODY))
        .font_family(ui::system_font())
        .child(
            material::glass("window-material")
                .radius(px(WINDOW_RADIUS))
                .absolute()
                .inset_0()
                .bg(rgba((ui::theme::get(6) << 8) | 0xa0)),
        )
        .child(wallpaper::layer())
}

/// Create a draggable titlebar region with native double-click behavior.
pub fn titlebar_drag(id: &'static str) -> Stateful<Div> {
    div()
        .id(id)
        .on_mouse_down(MouseButton::Left, |event, window, cx| {
            cx.stop_propagation();
            if event.click_count == 2 {
                window.titlebar_double_click();
            } else {
                window.start_window_move();
            }
        })
}

/// Lay out host-provided navigation, actions and settings in the sidebar.
pub fn sidebar(
    views: Div,
    new_view: AnyElement,
    notifications: Option<AnyElement>,
    settings: AnyElement,
) -> Div {
    col()
        .w(px(meep_ui::design::current().sidebar))
        .flex_shrink_0()
        .h_full()
        .px(px(ui::nav::INSET))
        .pt(px(ui::nav::TOP))
        .pb(px(ui::nav::INSET))
        .relative()
        .child(
            titlebar_drag("window-titlebar")
                .absolute()
                .top_0()
                .left(px(titlebar::TOGGLE_LEFT + titlebar::BUTTON))
                .right(px(
                    16. - (titlebar::BUTTON - titlebar::PLUS_INK) / 2. + titlebar::BUTTON
                ))
                .h(px(meep_ui::design::current().toolbar)),
        )
        .child(new_view)
        .child(views.id("view-list").flex_1().min_h_0().overflow_y_scroll())
        .child(
            col()
                .pt(px(8.))
                .gap(px(2.))
                .children(notifications)
                .child(settings),
        )
}

/// Build the Settings navigation button for a host click handler.
pub fn settings_button(cx: &App) -> Button {
    ui::nav::button("settings", false, cx)
        .accessibility_label("Settings")
        .tooltip(shortcuts::SETTINGS.hint("Settings"))
        .child(
            row()
                .w_full()
                .gap(px(8.))
                .child(ui::nav::glyph(Glyph::Settings2, false))
                .child(ui::nav::title("Settings")),
        )
}
/// Build a sidebar toggle with a label matching its current visibility.
pub fn sidebar_toggle(visible: bool) -> Button {
    titlebar::button(
        "toggle-sidebar",
        Glyph::PanelLeft,
        if visible {
            "Hide sidebar"
        } else {
            "Show sidebar"
        },
    )
    .absolute()
    .top(px(TRAFFIC_LIGHT_CENTER - titlebar::BUTTON / 2.))
    .left(px(titlebar::TOGGLE_LEFT))
    .tooltip(if visible {
        shortcuts::TOGGLE_SIDEBAR.hint("Hide sidebar")
    } else {
        shortcuts::TOGGLE_SIDEBAR.hint("Show sidebar")
    })
}

/// Lay out the workspace at the supplied sidebar reveal progress.
pub fn window_layout(sidebar_progress: f32) -> Div {
    row()
        .size_full()
        .relative()
        .pt(px((titlebar::band() - GUTTER) * (1. - sidebar_progress)))
}
/// Reserve the sidebar's visible width while it opens or closes.
pub fn sidebar_slot(progress: f32) -> Stateful<Div> {
    div()
        .id("sidebar-slot")
        .flex_shrink_0()
        .h_full()
        .w(px(meep_ui::design::current().sidebar * progress))
        .flex()
        .justify_end()
        .overflow_hidden()
        .mt(px(-(titlebar::band() - GUTTER) * (1. - progress)))
}
/// Compute the inspector width from the available space and optional host preference.
pub fn agent_panel_width(window_width: f32, sidebar: f32, preferred: Option<f32>) -> f32 {
    let default = (window_width * 0.36).clamp(320., meep_ui::design::current().agent_sidebar);
    preferred
        .unwrap_or(default)
        .clamp(300., (window_width - sidebar - 320.).clamp(300., 800.))
}
