pub use crate::component_traits::{Collapsible, Disableable, Selectable};
pub use crate::sizing::{Sizable, Size, StyleSized};
use gpui::{
    App, BoxShadow, Corners, Edges, Hsla, InteractiveElement as _, ParentElement, Pixels,
    StyleRefinement, Styled, Window, div, hsla, prelude::FluentBuilder as _, px,
};
pub use gpui_base::{FocusableExt, RoleOverride, StyledExt, box_shadow, h_flex, v_flex};

use crate::ActiveTheme as _;

const FOCUS_RING_WIDTH: Pixels = px(3.);
const FOCUS_RING_OPACITY: f32 = 0.5;
/// Gap between a borderless element's edge and a focus line drawn off it, in rem.
const FOCUS_LINE_GAP: f32 = 0.125;

/// Ink every layer of a surface's shadow carries — the `rgb(0 0 0 / 0.1)`
/// shadcn/ui spends at each elevation.
const SURFACE_SHADOW_INK: f32 = 0.1;

/// Ink of the hairline ring standing in for a popover's border.
///
/// shadcn/ui draws no border on a popup surface at all: its edge is a 1px
/// `rgb(0 0 0 / 0.1)` ring spent as a shadow layer. Because the ring is
/// translucent the shadow shows *through* it, which is what makes the edge read
/// as part of one grounded surface rather than as an outline with a separate
/// shadow below it. An opaque border cannot reproduce that — a border composites
/// over the element's own background, not over the shadow.
const POPOVER_RING_INK: f32 = 0.1;

/// The colour of a popup surface's hairline ring in this theme.
///
/// shadcn spends black on it in light mode and white in dark
/// (`oklch(1 0 0 / 10%)`), so it follows the foreground rather than the border
/// token: a fixed black ring would all but vanish on a dark surface.
///
pub(crate) fn popover_ring(cx: &App) -> Hsla {
    cx.theme().foreground.alpha(POPOVER_RING_INK)
}

/// shadcn/ui's popup surface shadow — a hairline `ring` plus `shadow-md` — at
/// `strength` of its full ink.
///
/// Callers animating a surface in pass a rising `strength`; a resting surface
/// passes `1.0`.
///
/// The two blurred layers use Tailwind's radii **halved**, which is the
/// conversion CSS requires and not a taste adjustment. CSS defines a box
/// shadow's blur radius as twice the gaussian's standard deviation, while GPUI's
/// shader takes the field as the deviation itself (`gaussian(y, sigma)`).
/// Copying Tailwind's `6px` and `4px` across therefore spreads the shadow over
/// twice the distance, which is why [`Styled::shadow_md`] reads as a wide grey
/// haze next to a browser's compact one.
///
/// Measured against shadcn's own render, this lands within a luminance step of
/// it the whole way down the falloff.
///
/// The ring is taken as a colour rather than read from the theme here so that an
/// animation can hold it across frames, where no `App` is in hand.
pub(crate) fn popover_shadow(ring: Hsla, strength: f32) -> Vec<BoxShadow> {
    let strength = strength.clamp(0., 1.);
    let ink = hsla(0., 0., 0., SURFACE_SHADOW_INK * strength);
    vec![
        // The ring, sitting in the 1px band outside the surface. No blur, so it
        // takes the shader's crisp path rather than the gaussian one.
        BoxShadow::new(px(0.), px(0.), ring.alpha(ring.a * strength))
            .blur_radius(px(0.))
            .spread_radius(px(1.)),
        BoxShadow::new(px(0.), px(4.), ink)
            .blur_radius(px(3.))
            .spread_radius(px(-1.)),
        BoxShadow::new(px(0.), px(2.), ink)
            .blur_radius(px(2.))
            .spread_radius(px(-2.)),
    ]
}

/// shadcn/ui's `shadow-lg`, the elevation it lifts a toast to, at `strength` of
/// its full ink.
///
/// A toast sits higher than a popover and is built differently: shadcn gives it
/// a real 1px border rather than the translucent ring it puts on a popup, so
/// there is no ring layer here. Its corner radius is left to the caller.
///
/// The radii are Tailwind's halved, for the reason [`popover_shadow`] explains.
pub(crate) fn toast_shadow(strength: f32) -> Vec<BoxShadow> {
    let ink = hsla(0., 0., 0., SURFACE_SHADOW_INK * strength.clamp(0., 1.));
    vec![
        BoxShadow::new(px(0.), px(10.), ink)
            .blur_radius(px(7.5))
            .spread_radius(px(-3.)),
        BoxShadow::new(px(0.), px(4.), ink)
            .blur_radius(px(3.))
            .spread_radius(px(-4.)),
    ]
}

/// shadcn/ui's `shadow-sm`, the elevation it spends on a control raised out of
/// the container it sits in — the active pill of a segmented tab bar — at full
/// ink.
///
/// Unlike a popover or a toast this surface is not floating over the page: it
/// sits *inside* a trough only a few pixels wider than itself, and that trough
/// clips. Both are reasons to keep the falloff tight — there is no room for a
/// wide one, and a wide one would read as grime against the trough wall rather
/// than as lift.
///
/// The radii are Tailwind's halved, for the reason [`popover_shadow`] explains:
/// CSS defines a box shadow's blur radius as twice the gaussian's standard
/// deviation, while GPUI's shader takes the field as the deviation itself
/// (`gaussian(y, sigma)`). Copying Tailwind's `3px` and `2px` across therefore
/// spreads the shadow over twice the distance, which is why
/// [`Styled::shadow_sm`] leaves a haze around a 24px pill where shadcn draws a
/// compact line.
pub(crate) fn raised_shadow() -> Vec<BoxShadow> {
    let ink = hsla(0., 0., 0., SURFACE_SHADOW_INK);
    vec![
        BoxShadow::new(px(0.), px(1.), ink).blur_radius(px(1.5)),
        BoxShadow::new(px(0.), px(1.), ink)
            .blur_radius(px(1.))
            .spread_radius(px(-1.)),
    ]
}

/// Finished styles that read the theme.
///
/// Separate from [`StyledExt`], which holds neutral helpers that make no
/// visual decisions. Everything here does: it reaches into the theme and
/// produces a specific look, which is why it belongs above the base layer.
pub trait ThemeStyled: Styled + Sized {
    /// Give this element the focus appearance the framework's own controls
    /// use: its border tinted with the focus colour, and the ring outside it.
    ///
    /// The ring is dropped when [`crate::Theme::focus_ring`] is off, leaving
    /// the tinted border — an application whose layout clips its containers can
    /// turn it off rather than finding room for the ring in each of them. An
    /// element without a border draws a 1px line on its edge instead, so
    /// borderless controls still show focus.
    ///
    /// Calling this turns the ring on; gate it with `when` for the conditions
    /// that decide whether the control shows one at all — its focus state,
    /// [`FocusableExt::focus_ring`], appearance, and so on.
    ///
    /// The ring sits outside the element's border, so an ancestor that clips
    /// its content will cut it off — leave it a few pixels of room, or don't
    /// clip.
    fn focus_ring_style(self, window: &Window, cx: &App) -> Self
    where
        Self: ParentElement;

    /// Give this element the surface, edge, shadow and radius of a popover.
    ///
    /// This is the one surface every popup shares — Popover, PopupMenu, Select,
    /// Combobox, DatePicker and the editor's hover popovers — so they cannot
    /// drift apart. See [`popover_shadow`] for what the shadow is modelled on.
    fn popover_style(self, cx: &App) -> Self;

    /// Round this element as far as its size allows — a circle if it is square,
    /// a pill if it is not — unless the theme squares its corners.
    ///
    /// Use this instead of [`gpui::Styled::rounded_full`] on anything the theme
    /// owns. A hardcoded `rounded_full` survives [`crate::Theme::radius`] being
    /// set to zero, which leaves avatars, badge dots and slider thumbs round in
    /// a UI that is square everywhere else. See [`crate::Theme::radius_full`].
    fn rounded_full_style(self, cx: &App) -> Self {
        self.rounded(cx.theme().radius_full())
    }
}

impl<T: Styled + Sized> ThemeStyled for T {
    /// Draw the focus ring the framework's own controls use.
    ///
    /// Calling this turns the ring on; gate it with `when` for the conditions
    /// that decide whether the control shows one at all — its focus state,
    /// [`crate::FocusableExt::focus_ring`], appearance, and so on.
    ///
    /// The ring sits outside the element's border, so an ancestor that clips
    /// its content will cut it off — leave it a few pixels of room, or don't
    /// clip.
    fn focus_ring_style(self, window: &Window, cx: &App) -> Self
    where
        Self: ParentElement,
    {
        focus_style(self, FocusLine::Edge, window, cx)
    }

    fn popover_style(self, cx: &App) -> Self {
        let theme = cx.theme();
        // No border: the edge is the ring inside `popover_shadow`, which is how
        // shadcn draws it and the only way the shadow can show through it.
        self.bg(theme.popover)
            .text_color(theme.popover_foreground)
            .shadow(popover_shadow(popover_ring(cx), 1.))
            .rounded(theme.radius)
    }
}

fn border_widths(style: &StyleRefinement, rem_size: Pixels) -> Edges<Pixels> {
    let width = |value: Option<gpui::AbsoluteLength>| {
        value.map(|v| v.to_pixels(rem_size)).unwrap_or_default()
    };
    let widths = &style.border_widths;
    Edges {
        top: width(widths.top),
        bottom: width(widths.bottom),
        left: width(widths.left),
        right: width(widths.right),
    }
}

fn corner_radii(style: &StyleRefinement, rem_size: Pixels) -> Corners<Pixels> {
    let radius = |value: Option<gpui::AbsoluteLength>| {
        value.map(|v| v.to_pixels(rem_size)).unwrap_or_default()
    };
    let radii = &style.corner_radii;
    Corners {
        top_left: radius(radii.top_left),
        top_right: radius(radii.top_right),
        bottom_left: radius(radii.bottom_left),
        bottom_right: radius(radii.bottom_right),
    }
}

fn corner_radii_refinement(radius: Corners<Pixels>) -> StyleRefinement {
    let mut style = StyleRefinement::default();
    style.corner_radii.top_left = Some(radius.top_left.into());
    style.corner_radii.top_right = Some(radius.top_right.into());
    style.corner_radii.bottom_left = Some(radius.bottom_left.into());
    style.corner_radii.bottom_right = Some(radius.bottom_right.into());
    style
}

/// Where a borderless element draws its 1px focus line when
/// [`crate::Theme::focus_ring`] is off.
#[derive(Clone, Copy)]
pub(crate) enum FocusLine {
    /// On the element's edge, in the `ring` colour. For elements whose
    /// content sits clear of the edge and that have no fill of their own.
    Edge,
    /// Inset from the edge, in the given colour. For filled elements, where
    /// the `ring` colour can land close to the fill; pass a colour that
    /// contrasts with it, such as the element's foreground.
    Inside(Hsla),
    /// Just outside the edge, in the `ring` colour. For elements with no
    /// padding, where a line on the edge would touch their text.
    Outside,
}

/// Style a focused element as [`ThemeStyled::focus_ring_style`] does, with
/// `line` choosing where a borderless element draws its focus line.
pub(crate) fn focus_style<T: Styled + ParentElement>(
    mut element: T,
    line: FocusLine,
    window: &Window,
    cx: &App,
) -> T {
    let theme = cx.theme();
    if theme.focus_ring {
        return focus_ring(
            element.border_color(theme.ring),
            window,
            theme.ring.alpha(FOCUS_RING_OPACITY),
        );
    }

    // The ring is painted outside the border, so a clipping ancestor cuts it
    // off. An application whose layout clips heavily turns it off in the theme
    // and keeps the tinted border, which takes no space.
    let rem_size = window.rem_size();
    if border_widths(element.style(), rem_size).any(|width| *width > Pixels::ZERO) {
        return element.border_color(theme.ring);
    }

    let gap = rem_size * FOCUS_LINE_GAP;
    let (color, inset) = match line {
        FocusLine::Edge => (theme.ring, Pixels::ZERO),
        FocusLine::Inside(color) => (color, gap),
        FocusLine::Outside => (theme.ring, -gap),
    };
    // Shrinking or growing the box by `inset` keeps the line concentric with
    // the element's own corners.
    let radius =
        corner_radii(element.style(), rem_size).map(|value| (*value - inset).max(Pixels::ZERO));
    element.child(
        div()
            .when(cfg!(test), |this| {
                this.debug_selector(|| "focus-ring".into())
            })
            .flex_none()
            .absolute()
            .top(inset)
            .left(inset)
            .right(inset)
            .bottom(inset)
            .border_1()
            .border_color(color)
            .refine_style(&corner_radii_refinement(radius)),
    )
}

/// Paint only the outside band, preserving translucent control backgrounds.
pub(crate) fn focus_ring<T: Styled + ParentElement>(
    mut element: T,
    window: &Window,
    color: Hsla,
) -> T {
    let rem_size = window.rem_size();
    let border_widths = border_widths(element.style(), rem_size);
    let radius = corner_radii(element.style(), rem_size).map(|value| *value + FOCUS_RING_WIDTH);
    let ring_style = corner_radii_refinement(radius);
    let inset = FOCUS_RING_WIDTH;

    element.child(
        div()
            .when(cfg!(test), |this| {
                this.debug_selector(|| "focus-ring".into())
            })
            .flex_none()
            .absolute()
            .top(-(inset + border_widths.top))
            .left(-(inset + border_widths.left))
            .right(-(inset + border_widths.right))
            .bottom(-(inset + border_widths.bottom))
            .border(FOCUS_RING_WIDTH)
            .border_color(color)
            .refine_style(&ring_style),
    )
}
