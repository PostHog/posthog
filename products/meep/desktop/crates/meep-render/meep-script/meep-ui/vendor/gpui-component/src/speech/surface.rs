use std::f32::consts::{PI, TAU};

use instant::Instant;

use super::level::LevelMeter;

/// The space between two simulated points of the surface, in pixels: fine
/// enough for a smooth curve, coarse enough that a wide waveform stays cheap.
const NODE_SPACING: f32 = 3.;

/// The fewest points a surface has, however narrow.
const MIN_NODES: usize = 16;

/// The longest integration step, in seconds. The stiffest wave stays stable
/// well below this.
const STEP: f32 = 1. / 240.;

/// The most time one frame advances the surface, in seconds, so a stalled
/// window resumes calmly instead of releasing a burst of waves.
const MAX_FRAME: f32 = 0.05;

/// How strongly each point pulls on its neighbours, in points² per second²:
/// waves travel at its square root, about 150 px a second.
const STIFFNESS: f32 = 2_600.;

/// How strongly each point is pulled back to rest, per second², so the surface
/// settles flat instead of keeping a slow swell.
const RESTORING: f32 = 4.;

/// How quickly motion dies away, per second: a wave fades within about a
/// second of travel.
const DAMPING: f32 = 2.4;

/// How often the source at the middle rises and falls while there is sound.
const SOURCE_FREQUENCY: f32 = 3.2;

/// The source's height at full level, in surface units.
const SOURCE_AMPLITUDE: f32 = 0.9;

/// How far the points around the source move toward its height per step.
const SOURCE_PULL: f32 = 0.35;

/// How quickly the source follows the input level, in seconds: levels arrive
/// in bursts every 80 ms, and the source should swell rather than step.
const SOURCE_RESPONSE: f32 = 0.05;

/// A level at least this loud, after a quieter one, starts a syllable and
/// drops onto the surface.
const DROP_LEVEL: f32 = 0.18;

/// A level below this ends the syllable.
const DROP_RELEASE: f32 = 0.09;

/// How much louder than the previous level a level must be to drop again
/// within one syllable.
const DROP_RISE: f32 = 0.15;

/// How hard a drop of full level strikes the surface, in surface units per
/// second.
const DROP_STRENGTH: f32 = 9.;

/// How many points on each side of where a drop lands it strikes.
const DROP_REACH: isize = 4;

/// How long a surface that no waveform draws any more is kept, in seconds:
/// the widths a live resize passes through are not drawn again.
const STALE_AFTER: f32 = 0.5;

/// How many points a surface `width` pixels wide has.
fn node_count(width: f32) -> usize {
    ((width / NODE_SPACING) as usize).max(MIN_NODES)
}

/// The water surfaces of one speech state, one for each width a liquid
/// waveform draws, so that waveforms of different widths do not restart each
/// other. Waveforms of the same width share a surface.
#[derive(Default)]
pub(super) struct LiquidSurfaces(Vec<LiquidSurface>);

impl LiquidSurfaces {
    /// Advance the surface `width` pixels wide to `now`, starting one from rest
    /// for a width not drawn before, and drop the surfaces no longer drawn.
    pub(super) fn advance(&mut self, now: Instant, width: f32, meter: &LevelMeter) {
        let nodes = node_count(width);
        self.0.retain(|surface| {
            surface.heights.len() == nodes
                || surface
                    .advanced
                    .and_then(|advanced| now.checked_duration_since(advanced))
                    .is_none_or(|idle| idle.as_secs_f32() < STALE_AFTER)
        });
        let ix = match self
            .0
            .iter()
            .position(|surface| surface.heights.len() == nodes)
        {
            Some(ix) => ix,
            None => {
                self.0.push(LiquidSurface::new());
                self.0.len() - 1
            }
        };
        self.0[ix].advance(now, width, meter);
    }

    /// The heights of the surface `width` pixels wide; empty before it is
    /// first advanced.
    pub(super) fn heights(&self, width: f32) -> &[f32] {
        let nodes = node_count(width);
        self.0
            .iter()
            .find(|surface| surface.heights.len() == nodes)
            .map_or(&[], |surface| surface.heights())
    }
}

/// A one-dimensional water surface driven by speech, behind
/// [`SpeechWaveform::liquid`](super::SpeechWaveform::liquid).
///
/// While there is sound, the middle of the surface rises and falls with the
/// input level and sends waves toward both edges; each syllable also drops
/// onto the surface at a varying place. The waves travel, overlap and die away,
/// and in silence the surface settles flat. The edges are held at rest.
///
/// It is simulated, not derived from the level history, so it is advanced once
/// per frame with the frame's time; heights are displacements around zero that
/// stay within about `-1.0..=1.0`.
pub(super) struct LiquidSurface {
    heights: Vec<f32>,
    velocities: Vec<f32>,
    advanced: Option<Instant>,
    /// The source's smoothed level.
    level: f32,
    /// The source's phase, in radians.
    phase: f32,
    /// Levels of the meter already seen.
    seen: u64,
    /// Whether a syllable is sounding.
    sounding: bool,
    previous: f32,
    /// The state of a xorshift generator for where drops land; fixed, so a
    /// session plays out the same way for the same input.
    seed: u32,
}

impl LiquidSurface {
    pub(super) fn new() -> Self {
        Self {
            heights: Vec::new(),
            velocities: Vec::new(),
            advanced: None,
            level: 0.,
            phase: 0.,
            seen: 0,
            sounding: false,
            previous: 0.,
            seed: 0x9e37_79b9,
        }
    }

    /// The height of each point, evenly spaced from the leading edge to the
    /// trailing edge; empty before the first advance.
    pub(super) fn heights(&self) -> &[f32] {
        &self.heights
    }

    /// Advance the surface to `now`, `width` pixels wide, driven by `meter`'s
    /// levels. A change of width starts over from rest.
    pub(super) fn advance(&mut self, now: Instant, width: f32, meter: &LevelMeter) {
        let nodes = node_count(width);
        if self.heights.len() != nodes {
            self.heights = vec![0.; nodes];
            self.velocities = vec![0.; nodes];
        }

        let elapsed = self
            .advanced
            .and_then(|advanced| now.checked_duration_since(advanced))
            .map_or(0., |elapsed| elapsed.as_secs_f32().min(MAX_FRAME));
        self.advanced = Some(now);

        self.drop_syllables(meter);
        let level = meter.levels().last().unwrap_or(0.);
        self.level += (level - self.level) * (1. - (-elapsed / SOURCE_RESPONSE).exp());

        let steps = (elapsed / STEP).ceil() as usize;
        for _ in 0..steps {
            self.step(elapsed / steps as f32);
        }
    }

    /// Drop onto the surface for each syllable that started among the levels
    /// recorded since the last advance.
    fn drop_syllables(&mut self, meter: &LevelMeter) {
        let fresh = meter.recorded().saturating_sub(self.seen) as usize;
        self.seen = meter.recorded();
        let levels = meter.levels();
        let skip = levels.len().saturating_sub(fresh);
        for level in levels.skip(skip) {
            if level < DROP_RELEASE {
                self.sounding = false;
            } else if level >= DROP_LEVEL && (!self.sounding || level >= self.previous + DROP_RISE)
            {
                self.sounding = true;
                self.drop(level);
            }
            self.previous = level;
        }
    }

    /// Strike the surface with a drop of `level` somewhere away from its edges.
    fn drop(&mut self, level: f32) {
        self.seed ^= self.seed << 13;
        self.seed ^= self.seed >> 17;
        self.seed ^= self.seed << 5;
        let place = 0.12 + 0.76 * (self.seed as f32 / u32::MAX as f32);
        let last = self.heights.len() - 1;
        let center = (place * last as f32) as isize;
        for offset in -DROP_REACH..=DROP_REACH {
            let ix = center + offset;
            if ix > 0 && (ix as usize) < last {
                let falloff = (-(offset * offset) as f32 / 5.).exp();
                self.velocities[ix as usize] -= level * DROP_STRENGTH * falloff;
            }
        }
    }

    /// One integration step of `dt` seconds.
    fn step(&mut self, dt: f32) {
        let (heights, velocities) = (&mut self.heights, &mut self.velocities);
        let last = heights.len() - 1;

        self.phase = (self.phase + dt * TAU * SOURCE_FREQUENCY) % TAU;
        let source = self.level * SOURCE_AMPLITUDE * self.phase.sin();
        let middle = heights.len() / 2;
        for offset in -2_isize..=2 {
            let ix = (middle as isize + offset) as usize;
            let target = source * (-(offset * offset) as f32 / 2.).exp();
            heights[ix] += (target - heights[ix]) * SOURCE_PULL;
        }

        let damping = (-DAMPING * dt).exp();
        for ix in 1..last {
            let curvature = heights[ix - 1] + heights[ix + 1] - 2. * heights[ix];
            velocities[ix] += (STIFFNESS * curvature - RESTORING * heights[ix]) * dt;
            velocities[ix] *= damping;
        }
        for ix in 1..last {
            heights[ix] += velocities[ix] * dt;
        }
        heights[0] = 0.;
        heights[last] = 0.;
    }
}

/// A still surface for `level` when motion is reduced: a ripple around the
/// middle that grows with the level but does not travel.
pub(super) fn still_heights(level: f32) -> Vec<f32> {
    const POINTS: usize = 64;
    (0..POINTS)
        .map(|ix| {
            let from_middle = ix as f32 / (POINTS - 1) as f32 - 0.5;
            let envelope = (-(from_middle / 0.3).powi(2)).exp();
            level * SOURCE_AMPLITUDE * (TAU * 2.5 * from_middle).cos() * envelope
        })
        .collect()
}

/// How far a point `t` of the way across (`0.0..=1.0`) may move: nothing at
/// the edges, rising quickly to full in from them, so the line meets the edges
/// at rest instead of being cut off mid-wave.
pub(super) fn edge_taper(t: f32) -> f32 {
    // sin(π) rounds to just below zero, which a fractional power turns into NaN.
    (PI * t.clamp(0., 1.)).sin().max(0.).powf(0.35)
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;

    /// A meter that has recorded `count` levels of a loud tone.
    fn loud_meter(count: usize) -> LevelMeter {
        let mut meter = LevelMeter::new();
        meter.reset(16_000, 1);
        let tone: Vec<i16> = (0..1_280 * count)
            .map(|ix| if ix % 2 == 0 { 8_000 } else { -8_000 })
            .collect();
        meter.push(&tone);
        meter
    }

    /// Advance `surface` for `secs` at 60 frames a second from `start`.
    fn run(surface: &mut LiquidSurface, meter: &LevelMeter, start: Instant, secs: f32) -> Instant {
        let mut now = start;
        for _ in 0..(secs * 60.) as usize {
            now += Duration::from_secs_f32(1. / 60.);
            surface.advance(now, 300., meter);
        }
        now
    }

    #[test]
    fn silence_stays_flat() {
        let mut meter = LevelMeter::new();
        meter.reset(16_000, 1);
        let mut surface = LiquidSurface::new();
        run(&mut surface, &meter, Instant::now(), 1.);
        assert_eq!(surface.heights().len(), 100);
        assert!(surface.heights().iter().all(|height| *height == 0.));
    }

    #[test]
    fn sound_sends_waves_from_the_middle_toward_the_edges() {
        let meter = loud_meter(4);
        let mut surface = LiquidSurface::new();
        let start = Instant::now();
        surface.advance(start, 300., &meter);
        let near_edge = |surface: &LiquidSurface| surface.heights()[5].abs();

        let now = run(&mut surface, &meter, start, 0.1);
        let middle = surface.heights()[40..60]
            .iter()
            .fold(0f32, |m, h| m.max(h.abs()));
        assert!(middle > 0.05, "the middle moves: {middle}");
        let early = near_edge(&surface);

        let mut now = now;
        let mut reached = 0f32;
        for _ in 0..60 {
            now += Duration::from_secs_f32(1. / 60.);
            surface.advance(now, 300., &meter);
            reached = reached.max(near_edge(&surface));
        }
        assert!(
            reached > early.max(0.01),
            "the waves reach the edge: {reached}"
        );
    }

    #[test]
    fn the_edges_stay_at_rest_and_the_surface_stays_bounded() {
        let meter = loud_meter(8);
        let mut surface = LiquidSurface::new();
        run(&mut surface, &meter, Instant::now(), 5.);
        let heights = surface.heights();
        assert_eq!(heights[0], 0.);
        assert_eq!(heights[heights.len() - 1], 0.);
        assert!(
            heights.iter().all(|height| height.abs() < 2.),
            "{heights:?}"
        );
    }

    #[test]
    fn the_surface_settles_after_the_sound_stops() {
        let mut surface = LiquidSurface::new();
        let now = run(&mut surface, &loud_meter(4), Instant::now(), 1.);
        let mut quiet = LevelMeter::new();
        quiet.reset(16_000, 1);
        run(&mut surface, &quiet, now, 4.);
        assert!(surface.heights().iter().all(|height| height.abs() < 0.02));
    }

    #[test]
    fn a_change_of_width_starts_from_rest() {
        let meter = loud_meter(4);
        let mut surface = LiquidSurface::new();
        let now = run(&mut surface, &meter, Instant::now(), 0.5);
        surface.advance(now, 600., &meter);
        assert_eq!(surface.heights().len(), 200);
        assert!(surface.heights().iter().all(|height| *height == 0.));
    }

    #[test]
    fn waveforms_of_different_widths_keep_their_own_surfaces() {
        let meter = loud_meter(4);
        let mut surfaces = LiquidSurfaces::default();
        let (mut narrow, mut wide) = (LiquidSurface::new(), LiquidSurface::new());
        let mut now = Instant::now();
        for _ in 0..60 {
            now += Duration::from_secs_f32(1. / 60.);
            surfaces.advance(now, 300., &meter);
            surfaces.advance(now, 600., &meter);
            narrow.advance(now, 300., &meter);
            wide.advance(now, 600., &meter);
        }
        assert_eq!(surfaces.heights(300.), narrow.heights());
        assert_eq!(surfaces.heights(600.), wide.heights());
        assert!(wide.heights()[80].abs() > 0.01, "the waves travel");
    }

    #[test]
    fn a_width_no_longer_drawn_is_dropped() {
        let meter = loud_meter(4);
        let mut surfaces = LiquidSurfaces::default();
        let now = Instant::now();
        surfaces.advance(now, 300., &meter);
        surfaces.advance(now + Duration::from_secs_f32(0.1), 600., &meter);
        assert!(!surfaces.heights(300.).is_empty());
        surfaces.advance(now + Duration::from_secs(1), 600., &meter);
        assert!(surfaces.heights(300.).is_empty());
        assert_eq!(surfaces.heights(600.).len(), 200);
    }

    #[test]
    fn reduced_motion_ripples_in_place_with_the_level() {
        assert!(still_heights(0.).iter().all(|height| *height == 0.));
        let loud = still_heights(1.);
        assert!(loud[loud.len() / 2].abs() > 0.5);
        assert!(loud[0].abs() < 0.05);
    }

    #[test]
    fn the_taper_holds_the_edges() {
        assert_eq!(edge_taper(0.), 0.);
        assert!((0. ..0.01).contains(&edge_taper(1.)));
        assert!((edge_taper(0.5) - 1.).abs() < 1e-6);
        assert!(edge_taper(0.1) > 0.6);
    }
}
