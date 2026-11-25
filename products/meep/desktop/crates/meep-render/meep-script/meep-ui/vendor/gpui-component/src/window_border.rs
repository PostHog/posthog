// From:
// https://github.com/zed-industries/zed/blob/56daba28d40301ee4c05546fadb691d070b7b2b6/crates/gpui/examples/window_shadow.rs
use gpui::{
    AnyElement, App, CursorStyle, Decorations, Edges, Hsla, InteractiveElement as _, IntoElement,
    MouseButton, ParentElement, Pixels, Point, RenderOnce, ResizeEdge, Size, Styled as _, Tiling,
    Window, div, point, prelude::FluentBuilder as _, px,
};

use crate::ActiveTheme;

#[cfg(not(target_os = "linux"))]
pub(crate) const SHADOW_SIZE: Pixels = px(0.0);
#[cfg(target_os = "linux")]
pub(crate) const SHADOW_SIZE: Pixels = px(20.0);
const BORDER_SIZE: Pixels = px(1.0);
/// Half-width of the resize hit band on each side of the visible frame (inner border).
const RESIZE_HIT_SIZE: Pixels = px(4.0);
///
/// GPUI currently clips overflowing children to a rectangular content mask. A non-zero
/// radius here would round the frame itself but leave child backgrounds visible in the
/// corners, so keep the generic window wrapper square until rounded content masks exist.
pub(crate) const BORDER_RADIUS: Pixels = px(0.0);

/// Create a new window border.
pub fn window_border() -> WindowBorder {
    WindowBorder::new()
}

/// Renders a custom window border and shadow on Linux.
#[derive(IntoElement)]
pub struct WindowBorder {
    shadow_size: Pixels,
    resize_hit_size: Pixels,
    children: Vec<AnyElement>,
}

impl Default for WindowBorder {
    fn default() -> Self {
        Self {
            shadow_size: SHADOW_SIZE,
            resize_hit_size: RESIZE_HIT_SIZE,
            children: Vec::new(),
        }
    }
}

impl WindowBorder {
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the shadow size for typical Linux client-side decorations.
    ///
    /// Default: [`SHADOW_SIZE`]
    pub fn shadow_size(mut self, size: impl Into<Pixels>) -> Self {
        self.shadow_size = size.into();
        self
    }

    /// Set the resize hit band half-width around the visible inner frame edge.
    ///
    /// Default: [`RESIZE_HIT_SIZE`]
    pub fn resize_hit_size(mut self, size: impl Into<Pixels>) -> Self {
        self.resize_hit_size = size.into();
        self
    }
}

/// Per-side inset of the visible frame from the outer window bounds.
fn client_frame_insets(shadow_size: Pixels, tiling: &Tiling) -> Edges<Pixels> {
    let mut insets = Edges::all(shadow_size);
    if tiling.top {
        insets.top = px(0.0);
    }
    if tiling.bottom {
        insets.bottom = px(0.0);
    }
    if tiling.left {
        insets.left = px(0.0);
    }
    if tiling.right {
        insets.right = px(0.0);
    }
    insets
}

/// Get the window paddings.
pub fn window_paddings(window: &Window) -> Edges<Pixels> {
    let shadow_size = window.client_inset().unwrap_or(SHADOW_SIZE);
    match window.window_decorations() {
        Decorations::Server => Edges::all(px(0.0)),
        Decorations::Client { tiling } => client_frame_insets(shadow_size, &tiling),
    }
}

/// Per-side inset from the window bounds to the visible frame's content area.
///
/// This is [`window_paddings`] plus the frame's own border, which the window
/// wrapper draws on every side it is not tiled against. Allows to lay an element
/// flush against the inside of the window frame.
pub(crate) fn window_content_insets(window: &Window) -> Edges<Pixels> {
    let shadow_size = window.client_inset().unwrap_or(SHADOW_SIZE);
    match window.window_decorations() {
        Decorations::Server => Edges::all(px(0.0)),
        Decorations::Client { tiling } => {
            let mut insets = client_frame_insets(shadow_size, &tiling);
            if !tiling.top {
                insets.top += BORDER_SIZE;
            }
            if !tiling.bottom {
                insets.bottom += BORDER_SIZE;
            }
            if !tiling.left {
                insets.left += BORDER_SIZE;
            }
            if !tiling.right {
                insets.right += BORDER_SIZE;
            }
            insets
        }
    }
}

/// Per-side inset from the window bounds to the part of the window that is
/// fully visible: not under the system bars, a display cutout or the on-screen
/// keyboard ([`Window::fully_visible_bounds`]). Zero on desktop.
pub(crate) fn window_safe_insets(window: &Window) -> Edges<Pixels> {
    let viewport = window.viewport_size();
    let visible = window.fully_visible_bounds();
    Edges {
        top: visible.top(),
        right: viewport.width - visible.right(),
        bottom: viewport.height - visible.bottom(),
        left: visible.left(),
    }
}

impl ParentElement for WindowBorder {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for WindowBorder {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let decorations = window.window_decorations();
        let mut children = self.children;
        if !uses_client_border(decorations) {
            return match children.len() {
                1 => children.pop().unwrap(),
                _ => div().size_full().children(children).into_any_element(),
            };
        }
        let Decorations::Client { tiling } = decorations else {
            unreachable!("client border requires client decorations");
        };

        // Keep the platform client inset stable. When the window is tiled on all sides we stop drawing
        // shadow padding, but `set_client_inset` must still use the full shadow size. Clearing it
        // makes the first resize after restore double-count the shadow in `compute_outer_size`, and
        // the window jumps larger.
        let platform_inset = self.shadow_size;
        let visual_shadow = if tiling.top && tiling.bottom && tiling.left && tiling.right {
            px(0.0)
        } else {
            self.shadow_size
        };
        let resize_hit_size = self.resize_hit_size;
        window.set_client_inset(platform_inset);
        let window_size = window.window_bounds().get_bounds().size;
        let is_window_active = window.is_window_active();
        let border_color = if cx.theme().is_dark() {
            Hsla {
                h: 0.,
                s: 0.,
                l: 0.2,
                a: 1.0,
            }
        } else {
            Hsla {
                h: 0.,
                s: 0.,
                l: 0.8,
                a: 1.0,
            }
        };

        div()
            .id("window-backdrop")
            .bg(gpui::transparent_black())
            .flex()
            .flex_col()
            .overflow_hidden()
            .when(!(tiling.top || tiling.right), |div| {
                div.rounded_tr(BORDER_RADIUS)
            })
            .when(!(tiling.top || tiling.left), |div| {
                div.rounded_tl(BORDER_RADIUS)
            })
            .when(!tiling.top, |div| div.pt(visual_shadow))
            .when(!tiling.bottom, |div| div.pb(visual_shadow))
            .when(!tiling.left, |div| div.pl(visual_shadow))
            .when(!tiling.right, |div| div.pr(visual_shadow))
            .on_mouse_down(MouseButton::Left, move |_, window, _| {
                let Decorations::Client { tiling } = window.window_decorations() else {
                    return;
                };
                if !window.is_resizable() {
                    return;
                }
                if tiling.top && tiling.bottom && tiling.left && tiling.right {
                    return;
                }
                let size = window.window_bounds().get_bounds().size;
                let pos = window.mouse_position();
                let insets = client_frame_insets(platform_inset, &tiling);

                match resize_edge(pos, size, insets, &tiling, resize_hit_size) {
                    Some(edge) => window.start_window_resize(edge),
                    None => {}
                };
            })
            .size_full()
            .child(
                div()
                    .cursor(CursorStyle::default())
                    .flex_1()
                    .min_h_0()
                    .min_w_0()
                    .overflow_hidden()
                    .when(!(tiling.top || tiling.right), |div| {
                        div.rounded_tr(BORDER_RADIUS)
                    })
                    .when(!(tiling.top || tiling.left), |div| {
                        div.rounded_tl(BORDER_RADIUS)
                    })
                    .border_color(border_color)
                    .when(!tiling.top, |div| div.border_t(BORDER_SIZE))
                    .when(!tiling.bottom, |div| div.border_b(BORDER_SIZE))
                    .when(!tiling.left, |div| div.border_l(BORDER_SIZE))
                    .when(!tiling.right, |div| div.border_r(BORDER_SIZE))
                    .when(!tiling.is_tiled(), |div| {
                        let opacity = if is_window_active { 1.0 } else { 0.7 };
                        div.shadow(vec![
                            // Keep the effective outer reach below SHADOW_SIZE. GPUI
                            // does not grow the paint bounds for blur, so a larger blur
                            // or offset would be visibly cut off by the window surface.
                            gpui::BoxShadow {
                                color: Hsla {
                                    h: 0.,
                                    s: 0.,
                                    l: 0.,
                                    a: 0.18 * opacity,
                                },
                                // GNOME-style ambient shadow: horizontally centered
                                // with only a slight downward bias.
                                blur_radius: px(10.),
                                spread_radius: px(-1.),
                                offset: point(px(0.0), px(2.0)),
                                inset: false,
                            },
                            // The contact layer adds definition without increasing the
                            // space between the content and the outer window bounds.
                            gpui::BoxShadow {
                                color: Hsla {
                                    h: 0.,
                                    s: 0.,
                                    l: 0.,
                                    a: 0.18 * opacity,
                                },
                                blur_radius: px(3.),
                                spread_radius: px(0.),
                                offset: point(px(0.0), px(1.0)),
                                inset: false,
                            },
                        ])
                    })
                    .on_mouse_move(|_e, _, cx| {
                        cx.stop_propagation();
                    })
                    .bg(gpui::transparent_black())
                    .children(children),
            )
            .when(window.is_resizable(), |parent| {
                parent.child(div().absolute().size_full().children(resize_hit_zones(
                    window_size,
                    platform_inset,
                    resize_hit_size,
                    &tiling,
                )))
            })
            .into_any_element()
    }
}

fn uses_client_border(decorations: Decorations) -> bool {
    matches!(decorations, Decorations::Client { .. })
}

fn cursor_style_for_resize_edge(edge: ResizeEdge) -> CursorStyle {
    match edge {
        ResizeEdge::Top | ResizeEdge::Bottom => CursorStyle::ResizeUpDown,
        ResizeEdge::Left | ResizeEdge::Right => CursorStyle::ResizeLeftRight,
        ResizeEdge::TopLeft | ResizeEdge::BottomRight => CursorStyle::ResizeUpLeftDownRight,
        ResizeEdge::TopRight | ResizeEdge::BottomLeft => CursorStyle::ResizeUpRightDownLeft,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_client_decorated_windows_use_the_client_border() {
        assert!(!uses_client_border(Decorations::Server));
        assert!(uses_client_border(Decorations::Client {
            tiling: Tiling::default(),
        }));
    }
}

/// Cursor-only overlay for each resize edge/corner. Resize starts from the backdrop
/// `on_mouse_down` via [`resize_edge`]. `.cursor()` updates immediately on hitbox changes
/// without `window.refresh()` (PR #617).
fn resize_hit_zones(
    window_size: Size<Pixels>,
    shadow_size: Pixels,
    hit_size: Pixels,
    tiling: &Tiling,
) -> Vec<AnyElement> {
    if tiling.top && tiling.bottom && tiling.left && tiling.right {
        return Vec::new();
    }

    let insets = client_frame_insets(shadow_size, tiling);
    let inner_left = insets.left;
    let inner_right = window_size.width - insets.right;
    let inner_top = insets.top;
    let inner_bottom = window_size.height - insets.bottom;
    // Overlay is laid out in the padded content box; convert from window coords.
    let frame_origin = point(insets.left, insets.top);
    let band = hit_size + hit_size;
    let span_x = inner_right - inner_left + band;
    let span_y = inner_bottom - inner_top + band;

    let mut zones: Vec<AnyElement> = Vec::new();

    let mut push_zone = |edge: ResizeEdge, origin: Point<Pixels>, zone_size: Size<Pixels>| {
        let origin = origin - frame_origin;
        zones.push(
            div()
                .absolute()
                .left(origin.x)
                .top(origin.y)
                .w(zone_size.width)
                .h(zone_size.height)
                .cursor(cursor_style_for_resize_edge(edge))
                .into_any_element(),
        );
    };

    if !tiling.top {
        push_zone(
            ResizeEdge::Top,
            point(inner_left - hit_size, inner_top - hit_size),
            Size::new(span_x, band),
        );
    }
    if !tiling.bottom {
        push_zone(
            ResizeEdge::Bottom,
            point(inner_left - hit_size, inner_bottom - hit_size),
            Size::new(span_x, band),
        );
    }
    if !tiling.left {
        push_zone(
            ResizeEdge::Left,
            point(inner_left - hit_size, inner_top - hit_size),
            Size::new(band, span_y),
        );
    }
    if !tiling.right {
        push_zone(
            ResizeEdge::Right,
            point(inner_right - hit_size, inner_top - hit_size),
            Size::new(band, span_y),
        );
    }

    // Corners are pushed after edge strips so hit-testing prefers them over adjacent edges.
    if !tiling.top && !tiling.left {
        push_zone(
            ResizeEdge::TopLeft,
            point(inner_left - hit_size, inner_top - hit_size),
            Size::new(band, band),
        );
    }
    if !tiling.top && !tiling.right {
        push_zone(
            ResizeEdge::TopRight,
            point(inner_right - hit_size, inner_top - hit_size),
            Size::new(band, band),
        );
    }
    if !tiling.bottom && !tiling.left {
        push_zone(
            ResizeEdge::BottomLeft,
            point(inner_left - hit_size, inner_bottom - hit_size),
            Size::new(band, band),
        );
    }
    if !tiling.bottom && !tiling.right {
        push_zone(
            ResizeEdge::BottomRight,
            point(inner_right - hit_size, inner_bottom - hit_size),
            Size::new(band, band),
        );
    }

    zones
}

/// Hit-test resize edges on a narrow band around the visible inner frame, not the full shadow padding.
fn resize_edge(
    pos: Point<Pixels>,
    size: Size<Pixels>,
    insets: Edges<Pixels>,
    tiling: &Tiling,
    hit_size: Pixels,
) -> Option<ResizeEdge> {
    let inner_left = insets.left;
    let inner_right = size.width - insets.right;
    let inner_top = insets.top;
    let inner_bottom = size.height - insets.bottom;

    // Each edge only applies along its corresponding inner-frame segment; it does not extend along the "extension lines" of the shadow padding.
    let on_left = pos.x >= inner_left - hit_size
        && pos.x <= inner_left + hit_size
        && pos.y >= inner_top - hit_size
        && pos.y <= inner_bottom + hit_size;
    let on_right = pos.x >= inner_right - hit_size
        && pos.x <= inner_right + hit_size
        && pos.y >= inner_top - hit_size
        && pos.y <= inner_bottom + hit_size;
    let on_top = pos.y >= inner_top - hit_size
        && pos.y <= inner_top + hit_size
        && pos.x >= inner_left - hit_size
        && pos.x <= inner_right + hit_size;
    let on_bottom = pos.y >= inner_bottom - hit_size
        && pos.y <= inner_bottom + hit_size
        && pos.x >= inner_left - hit_size
        && pos.x <= inner_right + hit_size;

    if !tiling.top && !tiling.left && on_top && on_left {
        return Some(ResizeEdge::TopLeft);
    }
    if !tiling.top && !tiling.right && on_top && on_right {
        return Some(ResizeEdge::TopRight);
    }
    if !tiling.bottom && !tiling.left && on_bottom && on_left {
        return Some(ResizeEdge::BottomLeft);
    }
    if !tiling.bottom && !tiling.right && on_bottom && on_right {
        return Some(ResizeEdge::BottomRight);
    }
    if !tiling.top && on_top {
        return Some(ResizeEdge::Top);
    }
    if !tiling.bottom && on_bottom {
        return Some(ResizeEdge::Bottom);
    }
    if !tiling.left && on_left {
        return Some(ResizeEdge::Left);
    }
    if !tiling.right && on_right {
        return Some(ResizeEdge::Right);
    }
    None
}
