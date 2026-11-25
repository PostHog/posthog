//! Boundary displacement shared by inputs and scroll viewports.
//!
//! Viewport owners keep their logical scroll position clamped and apply this
//! displacement only to content geometry. Inputs drive it directly, while
//! `ScrollBounce` can own a list or scroll area's vertical wheel handling.

use crate::scroll_bounce::Physics;
use gpui::TouchPhase;
use std::time::Duration;
#[cfg(not(target_family = "wasm"))]
use std::time::Instant;
#[cfg(target_family = "wasm")]
use web_time::Instant;

/// A pause without packets that ends a gesture.
///
/// Momentum arrives once per frame with no phase of its own, and some precise
/// scrolling devices send no phases, so a pause marks the end of their stream.
/// `ScrollBounce` waits the same time for the same reason.
const GESTURE_GAP: Duration = Duration::from_millis(250);

/// The fraction of the text's speed the edge carries when the text runs into
/// it or a finger lets go of it. Measured on `NSScrollView`, and the same as
/// WebKit's rubber-band amplitude: a fling arriving at 5000 px/s throws the
/// edge about 45 px out, 80 ms before it turns back.
const CARRY: f32 = 0.31;

/// A finger that sends nothing for this long before lifting has stopped:
/// it lets go of the edge with no speed.
const STILL: Duration = Duration::from_millis(50);

/// The interval assumed for the first packet of a stream.
const FRAME: f32 = 1. / 60.;

/// How far back the stream's speed is read. Packets carry no timestamp, so a
/// frame that takes long hands over several at once; read over a span, their
/// distance still spreads over the time they took, instead of each one
/// arriving at once and reading as a huge speed. That happens most on a fling
/// through a long list, just as it runs into the top.
const SPEED_SPAN: Duration = Duration::from_millis(50);

/// The most a packet's unused part can be and still be rounding. Far from
/// its start an `f32` offset cannot hold every fraction, so text that used a
/// whole packet can report a hair more or less, which is not an edge.
const ROUNDING: f32 = 0.01;

#[derive(Default)]
pub(crate) struct Overscroll {
    physics: Physics,
    sampled_at: Option<Instant>,
    last_packet_at: Option<Instant>,
    /// When the stream last moved, and how fast, in pixels per second.
    moved_at: Option<Instant>,
    velocity: f32,
    /// The packets that moved within the last `SPEED_SPAN`, and the one
    /// before them, which marks where the span starts.
    moves: Vec<(Instant, f32)>,
    /// A finger rests on the trackpad but has not moved since it touched.
    resting: bool,
    /// The edge already answered the rest of this gesture: a fling ran into
    /// it, or a finger let go of it stretched. The momentum that follows
    /// still scrolls the text back from the edge, but no longer moves the
    /// edge.
    spent: bool,
}

impl Overscroll {
    pub(crate) fn set_motion(&mut self, motion: crate::ScrollBounceMotion) {
        self.physics.set_motion(motion);
    }
    /// How far the text is drawn from where it scrolled to.
    pub(crate) fn offset(&self) -> f32 {
        self.physics.offset()
    }

    /// A new gesture starts: it may stretch the edge again.
    fn start_gesture(&mut self) {
        self.spent = false;
        self.velocity = 0.;
        self.moves.clear();
    }

    /// Track the stream's speed from packets that moved: the distance they
    /// covered over the time since the span started.
    fn sample(&mut self, dy: f32, now: Instant) {
        if dy == 0. {
            return;
        }
        if self.moves.last().is_some_and(|&(_, last)| last * dy < 0.) {
            self.moves.clear();
        }
        self.moves.push((now, dy));
        let start = self
            .moves
            .iter()
            .rposition(|&(at, _)| now.saturating_duration_since(at) > SPEED_SPAN)
            .unwrap_or(0);
        self.moves.drain(..start);
        let (first, _) = self.moves[0];
        let seconds = now.saturating_duration_since(first).as_secs_f32();
        self.velocity = if seconds > 0. && self.moves.len() > 1 {
            self.moves[1..].iter().map(|&(_, dy)| dy).sum::<f32>() / seconds
        } else {
            // The first packet, or several handed over at once.
            self.moves.iter().map(|&(_, dy)| dy).sum::<f32>() / FRAME
        };
        self.moved_at = Some(now);
    }

    /// Handle one vertical packet of `dy` over a viewport `extent` tall.
    /// `scroll` moves the text by a delta and returns how much of it the text
    /// used. Returns whether the stretch changed.
    pub(crate) fn packet(
        &mut self,
        dy: f32,
        phase: TouchPhase,
        extent: f32,
        now: Instant,
        mut scroll: impl FnMut(f32) -> f32,
    ) -> bool {
        let before = self.offset();
        let mut thrown = false;
        let gap = self
            .last_packet_at
            .replace(now)
            .map(|at| now.saturating_duration_since(at))
            .filter(|gap| *gap < GESTURE_GAP);
        // A finger resting on the trackpad sends nothing, however long it
        // holds the edge; only its own `Ended` lets go. A pause ends the
        // other streams.
        if gap.is_none() && !self.physics.is_dragging() {
            self.start_gesture();
            self.moved_at = None;
        }
        self.sample(dy, now);
        if phase == TouchPhase::Started {
            // Grab the edge, a returning one included, where it is.
            self.physics.begin(extent);
            self.spent = false;
            self.resting = dy == 0.;
        } else if dy != 0. {
            self.resting = false;
        } else if self.resting && self.physics.is_dragging() {
            // A finger that touches and lifts without moving cancels its
            // gesture, and GPUI reports the cancel as a move of nothing: it
            // lets go of the edge where it held it.
            self.resting = false;
            self.physics.let_go(0.);
            self.spent = self.offset() != 0.;
            if self.spent {
                self.sampled_at = Some(now);
            }
            return self.physics.is_moving();
        }
        if self.physics.is_dragging() {
            // A stretched edge takes the packet first; only what crosses back
            // over the edge scrolls the text.
            let rest = if self.offset() != 0. {
                self.physics.pull(dy)
            } else {
                dy
            };
            if rest != 0. {
                let unused = rest - scroll(rest);
                if unused.abs() > ROUNDING {
                    self.physics.pull(unused);
                }
            }
            if matches!(phase, TouchPhase::Ended | TouchPhase::Cancelled) {
                let moving = self
                    .moved_at
                    .is_some_and(|at| now.saturating_duration_since(at) < STILL);
                // Only an edge held past its end carries the finger's speed.
                // Let go within the text, the momentum that follows scrolls
                // it, and throws the edge only if it runs into it.
                let velocity = if moving && self.offset() != 0. {
                    self.velocity
                } else {
                    0.
                };
                self.physics.let_go(velocity * CARRY);
                thrown = true;
                self.spent = self.offset() != 0.;
            }
        } else if self.spent {
            // Momentum after the edge answered: back into the text it
            // scrolls; against the edge it has nothing left to move.
            scroll(dy);
        } else {
            // Momentum or phaseless precise scrolling: it scrolls the text,
            // and when the text runs into the edge it throws the edge as
            // fast as it arrived, once.
            let unused = dy - scroll(dy);
            if unused.abs() > ROUNDING {
                self.physics.let_go(self.velocity * CARRY);
                thrown = true;
                self.spent = true;
            }
        }
        let changed = (thrown && self.physics.is_moving()) || self.offset() != before;
        // Start the clock when the edge starts moving, and again when it is
        // let go, however long it was held; a packet that arrives while it
        // moves must not lose the time since the last frame.
        if thrown || (changed && self.sampled_at.is_none()) {
            self.sampled_at = Some(now);
        }
        changed
    }

    /// Advance the return to `now`. Returns whether it is still moving.
    pub(crate) fn step(&mut self, now: Instant) -> bool {
        let elapsed = self
            .sampled_at
            .replace(now)
            .map_or(0., |at| now.saturating_duration_since(at).as_secs_f32());
        let moving = self.physics.step(elapsed);
        if !moving {
            self.sampled_at = None;
        }
        moving
    }

    /// Drop any stretch at once, as when bouncing is turned off.
    pub(crate) fn reset(&mut self) {
        let mut physics = std::mem::take(&mut self.physics);
        physics.reset();
        *self = Self {
            physics,
            ..Self::default()
        };
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    /// Text that can scroll `room` further toward its end.
    fn text(room: &mut f32) -> impl FnMut(f32) -> f32 + '_ {
        move |dy: f32| {
            let used = dy.max(-*room);
            *room += used;
            used
        }
    }

    #[test]
    fn a_swipe_past_the_end_stretches_and_springs_back() {
        let now = Instant::now();
        let mut overscroll = Overscroll::default();
        let mut room = 30.;
        overscroll.packet(-10., TouchPhase::Started, 400., now, text(&mut room));
        overscroll.packet(-100., TouchPhase::Moved, 400., now, text(&mut room));
        // The text used the 30px it had left; the rest stretches the edge.
        assert_eq!(room, 0.);
        let stretched = overscroll.offset();
        assert!(stretched < 0. && stretched > -80., "{stretched}");

        overscroll.packet(0., TouchPhase::Ended, 400., now, text(&mut room));
        // Momentum after the release is answered by the spring alone.
        assert!(!overscroll.packet(-40., TouchPhase::Moved, 400., now, text(&mut room)));
        let mut later = now;
        while overscroll.step(later) {
            later += Duration::from_millis(16);
        }
        assert_eq!(overscroll.offset(), 0.);
    }

    #[test]
    fn pulling_back_unstretches_before_scrolling_the_text() {
        let now = Instant::now();
        let mut overscroll = Overscroll::default();
        let mut room = 0.;
        overscroll.packet(0., TouchPhase::Started, 400., now, text(&mut room));
        overscroll.packet(-50., TouchPhase::Moved, 400., now, text(&mut room));
        assert!(overscroll.offset() < 0.);
        // Back the other way: the first 50px return the edge, the next 20px
        // scroll the text back from its end.
        let mut scrolled = 0.;
        overscroll.packet(70., TouchPhase::Moved, 400., now, |dy| {
            scrolled += dy;
            dy
        });
        assert_eq!(overscroll.offset(), 0.);
        assert_eq!(scrolled, 20.);
    }

    /// A momentum stream of `speed` px/s decaying as AppKit's does, against
    /// text already at its end. Returns the edge's offset at each frame.
    fn fling(speed: f32) -> Vec<f32> {
        fling_through(speed, 0., 0)
    }

    /// The same stream through `room` px of text first, with every packet
    /// from frame `stall` to the impact handed over in one go, as when the
    /// frames that scroll the text take long to draw.
    fn fling_through(speed: f32, mut room: f32, stall: u32) -> Vec<f32> {
        let start = Instant::now();
        let frame = Duration::from_micros(16_667);
        let mut overscroll = Overscroll::default();
        let mut dy = -speed / 60.;
        let mut held = Vec::new();
        let mut path = Vec::new();
        for n in 0..120 {
            let at = start + frame * n;
            // Momentum keeps arriving well after the edge has settled.
            if n < 100 {
                held.push(dy);
                dy *= 0.95;
                if stall == 0 || n < stall || room == 0. || -held.iter().sum::<f32>() > room {
                    for dy in held.drain(..) {
                        overscroll.packet(dy, TouchPhase::Moved, 300., at, text(&mut room));
                    }
                }
            }
            overscroll.step(at);
            path.push(overscroll.offset());
        }
        path
    }

    #[cfg(not(any(target_os = "ios", target_os = "android")))]
    #[test]
    fn a_fling_throws_the_edge_as_far_as_nsscrollview_does() {
        // Measured on NSScrollView: a fling arriving at 1500 px/s peaks about
        // 14 px out, roughly 80 ms after impact, and settles within 0.65 s.
        let path = fling(1500.);
        let peak = path.iter().copied().fold(0., f32::min);
        assert!((-16. ..=-12.).contains(&peak), "peak {peak}");
        let turned = path.iter().position(|&offset| offset == peak).unwrap();
        assert!((4..=6).contains(&turned), "turned at frame {turned}");
        assert_eq!(path[50], 0., "the edge settles");
        // The momentum still arriving after impact never throws it again.
        assert!(path[turned..].windows(2).all(|pair| pair[1] >= pair[0]));
        assert!(path[50..].iter().all(|&offset| offset == 0.));
        // Twice the speed throws it about twice as far.
        let faster = fling(3000.).iter().copied().fold(0., f32::min);
        assert!((faster / peak - 2.).abs() < 0.15, "{faster} vs {peak}");
        // But no fling throws it past the limit, as none does in Finder.
        let hardest = fling(20_000.).iter().copied().fold(0., f32::min);
        assert!((-36. ..=-34.).contains(&hardest), "{hardest}");
    }

    #[cfg(not(any(target_os = "ios", target_os = "android")))]
    #[test]
    fn packets_handed_over_at_once_do_not_throw_the_edge_further() {
        let peak = |path: Vec<f32>| path.iter().copied().fold(0., f32::min);
        let even = peak(fling_through(4000., 500., 0));
        let stalled = peak(fling_through(4000., 500., 3));
        assert!(even < -10., "{even}");
        // Read per packet, the burst threw it out to the limit. Read over
        // the span, only the longer span's slower decay shows.
        assert!((stalled / even - 1.).abs() < 0.25, "{stalled} vs {even}");
    }

    #[test]
    fn a_touch_that_lifts_without_moving_lets_go_of_the_edge() {
        let start = Instant::now();
        let mut overscroll = Overscroll::default();
        let mut room = 0.;
        overscroll.packet(-80., TouchPhase::Moved, 400., start, text(&mut room));
        let later = start + Duration::from_millis(30);
        overscroll.step(later);
        let held = overscroll.offset();
        // Touch, then lift: GPUI reports `MayBegin` as `Started` and the
        // cancel as a `Moved` of nothing.
        overscroll.packet(0., TouchPhase::Started, 400., later, text(&mut room));
        assert!(overscroll.packet(0., TouchPhase::Moved, 400., later, text(&mut room)));
        let mut at = later;
        while overscroll.step(at) {
            at += Duration::from_millis(16);
        }
        assert!(held < 0.);
        assert_eq!(overscroll.offset(), 0.);
    }

    #[cfg(not(any(target_os = "ios", target_os = "android")))]
    #[test]
    fn a_stretch_follows_the_travel_as_nsscrollview_does() {
        // Measured on a 300 px NSScrollView: 100 px of travel past the end
        // stretches it 7 px. Further on, AppKit reads unaccelerated travel
        // and Finder never goes past 36 px; the stretch eases into that.
        let stretch = |travel: f32| {
            let start = Instant::now();
            let mut overscroll = Overscroll::default();
            let mut room = 0.;
            overscroll.packet(0., TouchPhase::Started, 300., start, text(&mut room));
            overscroll.packet(-travel, TouchPhase::Moved, 300., start, text(&mut room));
            -overscroll.offset()
        };
        assert!((6.5..=8.).contains(&stretch(100.)), "{}", stretch(100.));
        assert!((28. ..=34.).contains(&stretch(764.)), "{}", stretch(764.));
        assert!((35. ..36.).contains(&stretch(2400.)), "{}", stretch(2400.));
        assert!(stretch(100_000.) < 36.);
    }

    #[cfg(not(any(target_os = "ios", target_os = "android")))]
    #[test]
    fn a_still_release_returns_at_full_speed() {
        // NSScrollView lets go of a stretch held still and halves it in
        // 55 ms, starting at once rather than easing out.
        let start = Instant::now();
        let mut overscroll = Overscroll::default();
        let mut room = 0.;
        overscroll.packet(0., TouchPhase::Started, 300., start, text(&mut room));
        overscroll.packet(-800., TouchPhase::Moved, 300., start, text(&mut room));
        let held = overscroll.offset();
        let lifted = start + Duration::from_millis(200);
        overscroll.packet(0., TouchPhase::Ended, 300., lifted, text(&mut room));
        overscroll.step(lifted + Duration::from_millis(8));
        assert!(overscroll.offset() / held < 0.92, "starts at once");
        overscroll.step(lifted + Duration::from_millis(55));
        let half = overscroll.offset() / held;
        assert!((0.45..=0.55).contains(&half), "{half}");
    }

    /// Text `end` px long whose offset is an `f32`, as a scroll handle's is.
    fn long_text(offset: &mut f32, end: f32) -> impl FnMut(f32) -> f32 + '_ {
        move |dy: f32| {
            let before = *offset;
            *offset = (before + dy).clamp(-end, 0.);
            *offset - before
        }
    }

    #[test]
    fn a_drag_back_off_a_far_edge_keeps_scrolling_the_text() {
        let start = Instant::now();
        let end = 8902.5;
        for returned_ms in 1..60 {
            let mut overscroll = Overscroll::default();
            let mut offset = -end;
            overscroll.packet(
                0.,
                TouchPhase::Started,
                600.,
                start,
                long_text(&mut offset, end),
            );
            overscroll.packet(
                -200.,
                TouchPhase::Moved,
                600.,
                start,
                long_text(&mut offset, end),
            );
            let lifted = start + Duration::from_millis(100);
            overscroll.packet(
                0.,
                TouchPhase::Ended,
                600.,
                lifted,
                long_text(&mut offset, end),
            );
            // Caught on its way back, then dragged past the edge into the text.
            let caught = lifted + Duration::from_millis(returned_ms);
            overscroll.step(caught);
            overscroll.packet(
                0.,
                TouchPhase::Started,
                600.,
                caught,
                long_text(&mut offset, end),
            );
            overscroll.packet(
                300.,
                TouchPhase::Moved,
                600.,
                caught,
                long_text(&mut offset, end),
            );
            let before = offset;
            overscroll.packet(
                122.,
                TouchPhase::Moved,
                600.,
                caught,
                long_text(&mut offset, end),
            );
            assert_eq!(
                overscroll.offset(),
                0.,
                "the edge stays put ({returned_ms} ms)"
            );
            assert!(
                (offset - before - 122.).abs() < 0.01,
                "the drag scrolls the text"
            );
        }
    }

    #[test]
    fn a_flick_away_from_the_edges_leaves_the_next_drag_to_the_text() {
        let start = Instant::now();
        let frame = Duration::from_millis(16);
        let mut overscroll = Overscroll::default();
        let mut room = 10_000.;
        overscroll.packet(0., TouchPhase::Started, 400., start, text(&mut room));
        for n in 1..=6 {
            overscroll.packet(
                -70.,
                TouchPhase::Moved,
                400.,
                start + frame * n,
                text(&mut room),
            );
        }
        let lifted = start + frame * 7;
        overscroll.packet(0., TouchPhase::Ended, 400., lifted, text(&mut room));
        overscroll.step(lifted + frame);
        assert_eq!(overscroll.offset(), 0., "no edge to throw");
        // Fingers back down at once, dragging on the same way.
        let before = room;
        let again = lifted + frame * 2;
        overscroll.packet(0., TouchPhase::Started, 400., again, text(&mut room));
        overscroll.packet(
            -50.,
            TouchPhase::Moved,
            400.,
            again + frame,
            text(&mut room),
        );
        assert_eq!(before - room, 50., "the drag scrolls the text");
        assert_eq!(overscroll.offset(), 0.);
    }

    #[test]
    fn after_a_pause_the_next_flick_throws_the_edge_again() {
        let start = Instant::now();
        let mut overscroll = Overscroll::default();
        let mut room = 0.;
        assert!(overscroll.packet(-40., TouchPhase::Moved, 400., start, text(&mut room)));
        let mut at = start;
        while overscroll.step(at) {
            at += Duration::from_millis(16);
        }
        let later = at + GESTURE_GAP;
        assert!(overscroll.packet(-40., TouchPhase::Moved, 400., later, text(&mut room)));
    }

    #[test]
    fn momentum_back_into_the_text_scrolls_while_the_edge_returns() {
        let start = Instant::now();
        let mut overscroll = Overscroll::default();
        let mut room = 0.;
        overscroll.packet(0., TouchPhase::Started, 400., start, text(&mut room));
        overscroll.packet(-800., TouchPhase::Moved, 400., start, text(&mut room));
        let lifted = start + Duration::from_millis(100);
        overscroll.packet(0., TouchPhase::Ended, 400., lifted, text(&mut room));
        let later = lifted + Duration::from_millis(16);
        overscroll.step(later);
        let before = overscroll.offset();
        assert!(before < 0.);
        overscroll.packet(20., TouchPhase::Moved, 400., later, text(&mut room));
        assert_eq!(room, 20.);
        assert_eq!(overscroll.offset(), before, "the edge does not jump");
        overscroll.step(later + Duration::from_millis(16));
        assert!(overscroll.offset() > before && overscroll.offset() < 0.);
    }

    #[test]
    fn a_new_precise_gesture_takes_over_without_jumping() {
        let start = Instant::now();
        let mut overscroll = Overscroll::default();
        let mut room = 0.;
        overscroll.packet(-80., TouchPhase::Moved, 400., start, text(&mut room));
        overscroll.step(start + Duration::from_millis(16));
        let later = start + Duration::from_millis(200);
        overscroll.step(later);
        assert!(overscroll.offset() < 0.);
        let before = overscroll.offset();
        overscroll.packet(0., TouchPhase::Started, 400., later, text(&mut room));
        assert!(
            (overscroll.offset() - before).abs() < 0.001,
            "interruption does not jump"
        );
        assert!(overscroll.packet(-40., TouchPhase::Moved, 400., later, text(&mut room)));
        overscroll.step(later + Duration::from_millis(16));
        assert!(
            overscroll.offset() < before,
            "the new input pushes outward again"
        );
    }
}
