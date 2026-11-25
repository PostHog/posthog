use gpui::{
    AnyElement, App, Bounds, ContentMask, Entity, Hsla, IntoElement, ParentElement as _, Path,
    PathBuilder, Pixels, Point, RenderOnce, StyleRefinement, Styled, Window, canvas, div,
    linear_color_stop, linear_gradient, point, px, size,
};

use crate::{ActiveTheme as _, Sizable, Size, StyledExt as _};

use std::f32::consts::PI;

use instant::Instant;

use super::{
    SpeechState,
    surface::{edge_taper, still_heights},
};

/// The width of a waveform the caller does not size.
const DEFAULT_WIDTH: Pixels = px(96.);

/// The space between bars, relative to their width.
const GAP_RATIO: f32 = 2.5;

/// How far a liquid surface's crests reach from the midline, relative to the
/// height, leaving room for the line's own width.
const CREST_RATIO: f32 = 0.42;

/// How steeply a liquid surface's heights approach its crest: higher waves
/// flatten out instead of being cut off at the edge of the waveform.
const CREST_SOFTNESS: f32 = 1.4;

/// How wide a liquid surface's line is at its ends, relative to its middle.
const LINE_TAPER: f32 = 0.25;

/// How many points a liquid surface without heights is drawn with, so that
/// even a flat line tapers smoothly toward its ends.
const MIN_SURFACE_POINTS: usize = 32;

/// How opaque the water under a liquid surface is at its crest; it fades to
/// clear at the bottom.
const WATER_OPACITY: f32 = 0.16;

/// How a [`SpeechWaveform`] draws the input.
#[derive(Clone, Copy, Default)]
enum Appearance {
    /// A bar per level, scrolling toward the leading edge.
    #[default]
    Bars,
    /// A water surface that the voice sets in motion.
    Liquid,
}

/// A live waveform of a [`SpeechState`]'s input levels.
///
/// Each level is a bar that grows up and down from the midline; silence is a
/// dot. The newest level enters at the trailing edge and older ones scroll
/// toward the leading edge at a steady pace, redrawn every frame while audio is
/// captured, so the trail grows from the trailing edge until it fills the
/// width. Before any audio, nothing is drawn. With reduced motion the bars
/// still show each level but do not scroll between them.
///
/// [`Self::liquid`] draws a water surface instead.
///
/// Size the waveform like any element, e.g. `.w_full()` to span a row; it is
/// 96 px wide by default, and its height follows [`Sizable`].
#[derive(IntoElement)]
pub struct SpeechWaveform {
    state: Entity<SpeechState>,
    size: Size,
    appearance: Appearance,
    style: StyleRefinement,
}

impl SpeechWaveform {
    /// A waveform for `state`.
    pub fn new(state: &Entity<SpeechState>) -> Self {
        Self {
            state: state.clone(),
            size: Size::default(),
            appearance: Appearance::default(),
            style: StyleRefinement::default(),
        }
    }

    /// Draw the input as a water surface rather than bars.
    ///
    /// While there is sound, the middle of the surface rises and falls with
    /// the input level and sends waves toward both edges, and each syllable
    /// drops onto the surface at a varying place; the waves travel, overlap
    /// and die away, and in silence the surface settles to a flat line. The
    /// line is shaded with the water beneath it. The motion is simulated in
    /// the [`SpeechState`], so liquid waveforms of one state and width show
    /// the same surface, and it starts from rest with each session. With reduced
    /// motion the surface holds a ripple in place that grows with the level.
    ///
    /// Waves need room to travel: use it for a waveform that spans a row, not
    /// a compact one beside a button.
    pub fn liquid(mut self) -> Self {
        self.appearance = Appearance::Liquid;
        self
    }

    fn height(&self) -> Pixels {
        match self.size {
            Size::Size(height) => height,
            Size::XSmall => px(12.),
            Size::Small => px(16.),
            Size::Medium => px(20.),
            Size::Large => px(24.),
        }
    }
}

impl Sizable for SpeechWaveform {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Styled for SpeechWaveform {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for SpeechWaveform {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let height = self.height();
        let state = self.state.read(cx);
        let capturing = state.status().is_capturing();
        let animate = capturing && !cx.reduce_motion();
        if animate {
            window.request_animation_frame();
        }
        let color = if capturing {
            cx.theme().primary
        } else {
            cx.theme().muted_foreground
        };
        let content = match self.appearance {
            Appearance::Bars => bars(state, height, animate, color),
            Appearance::Liquid => liquid(&self.state, height, animate, color, cx),
        };

        div()
            .h(height)
            .w(DEFAULT_WIDTH)
            .flex_shrink_0()
            .refine_style(&self.style)
            .child(content)
    }
}

/// The bars of `state`'s levels, scrolling while `animate`.
fn bars(state: &SpeechState, height: Pixels, animate: bool, color: Hsla) -> AnyElement {
    // Bars thicken with the waveform so a tall one does not read as hairlines,
    // and stand apart so a run of silence reads as a row of dots.
    let bar = (height * 0.125).round().clamp(px(2.), px(4.));
    let gap = (bar * GAP_RATIO).round();
    let levels: Vec<f32> = state.levels().collect();
    // The bars follow an even clock rather than the arrival of each level,
    // which comes in uneven bursts: the newest bar slides in from just past
    // the trailing edge, so the waveform scrolls without stepping or
    // stalling. Without animation the newest bar sits at the edge.
    let scroll = state
        .level_lead_at(Instant::now())
        .filter(|_| animate)
        .map_or(0., |lead| -lead);

    canvas(
        |_, _, _| {},
        move |bounds, _, window, _| {
            // A bar sliding in is cut at the trailing edge, not drawn past it.
            // Bars are anti-aliased paths, not quads: quads snap to whole
            // device pixels, so a bar moving a fraction of a pixel per
            // frame would step instead of glide.
            window.with_content_mask(Some(ContentMask { bounds }), |window| {
                for rect in bar_rects(bounds, &levels, scroll, bar, gap) {
                    if let Some(path) = capsule(rect) {
                        window.paint_path(path, color);
                    }
                }
            });
        },
    )
    .size_full()
    .into_any_element()
}

/// The water surface of `state`, advanced to this frame while `animate`.
fn liquid(
    state: &Entity<SpeechState>,
    height: Pixels,
    animate: bool,
    color: Hsla,
    cx: &App,
) -> AnyElement {
    let still = cx
        .reduce_motion()
        .then(|| still_heights(state.read(cx).levels().last().unwrap_or(0.)));
    let state = state.clone();
    // The line at its thickest, in the middle.
    let line = (height * (1. / 10.)).max(px(2.));

    canvas(
        // The surface is advanced here, where the width is known; it stays as
        // it was while nothing is captured.
        move |bounds, _, cx| {
            still.unwrap_or_else(|| {
                state.update(cx, |state, _| {
                    if animate {
                        state.advance_surface(Instant::now(), bounds.size.width);
                    }
                    state.surface_heights(bounds.size.width).to_vec()
                })
            })
        },
        move |bounds, heights, window, _| {
            let points = surface_points(bounds, &heights);
            window.with_content_mask(Some(ContentMask { bounds }), |window| {
                let mut water = PathBuilder::fill();
                trace(&mut water, &points);
                water.line_to(bounds.bottom_right());
                water.line_to(bounds.bottom_left());
                water.close();
                if let Ok(water) = water.build() {
                    window.paint_path(
                        water,
                        linear_gradient(
                            180.,
                            linear_color_stop(color.opacity(WATER_OPACITY), 0.),
                            linear_color_stop(color.opacity(0.), 1.),
                        ),
                    );
                }
                // A ribbon rather than a stroke, so the line can swell toward
                // the middle and thin out at the edges.
                let (top, bottom) = ribbon(&points, line);
                let mut surface = PathBuilder::fill();
                trace(&mut surface, &top);
                if let Some(end) = bottom.last() {
                    surface.line_to(*end);
                }
                follow(
                    &mut surface,
                    &bottom.iter().rev().copied().collect::<Vec<_>>(),
                );
                surface.close();
                if let Ok(surface) = surface.build() {
                    window.paint_path(surface, color);
                }
            });
        },
    )
    .size_full()
    .into_any_element()
}

/// The points of a surface with `heights` across `bounds`: evenly spaced from
/// edge to edge, around the midline, flat when there are no heights.
fn surface_points(bounds: Bounds<Pixels>, heights: &[f32]) -> Vec<Point<Pixels>> {
    let middle = bounds.center().y;
    let crest = bounds.size.height * CREST_RATIO;
    let count = if heights.is_empty() {
        MIN_SURFACE_POINTS
    } else {
        heights.len().max(2)
    };
    (0..count)
        .map(|ix| {
            let t = ix as f32 / (count - 1) as f32;
            let height = heights.get(ix).copied().unwrap_or(0.);
            let rise = (height * CREST_SOFTNESS).tanh() * edge_taper(t);
            point(bounds.left() + bounds.size.width * t, middle + crest * rise)
        })
        .collect()
}

/// Trace a smooth curve through `points`, passing through each midpoint
/// between them.
fn trace(path: &mut PathBuilder, points: &[Point<Pixels>]) {
    let Some(first) = points.first() else {
        return;
    };
    path.move_to(*first);
    follow(path, points);
}

/// Continue `path`, which is at the first of `points`, along a smooth curve
/// through the rest, passing through each midpoint between them.
fn follow(path: &mut PathBuilder, points: &[Point<Pixels>]) {
    let Some(last) = points.last() else {
        return;
    };
    for pair in points[1..].windows(2) {
        let middle = point((pair[0].x + pair[1].x) / 2., (pair[0].y + pair[1].y) / 2.);
        path.curve_to(middle, pair[0]);
    }
    path.line_to(*last);
}

/// The two edges of a line through `points` that is `width` wide in the
/// middle and narrows smoothly to [`LINE_TAPER`] of that at the ends: each
/// point moved half the local width to either side, across the line rather
/// than straight up and down, so steep waves keep their weight.
fn ribbon(points: &[Point<Pixels>], width: Pixels) -> (Vec<Point<Pixels>>, Vec<Point<Pixels>>) {
    let last = points.len().saturating_sub(1).max(1);
    points
        .iter()
        .enumerate()
        .map(|(ix, at)| {
            let before = points[ix.saturating_sub(1)];
            let after = points[(ix + 1).min(points.len() - 1)];
            let (dx, dy) = ((after.x - before.x).as_f32(), (after.y - before.y).as_f32());
            let length = dx.hypot(dy).max(f32::EPSILON);
            let swell = (PI * ix as f32 / last as f32).sin().max(0.);
            let half = width * (LINE_TAPER + (1. - LINE_TAPER) * swell) / 2.;
            let offset = point(half * (-dy / length), half * (dx / length));
            (*at - offset, *at + offset)
        })
        .unzip()
}

/// A capsule filling `rect`: round caps on its short ends, a dot when square.
pub(super) fn capsule(rect: Bounds<Pixels>) -> Option<Path<Pixels>> {
    let radius = rect.size.width.min(rect.size.height) / 2.;
    let radii = point(radius, radius);
    let (left, right) = (rect.left(), rect.right());
    let (top, bottom) = (rect.top() + radius, rect.bottom() - radius);
    let mut path = PathBuilder::fill();
    path.move_to(point(left, top));
    path.arc_to(radii, px(0.), false, true, point(right, top));
    path.line_to(point(right, bottom));
    path.arc_to(radii, px(0.), false, true, point(left, bottom));
    path.close();
    path.build().ok()
}

/// The bars for `levels` (oldest first) in `bounds`: the newest at the trailing
/// edge, `scroll` of a step further toward the leading edge (negative past the
/// trailing edge, where a bar is cut off or left out), each centered on
/// the midline and at least as tall as it is wide. Only levels that exist are
/// drawn, so a short history leaves the leading part empty.
fn bar_rects(
    bounds: Bounds<Pixels>,
    levels: &[f32],
    scroll: f32,
    bar: Pixels,
    gap: Pixels,
) -> Vec<Bounds<Pixels>> {
    let pitch = bar + gap;
    let height = bounds.size.height;
    let middle = bounds.origin.y + height / 2.;
    // Enough bars to reach the leading edge from wherever the newest one sits.
    let count = ((bounds.size.width + gap) / pitch - scroll.min(0.))
        .ceil()
        .max(0.) as usize
        + 1;
    (0..count)
        .filter_map(|from_end| {
            let right = bounds.right() - pitch * (from_end as f32 + scroll);
            let left = right - bar;
            if left < bounds.left() - px(0.5) || left >= bounds.right() {
                return None;
            }
            let level = levels[levels.len().checked_sub(from_end + 1)?];
            let bar_height = (height * level.clamp(0., 1.)).max(bar);
            Some(Bounds::new(
                point(left, middle - bar_height / 2.),
                size(bar, bar_height),
            ))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn bounds(width: f32, height: f32) -> Bounds<Pixels> {
        Bounds::new(point(px(10.), px(20.)), size(px(width), px(height)))
    }

    #[test]
    fn a_short_history_grows_from_the_trailing_edge() {
        let bounds = bounds(98., 20.);
        let rects = bar_rects(bounds, &[0.2, 0.9], 0., px(2.), px(5.));
        assert_eq!(rects.len(), 2);
        assert_eq!(rects[0].right(), bounds.right());
        assert_eq!(rects[0].size.height, px(18.));
        assert_eq!(rects[1].right(), bounds.right() - px(7.));
        assert_eq!(rects[1].size.height, px(4.));
    }

    #[test]
    fn a_long_history_fills_the_width() {
        let bounds = bounds(96., 20.);
        let rects = bar_rects(bounds, &[0.; 64], 0., px(2.), px(5.));
        // 96 px at a 7 px pitch fits 14 bars; the oldest sit off the leading edge.
        assert_eq!(rects.len(), 14);
        assert!(
            rects
                .iter()
                .all(|rect| rect.left() >= bounds.left() - px(0.5))
        );
    }

    #[test]
    fn nothing_is_drawn_before_any_audio() {
        assert!(bar_rects(bounds(96., 20.), &[], 0., px(2.), px(5.)).is_empty());
    }

    #[test]
    fn a_surface_at_rest_is_a_flat_line_across_the_midline() {
        let bounds = bounds(96., 20.);
        let points = surface_points(bounds, &[]);
        assert_eq!(points.len(), MIN_SURFACE_POINTS);
        assert_eq!(points[0], point(bounds.left(), px(30.)));
        assert_eq!(
            points[MIN_SURFACE_POINTS - 1],
            point(bounds.right(), px(30.))
        );
        assert!(points.iter().all(|point| point.y == px(30.)));
    }

    #[test]
    fn a_surface_line_swells_in_the_middle_and_thins_at_the_ends() {
        let bounds = bounds(96., 20.);
        let points = surface_points(bounds, &[]);
        let (top, bottom) = ribbon(&points, px(4.));
        let width = |ix: usize| bottom[ix].y - top[ix].y;
        let middle = points.len() / 2;
        assert!((width(0) - px(1.)).abs() < px(0.01));
        assert!((width(points.len() - 1) - px(1.)).abs() < px(0.01));
        assert!(width(middle) > px(3.9));
        assert!(width(4) > width(0) && width(middle) > width(4));
    }

    #[test]
    fn a_surface_line_keeps_its_width_across_a_steep_wave() {
        let points = [
            point(px(0.), px(0.)),
            point(px(1.), px(1.)),
            point(px(2.), px(2.)),
        ];
        let (top, bottom) = ribbon(&points, px(4.));
        let across = bottom[1] - top[1];
        let length = across.x.as_f32().hypot(across.y.as_f32());
        assert!((length - 4.).abs() < 0.01, "{length}");
    }

    #[test]
    fn a_surface_meets_the_edges_at_rest_and_keeps_its_crests_inside() {
        let bounds = bounds(96., 20.);
        let points = surface_points(bounds, &[5., -5., 5., -5., 5.]);
        assert_eq!(points.len(), 5);
        assert_eq!(points[0].y, px(30.));
        assert!((points[4].y - px(30.)).abs() < px(0.1));
        for point in &points {
            assert!((point.y - px(30.)).abs() <= px(20. * CREST_RATIO));
        }
        assert!(points[1].y < px(30.) && points[2].y > px(30.));
    }

    #[test]
    fn bars_grow_from_the_midline_and_silence_is_a_dot() {
        let bounds = bounds(40., 20.);
        for rect in bar_rects(bounds, &[0.5, 0.], 0., px(2.), px(5.)) {
            let middle = rect.origin.y + rect.size.height / 2.;
            assert_eq!(middle, px(30.));
            assert!(rect.size.height >= px(2.));
        }
    }

    #[test]
    fn scrolling_moves_bars_toward_the_leading_edge() {
        let bounds = bounds(40., 20.);
        let still = bar_rects(bounds, &[1.; 8], 0., px(2.), px(5.));
        let moving = bar_rects(bounds, &[1.; 8], 0.5, px(2.), px(5.));
        assert_eq!(still[0].left() - moving[0].left(), px(3.5));
        assert!(
            moving
                .iter()
                .all(|rect| rect.left() >= bounds.left() - px(0.5))
        );
    }

    #[test]
    fn a_bar_past_the_trailing_edge_is_left_out_until_it_slides_in() {
        let bounds = bounds(40., 20.);
        // The newest bar sits a whole pitch past the edge: not drawn yet.
        let out = bar_rects(bounds, &[1., 0.5], -1., px(2.), px(5.));
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].right(), bounds.right());
        // A fifth of a pitch out (1.4 px): drawn across the edge, cut by the
        // content mask.
        let entering = bar_rects(bounds, &[1., 0.5], -0.2, px(2.), px(5.));
        assert_eq!(entering.len(), 2);
        assert!(entering[0].left() < bounds.right());
    }
}
