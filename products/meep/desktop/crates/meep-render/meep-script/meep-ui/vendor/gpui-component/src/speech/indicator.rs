use gpui::{
    App, Bounds, Entity, InteractiveElement as _, IntoElement, ParentElement as _, Pixels,
    RenderOnce, Styled as _, Window, canvas, div, point, size,
};

use crate::{Icon, IconName, Sizable, Size};

use instant::Instant;

use super::{SpeechState, level::LEVEL_INTERVAL, waveform::capsule};

/// The group the indicator's layers watch for the pointer.
const GROUP: &str = "speech-indicator";

/// How many bars move with the voice.
const BARS: usize = 4;

/// How strongly each bar follows the voice: fuller in the middle, so the bars
/// read as one shape rather than four equal meters.
const WEIGHTS: [f32; BARS] = [0.65, 1., 0.85, 0.55];

/// How far behind the newest level each bar reads, in levels, so the bars rise
/// and fall one after another instead of in step.
const LAGS: [f32; BARS] = [1., 0., 0.5, 1.5];

/// The bars' heights with reduced motion: a still glyph of a voice.
const STILL: [f32; BARS] = [0.4, 0.7, 0.55, 0.35];

/// How high the bars breathe in silence, so a quiet microphone still reads as
/// listening.
const BREATH: f32 = 0.12;

/// How fast the bars breathe, in radians per second.
const BREATH_RATE: f32 = 2.4;

/// How far apart the bars breathe, in radians.
const BREATH_SPREAD: f32 = 0.9;

/// A bar's width, the gap between bars and a full bar's height, relative to
/// the indicator's shorter side.
const BAR_RATIO: f32 = 0.085;
const GAP_RATIO: f32 = 0.075;
const HEIGHT_RATIO: f32 = 0.46;

/// What a stop button shows while a [`SpeechState`] captures: bars that rise
/// and fall with the voice, so the button reads as listening rather than as a
/// media control, turning into a stop glyph while the pointer is over it.
///
/// In silence the bars shrink to dots that breathe gently; with reduced motion
/// they hold still. They take the text color of the button they sit in.
///
/// [`SpeechButton`](super::SpeechButton) shows it while capturing. A caller
/// with its own stop button makes it the button's only child and removes the
/// button's padding, so the indicator fills it; the button stays responsible
/// for its accessible label, which should say that it stops. Keyboard focus
/// has no pointer to reveal the stop glyph, so while the button has it, show
/// the glyph in place of the indicator, as `SpeechButton` does. Size it like
/// the icon it replaces: the stop glyph takes that size.
#[derive(IntoElement)]
pub struct SpeechIndicator {
    state: Entity<SpeechState>,
    size: Size,
}

impl SpeechIndicator {
    /// An indicator for `state`.
    pub fn new(state: &Entity<SpeechState>) -> Self {
        Self {
            state: state.clone(),
            size: Size::default(),
        }
    }
}

impl Sizable for SpeechIndicator {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl RenderOnce for SpeechIndicator {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let state = self.state.read(cx);
        let heights = if cx.reduce_motion() {
            STILL
        } else {
            let lead = state.level_lead_at(Instant::now());
            let levels: Vec<f32> = state.levels().collect();
            bar_heights(&levels, state.levels_recorded(), lead)
        };
        if state.status().is_capturing() && !cx.reduce_motion() {
            window.request_animation_frame();
        }

        div()
            .size_full()
            .relative()
            .group(GROUP)
            .child(
                div()
                    .absolute()
                    .inset_0()
                    .group_hover(GROUP, |this| this.opacity(0.))
                    .child(
                        canvas(
                            |_, _, _| {},
                            move |bounds, _, window, _| {
                                // The button's foreground, whatever its variant.
                                let color = window.text_style().color;
                                for rect in bar_rects(bounds, &heights) {
                                    if let Some(path) = capsule(rect) {
                                        window.paint_path(path, color);
                                    }
                                }
                            },
                        )
                        .size_full(),
                    ),
            )
            .child(
                div()
                    .absolute()
                    .inset_0()
                    .flex()
                    .items_center()
                    .justify_center()
                    .opacity(0.)
                    .group_hover(GROUP, |this| this.opacity(1.))
                    .child(Icon::new(IconName::Square).with_size(self.size)),
            )
    }
}

/// The height of each bar in `0.0..=1.0` for `levels` (oldest first), `recorded`
/// of them so far this session, with the newest `lead` levels past the
/// playhead; see `LevelMeter::lead_at`. Without a lead, before any audio, the
/// bars are dots.
fn bar_heights(levels: &[f32], recorded: u64, lead: Option<f32>) -> [f32; BARS] {
    let (Some(lead), Some(last)) = (lead, levels.len().checked_sub(1)) else {
        return [0.; BARS];
    };
    // The playhead moves evenly between levels, so reading at it rather than
    // at the newest level makes the bars glide instead of jump every 80 ms.
    let playhead = last as f32 - lead;
    let at = |position: f32| {
        let position = position.clamp(0., last as f32);
        let below = position.floor() as usize;
        let above = (below + 1).min(last);
        let fraction = position - below as f32;
        levels[below] + (levels[above] - levels[below]) * fraction
    };
    // The bars breathe only while the voice is quiet, on a clock that runs
    // with the audio.
    let seconds = (recorded as f32 - lead) * LEVEL_INTERVAL.as_secs_f32();
    let quiet = 1. - (at(playhead) * 4.).min(1.);

    std::array::from_fn(|ix| {
        let voice = at(playhead - LAGS[ix]) * WEIGHTS[ix];
        let phase = seconds * BREATH_RATE + ix as f32 * BREATH_SPREAD;
        let breath = BREATH * (0.5 + 0.5 * phase.sin()) * quiet;
        voice.max(breath).clamp(0., 1.)
    })
}

/// The bars for `heights` in `bounds`: side by side around the center, each
/// centered on the midline and at least as tall as it is wide.
fn bar_rects(bounds: Bounds<Pixels>, heights: &[f32; BARS]) -> Vec<Bounds<Pixels>> {
    let side = bounds.size.width.min(bounds.size.height);
    let bar = side * BAR_RATIO;
    let gap = side * GAP_RATIO;
    let full = side * HEIGHT_RATIO;
    let total = bar * BARS as f32 + gap * (BARS - 1) as f32;
    let left = bounds.center().x - total / 2.;
    let middle = bounds.center().y;
    heights
        .iter()
        .enumerate()
        .map(|(ix, height)| {
            let height = bar + (full - bar) * *height;
            Bounds::new(
                point(left + (bar + gap) * ix as f32, middle - height / 2.),
                size(bar, height),
            )
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use gpui::px;

    use super::*;

    #[test]
    fn the_bars_are_dots_before_any_audio() {
        assert_eq!(bar_heights(&[], 0, None), [0.; BARS]);
        assert_eq!(bar_heights(&[0.5], 1, None), [0.; BARS]);
    }

    #[test]
    fn the_bars_follow_a_loud_voice_fullest_in_the_middle() {
        let heights = bar_heights(&[1.; 8], 8, Some(0.));
        assert_eq!(heights, WEIGHTS);
    }

    #[test]
    fn the_bars_rise_one_after_another() {
        // A voice that has only just started reaches the bar without lag
        // first and the most lagging bar last.
        let heights = bar_heights(&[0., 0., 0., 1.], 4, Some(0.));
        assert!(heights[1] > 0.9);
        assert!(heights[0] < heights[1]);
        assert!(heights[3] < heights[2]);
    }

    #[test]
    fn the_bars_glide_between_levels() {
        let levels = [0., 1.];
        let at_edge = bar_heights(&levels, 2, Some(0.))[1];
        let between = bar_heights(&levels, 2, Some(0.5))[1];
        let behind = bar_heights(&levels, 2, Some(1.))[1];
        assert!(
            behind < between && between < at_edge,
            "{behind} {between} {at_edge}"
        );
    }

    #[test]
    fn the_bars_breathe_in_silence_but_stay_low() {
        let silence = [0.; 8];
        let early = bar_heights(&silence, 8, Some(0.));
        let later = bar_heights(&silence, 12, Some(0.));
        assert_ne!(early, later);
        assert!(early.iter().chain(&later).all(|height| *height <= BREATH));
    }

    #[test]
    fn bars_sit_side_by_side_around_the_center_and_grow_from_the_midline() {
        let bounds = Bounds::new(point(px(0.), px(0.)), size(px(24.), px(24.)));
        let rects = bar_rects(bounds, &[0., 1., 0.5, 0.]);
        let first = rects.first().unwrap();
        let last = rects.last().unwrap();
        assert!((first.left() + last.right() - px(24.)).abs() < px(0.01));
        for rect in &rects {
            assert!((rect.center().y - px(12.)).abs() < px(0.01));
            assert!(rect.size.height >= rect.size.width);
        }
        assert!(rects[1].size.height > rects[2].size.height);
        assert!(rects[2].size.height > rects[0].size.height);
    }
}
