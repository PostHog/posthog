use gpui::{
    Animation, AnimationExt as _, App, Bounds, ContentMask, Element, ElementId, GlobalElementId,
    Hsla, InspectorElementId, IntoElement, LayoutId, LineLayout, ParentElement as _, Pixels, Point,
    RenderOnce, SharedString, StyleRefinement, Styled, StyledText, TextAlign, Window, WrapBoundary,
    div, point, px, size,
};
use instant::Duration;

use crate::{ActiveTheme as _, Colorize as _, StyledExt as _};

const SHIMMER_LAYER_COUNT: usize = 12;
const DEFAULT_SHIMMER_SPREAD: f32 = 0.3;
/// Lightness difference below which a highlight would be indistinguishable from the text.
const MIN_HIGHLIGHT_LIGHTNESS_GAP: f32 = 0.1;

/// The shimmer highlight half-width.
///
/// A relative spread follows the text width, keeping short and long labels
/// proportionally lit. An absolute spread keeps the band the same physical
/// width across labels, the way a fixed gradient would.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum ShimmerSpread {
    /// Half-width as a fraction of the text width.
    Relative(f32),
    /// Half-width as a fixed length.
    Absolute(Pixels),
}

impl Default for ShimmerSpread {
    fn default() -> Self {
        Self::Relative(DEFAULT_SHIMMER_SPREAD)
    }
}

impl From<f32> for ShimmerSpread {
    fn from(fraction: f32) -> Self {
        Self::Relative(fraction)
    }
}

impl From<Pixels> for ShimmerSpread {
    fn from(length: Pixels) -> Self {
        Self::Absolute(length)
    }
}

/// The appearance and timing of a reusable text shimmer.
///
/// By default, the highlight's half-width spans 30% of the text width and
/// completes one left-to-right sweep every two seconds. Its color follows the
/// current text color and active theme.
#[derive(Clone, Copy, Debug)]
pub struct ShimmerStyle {
    duration: Duration,
    highlight_color: Option<Hsla>,
    spread: ShimmerSpread,
    reverse: bool,
    once: bool,
}

impl ShimmerStyle {
    /// Create a theme-aware shimmer with the default timing and spread.
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the duration of one complete sweep.
    ///
    /// A zero duration is clamped to one millisecond.
    pub fn duration(mut self, duration: Duration) -> Self {
        self.duration = duration.max(Duration::from_millis(1));
        self
    }

    /// Replace the theme-aware highlight with an explicit color.
    pub fn highlight_color(mut self, color: impl Into<Hsla>) -> Self {
        self.highlight_color = Some(color.into());
        self
    }

    /// Set the highlight half-width.
    ///
    /// An `f32` is a fraction of the text width; finite values are clamped to
    /// the inclusive `0.05..=1.0` range and the default is `0.3`. A [`Pixels`]
    /// value is an absolute half-width with a one-pixel minimum. Non-finite
    /// values leave the existing spread unchanged.
    pub fn spread(mut self, spread: impl Into<ShimmerSpread>) -> Self {
        match spread.into() {
            ShimmerSpread::Relative(fraction) if fraction.is_finite() => {
                self.spread = ShimmerSpread::Relative(fraction.clamp(0.05, 1.));
            }
            ShimmerSpread::Absolute(length) if length.as_f32().is_finite() => {
                self.spread = ShimmerSpread::Absolute(length.max(px(1.)));
            }
            _ => {}
        }
        self
    }

    /// Set whether the highlight should move from right to left.
    pub fn reverse(mut self, reverse: bool) -> Self {
        self.reverse = reverse;
        self
    }

    /// Set whether the highlight should complete one sweep instead of looping.
    pub fn once(mut self, once: bool) -> Self {
        self.once = once;
        self
    }

    pub(crate) fn animation(self) -> Animation {
        loading_animation(self.duration, self.once)
    }
}

impl Default for ShimmerStyle {
    fn default() -> Self {
        Self {
            duration: Duration::from_secs(2),
            highlight_color: None,
            spread: ShimmerSpread::default(),
            reverse: false,
            once: false,
        }
    }
}

/// Text with a smooth, theme-aware loading highlight.
///
/// Font, color, weight, wrapping, and truncation are inherited from the parent
/// unless overridden through [`Styled`]. When the system requests reduced
/// motion, the text stays visible without requesting animation frames.
///
/// ```ignore
/// ShimmerText::new("Thinking…")
///     .duration(Duration::from_secs(3))
///     .spread(0.4)
/// ```
#[derive(IntoElement)]
pub struct ShimmerText {
    text: SharedString,
    style: StyleRefinement,
    shimmer_style: ShimmerStyle,
    id: Option<ElementId>,
}

impl ShimmerText {
    /// Create animated text with the default theme-aware shimmer.
    pub fn new(text: impl Into<SharedString>) -> Self {
        Self {
            text: text.into(),
            style: StyleRefinement::default(),
            shimmer_style: ShimmerStyle::default(),
            id: None,
        }
    }

    /// Set an explicit animation identity when sibling labels are identical.
    pub fn id(mut self, id: impl Into<ElementId>) -> Self {
        self.id = Some(id.into());
        self
    }

    /// Apply a reusable shimmer appearance and timing configuration.
    pub fn with_shimmer_style(mut self, style: ShimmerStyle) -> Self {
        self.shimmer_style = style;
        self
    }

    /// Set the duration of one complete sweep.
    pub fn duration(mut self, duration: Duration) -> Self {
        self.shimmer_style = self.shimmer_style.duration(duration);
        self
    }

    /// Replace the theme-aware highlight with an explicit color.
    pub fn highlight_color(mut self, color: impl Into<Hsla>) -> Self {
        self.shimmer_style = self.shimmer_style.highlight_color(color);
        self
    }

    /// Set the relative or absolute highlight half-width; the default is `0.3`.
    pub fn spread(mut self, spread: impl Into<ShimmerSpread>) -> Self {
        self.shimmer_style = self.shimmer_style.spread(spread);
        self
    }

    /// Set whether the highlight should move from right to left.
    pub fn reverse(mut self, reverse: bool) -> Self {
        self.shimmer_style = self.shimmer_style.reverse(reverse);
        self
    }

    /// Set whether the highlight should complete one sweep instead of looping.
    pub fn once(mut self, once: bool) -> Self {
        self.shimmer_style = self.shimmer_style.once(once);
        self
    }
}

impl Styled for ShimmerText {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for ShimmerText {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let id = self.id.unwrap_or_else(|| self.text.clone().into());
        let container = div().min_w_0().refine_style(&self.style);

        if cx.reduce_motion() {
            return container
                .child(StyledText::new(self.text))
                .into_any_element();
        }

        let tokens = cx.theme().semantic_tokens();
        let reverse = self.shimmer_style.reverse;
        let shimmer = ShimmerGlyphs {
            text: StyledText::new(self.text),
            highlight_color: self.shimmer_style.highlight_color,
            background: tokens.colors.background,
            foreground: tokens.colors.foreground,
            dark: cx.theme().is_dark(),
            spread: self.shimmer_style.spread,
            phase: 0.,
        }
        .with_animation(
            id,
            self.shimmer_style.animation(),
            move |mut this, phase| {
                this.phase = if reverse { 1. - phase } else { phase };
                this
            },
        );

        container.child(shimmer).into_any_element()
    }
}

/// Paint an animated highlight over glyphs already laid out by `StyledText`.
///
/// Keeping `StyledText` as the layout owner preserves wrapping, truncation,
/// inherited typography, and GPUI's glyph cache. Nested content masks produce
/// a soft continuous band without rebuilding text runs on every frame.
struct ShimmerGlyphs {
    text: StyledText,
    highlight_color: Option<Hsla>,
    background: Hsla,
    foreground: Hsla,
    dark: bool,
    spread: ShimmerSpread,
    phase: f32,
}

impl ShimmerGlyphs {
    fn paint_highlight(&self, bounds: Bounds<Pixels>, window: &mut Window, cx: &mut App) {
        let masks = std::array::from_fn::<_, SHIMMER_LAYER_COUNT, _>(|layer| {
            shimmer_band_bounds(bounds, self.phase, self.spread, layer)
                .map(|bounds| ContentMask { bounds })
        });

        if masks.iter().all(Option::is_none) {
            return;
        }

        let color = shimmer_highlight_color(
            window.text_style().color,
            self.background,
            self.foreground,
            self.dark,
            self.highlight_color,
        );
        let layout = self.text.layout();
        let line_height = layout.line_height();
        let text_align = window.text_style().text_align;
        let mut line_origin = bounds.origin;

        window.paint_layer(bounds, |window| {
            for wrapped_line in layout.line_layouts() {
                let line = &wrapped_line.unwrapped_layout;
                let baseline_offset = point(
                    px(0.),
                    (line_height - line.ascent - line.descent) / 2. + line.ascent,
                );
                let mut wraps = wrapped_line.wrap_boundaries.iter().peekable();
                let mut glyph_origin = point(
                    shimmer_aligned_origin_x(
                        line_origin,
                        bounds.size.width,
                        px(0.),
                        text_align,
                        line,
                        wraps.peek().copied(),
                    ),
                    line_origin.y,
                );
                let mut previous_glyph_position = Point::default();

                for (run_index, run) in line.runs.iter().enumerate() {
                    let glyph_size = cx
                        .text_system()
                        .bounding_box(run.font_id, line.font_size)
                        .size;

                    for (glyph_index, glyph) in run.glyphs.iter().enumerate() {
                        glyph_origin.x += glyph.position.x - previous_glyph_position.x;

                        if wraps.peek().is_some_and(|wrap| {
                            wrap.run_ix == run_index && wrap.glyph_ix == glyph_index
                        }) {
                            wraps.next();
                            glyph_origin.x = shimmer_aligned_origin_x(
                                line_origin,
                                bounds.size.width,
                                glyph.position.x,
                                text_align,
                                line,
                                wraps.peek().copied(),
                            );
                            glyph_origin.y += line_height;
                        }

                        previous_glyph_position = glyph.position;

                        if glyph.is_emoji {
                            continue;
                        }

                        let glyph_bounds = Bounds::new(glyph_origin, glyph_size);
                        let paint_origin =
                            glyph_origin + baseline_offset + point(px(0.), glyph.position.y);

                        for mask in masks.iter().flatten() {
                            if !glyph_bounds.intersects(&mask.bounds) {
                                continue;
                            }

                            window.with_content_mask(Some(*mask), |window| {
                                let _ = window.paint_glyph(
                                    paint_origin,
                                    run.font_id,
                                    glyph.id,
                                    line.font_size,
                                    color,
                                );
                            });
                        }
                    }
                }

                line_origin.y += wrapped_line.size(line_height).height;
            }
        });
    }
}

impl IntoElement for ShimmerGlyphs {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

impl Element for ShimmerGlyphs {
    type RequestLayoutState = ();
    type PrepaintState = ();

    fn id(&self) -> Option<ElementId> {
        None
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        global_id: Option<&GlobalElementId>,
        inspector_id: Option<&InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, Self::RequestLayoutState) {
        self.text
            .request_layout(global_id, inspector_id, window, cx)
    }

    fn prepaint(
        &mut self,
        global_id: Option<&GlobalElementId>,
        inspector_id: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        layout: &mut Self::RequestLayoutState,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::PrepaintState {
        self.text
            .prepaint(global_id, inspector_id, bounds, layout, window, cx);
    }

    fn paint(
        &mut self,
        global_id: Option<&GlobalElementId>,
        inspector_id: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        layout: &mut Self::RequestLayoutState,
        prepaint: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App,
    ) {
        self.text.paint(
            global_id,
            inspector_id,
            bounds,
            layout,
            prepaint,
            window,
            cx,
        );
        self.paint_highlight(bounds, window, cx);
    }
}

pub(crate) fn loading_animation(duration: Duration, once: bool) -> Animation {
    if once {
        Animation::new(duration)
    } else {
        Animation::new(duration).repeat_synced()
    }
}

fn shimmer_highlight_color(
    text: Hsla,
    background: Hsla,
    foreground: Hsla,
    dark: bool,
    override_color: Option<Hsla>,
) -> Hsla {
    let highlight = override_color.unwrap_or_else(|| {
        let (target, opposite) = if dark {
            (foreground, background)
        } else {
            (background, foreground)
        };
        // Text already in the target's lightness (e.g. `foreground` text in a dark
        // theme) would get a band in its own color; sweep toward the other end.
        let target = if (target.l - text.l).abs() < MIN_HIGHLIGHT_LIGHTNESS_GAP {
            opposite
        } else {
            target
        };
        text.mix_oklab(target, 0.2)
    });
    let peak_opacity: f32 = if dark { 0.6 } else { 0.75 };
    let layer_opacity = 1. - (1. - peak_opacity).powf(1. / SHIMMER_LAYER_COUNT as f32);

    highlight.opacity(layer_opacity)
}

fn shimmer_band_bounds(
    bounds: Bounds<Pixels>,
    phase: f32,
    spread: ShimmerSpread,
    layer: usize,
) -> Option<Bounds<Pixels>> {
    let width = bounds.size.width.as_f32();

    if width <= 0. || bounds.size.height <= px(0.) || layer >= SHIMMER_LAYER_COUNT {
        return None;
    }

    let half_width = match spread {
        ShimmerSpread::Relative(fraction) => width * fraction,
        ShimmerSpread::Absolute(length) => length.as_f32(),
    };
    let padding = half_width / width + 0.05;
    let center = phase.mul_add(1. + padding * 2., -padding) * width;
    let radius = half_width * (1. - layer as f32 / SHIMMER_LAYER_COUNT as f32);
    let left = (center - radius).max(0.);
    let right = (center + radius).min(width);

    (right > left).then(|| {
        Bounds::new(
            point(bounds.origin.x + px(left), bounds.origin.y),
            size(px(right - left), bounds.size.height),
        )
    })
}

fn shimmer_aligned_origin_x(
    origin: Point<Pixels>,
    align_width: Pixels,
    previous_glyph_x: Pixels,
    align: TextAlign,
    layout: &LineLayout,
    next_wrap: Option<&WrapBoundary>,
) -> Pixels {
    let line_end = next_wrap
        .map(|wrap| layout.runs[wrap.run_ix].glyphs[wrap.glyph_ix].position.x)
        .unwrap_or(layout.width);
    let line_width = line_end - previous_glyph_x;

    match align {
        TextAlign::Left => origin.x,
        TextAlign::Center => (origin.x * 2. + align_width - line_width) / 2.,
        TextAlign::Right => origin.x + align_width - line_width,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_shimmer_builder() {
        let color = Hsla::white();
        let style = ShimmerStyle::new()
            .duration(Duration::from_secs(3))
            .highlight_color(color)
            .spread(0.45)
            .reverse(true)
            .once(true);

        assert_eq!(style.duration, Duration::from_secs(3));
        assert_eq!(style.highlight_color, Some(color));
        assert_eq!(style.spread, ShimmerSpread::Relative(0.45));
        assert!(style.reverse);
        assert!(style.once);

        let text = ShimmerText::new("Thinking")
            .id("thinking")
            .with_shimmer_style(style)
            .duration(Duration::from_secs(4))
            .spread(0.5)
            .reverse(false)
            .once(false)
            .opacity(0.8);

        assert_eq!(text.text.as_ref(), "Thinking");
        assert_eq!(text.shimmer_style.duration, Duration::from_secs(4));
        assert_eq!(text.shimmer_style.spread, ShimmerSpread::Relative(0.5));
        assert!(!text.shimmer_style.reverse);
        assert!(!text.shimmer_style.once);
        assert_eq!(text.style.opacity, Some(0.8));
        assert_eq!(text.id, Some("thinking".into()));

        assert_eq!(
            ShimmerStyle::new().spread(0.).spread,
            ShimmerSpread::Relative(0.05)
        );
        assert_eq!(
            ShimmerStyle::new().spread(2.).spread,
            ShimmerSpread::Relative(1.)
        );
        assert_eq!(
            ShimmerStyle::new().spread(f32::NAN).spread,
            ShimmerSpread::default()
        );
        assert_eq!(
            ShimmerStyle::new().spread(px(0.)).spread,
            ShimmerSpread::Absolute(px(1.))
        );
        assert_eq!(
            ShimmerStyle::new().spread(px(48.)).spread,
            ShimmerSpread::Absolute(px(48.))
        );
        assert_eq!(
            ShimmerStyle::new().spread(px(f32::NAN)).spread,
            ShimmerSpread::default()
        );
        assert_eq!(
            ShimmerStyle::new().duration(Duration::ZERO).duration,
            Duration::from_millis(1)
        );
    }

    #[test]
    fn test_shimmer_band_moves_smoothly_across_text() {
        let bounds = Bounds::new(point(px(10.), px(20.)), size(px(100.), px(18.)));
        let spread = ShimmerSpread::default();

        assert!(shimmer_band_bounds(bounds, 0., spread, 0).is_none());
        assert!(shimmer_band_bounds(bounds, 1., spread, 0).is_none());

        let early = shimmer_band_bounds(bounds, 0.35, spread, 0).unwrap();
        let late = shimmer_band_bounds(bounds, 0.65, spread, 0).unwrap();
        assert!(early.origin.x < late.origin.x);

        let outer = shimmer_band_bounds(bounds, 0.5, spread, 0).unwrap();
        let inner = shimmer_band_bounds(bounds, 0.5, spread, SHIMMER_LAYER_COUNT - 1).unwrap();
        assert!(inner.origin.x > outer.origin.x);
        assert!(inner.size.width < outer.size.width);
        assert!(shimmer_band_bounds(bounds, 0.5, spread, SHIMMER_LAYER_COUNT).is_none());
        assert!(
            shimmer_band_bounds(
                Bounds::new(bounds.origin, size(px(0.), px(18.))),
                0.5,
                spread,
                0
            )
            .is_none()
        );

        let narrow = shimmer_band_bounds(bounds, 0.5, ShimmerSpread::Relative(0.1), 0).unwrap();
        let wide = shimmer_band_bounds(bounds, 0.5, ShimmerSpread::Relative(0.5), 0).unwrap();
        assert!(narrow.size.width < wide.size.width);

        // An absolute spread keeps the band width constant across text widths.
        let absolute = ShimmerSpread::Absolute(px(20.));
        let band = shimmer_band_bounds(bounds, 0.5, absolute, 0).unwrap();
        assert_eq!(band.size.width, px(40.));
        let wider_bounds = Bounds::new(bounds.origin, size(px(200.), px(18.)));
        let wider_band = shimmer_band_bounds(wider_bounds, 0.5, absolute, 0).unwrap();
        assert_eq!(wider_band.size.width, px(40.));
    }

    #[test]
    fn test_shimmer_highlight_stays_bright_in_both_themes() {
        let black = Hsla::black();
        let white = Hsla::white();
        let muted = white.mix_oklab(black, 0.55);
        let light = shimmer_highlight_color(black, white, black, false, None);
        let dark = shimmer_highlight_color(muted, black, white, true, None);

        assert!(light.l > black.l);
        assert!(dark.l > muted.l);
        assert!(light.a > dark.a);
        assert!((1. - (1. - light.a).powi(SHIMMER_LAYER_COUNT as i32) - 0.75).abs() < 0.001);
        assert!((1. - (1. - dark.a).powi(SHIMMER_LAYER_COUNT as i32) - 0.6).abs() < 0.001);

        // Text that already has the target's lightness sweeps toward the other end
        // instead of getting a band in its own color.
        let on_dark_foreground = shimmer_highlight_color(white, black, white, true, None);
        assert!(white.l - on_dark_foreground.l > 0.3);
        let on_light_background = shimmer_highlight_color(white, white, black, false, None);
        assert!(white.l - on_light_background.l > 0.3);

        let custom = shimmer_highlight_color(black, white, black, false, Some(muted));
        assert_eq!(custom.h, muted.h);
        assert_eq!(custom.s, muted.s);
        assert_eq!(custom.l, muted.l);

        let animation = loading_animation(Duration::from_secs(3), false);
        assert_eq!(animation.duration, Duration::from_secs(3));
        assert!(animation.synced);
        assert!(!animation.oneshot);
        assert_eq!(animation.max_fps, None);

        let animation = loading_animation(Duration::from_secs(3), true);
        assert_eq!(animation.duration, Duration::from_secs(3));
        assert!(animation.oneshot);
        assert!(!animation.synced);
    }
}
