use std::{collections::VecDeque, time::Duration};

use instant::Instant;

/// How much audio one level covers, and so how often the waveform takes a
/// step: about the pace of a syllable, so the bars follow speech without
/// racing past.
pub(super) const LEVEL_INTERVAL: Duration = Duration::from_millis(80);

/// How many recent levels are kept: enough to fill a wide waveform (about
/// twenty seconds of audio).
pub(super) const LEVEL_HISTORY: usize = 256;

/// How far behind the newest level the waveform's playhead runs, in levels.
/// Levels arrive in uneven bursts as the audio device hands over its buffers.
/// Between two arrivals the playhead advances a whole level, so it must run
/// more than one level behind to never catch up with the newest bar; the rest
/// absorbs late and bunched buffers. The bars then scroll at an even pace and
/// each new one slides in from past the trailing edge (about 140 ms later
/// than the sound).
const PLAYHEAD_LAG: f64 = 1.75;

/// How much of each level's arrival error the playhead's phase corrects:
/// small enough that one late buffer does not jerk the waveform.
const PLAYHEAD_PHASE_GAIN: f64 = 0.1;

/// How much each arrival error adjusts the playhead's pace, in seconds per
/// level per second of error, so it settles on the pace levels actually
/// arrive at (a device running slow or a timer firing late) instead of
/// drifting away from them.
const PLAYHEAD_PACE_GAIN: f64 = 0.01;

/// How far ahead of the playhead levels may pile up before the waveform shows
/// them anyway, in levels.
const PLAYHEAD_MAX_LEAD: f32 = 3.;

/// Raw levels below this are background noise and read as silence, so a quiet
/// room shows a calm baseline instead of flickering bars.
const NOISE_FLOOR: f32 = 0.06;

/// How far a level moves toward a louder reading per step: almost at once, so
/// peaks pop.
const ATTACK: f32 = 0.85;

/// How far a level moves toward a quieter reading per step: slowly, so bars
/// fall back smoothly.
const RELEASE: f32 = 0.3;

/// Turns a stream of PCM into smoothed input levels, one per
/// [`LEVEL_INTERVAL`] of audio, carrying partial intervals across pushes.
pub(super) struct LevelMeter {
    /// Samples per level: [`LEVEL_INTERVAL`] at the stream's rate and channels.
    window: usize,
    sum: f64,
    count: usize,
    smoothed: f32,
    levels: VecDeque<f32>,
    /// Levels recorded since the reset, including those dropped from history.
    recorded: u64,
    /// When level zero would have arrived on the playhead's even clock; `None`
    /// until the first level.
    anchor: Option<Instant>,
    /// The playhead's pace in seconds per level: [`LEVEL_INTERVAL`], tuned to
    /// how fast levels actually arrive.
    pace: f64,
}

impl LevelMeter {
    pub(super) fn new() -> Self {
        Self {
            window: window_for(16_000, 1),
            sum: 0.,
            count: 0,
            smoothed: 0.,
            levels: VecDeque::with_capacity(LEVEL_HISTORY),
            recorded: 0,
            anchor: None,
            pace: LEVEL_INTERVAL.as_secs_f64(),
        }
    }

    /// Clear the history and measure a stream of `sample_rate` × `channels`.
    pub(super) fn reset(&mut self, sample_rate: u32, channels: u16) {
        *self = Self {
            window: window_for(sample_rate, channels),
            ..Self::new()
        };
    }

    /// Measure `samples`; returns whether a new level was recorded.
    pub(super) fn push(&mut self, samples: &[i16]) -> bool {
        self.push_at(samples, Instant::now())
    }

    /// [`Self::push`] with the time the samples arrived.
    pub(super) fn push_at(&mut self, samples: &[i16], now: Instant) -> bool {
        let mut recorded = false;
        for &sample in samples {
            let sample = sample as f64 / i16::MAX as f64;
            self.sum += sample * sample;
            self.count += 1;
            if self.count == self.window {
                let raw = gate(level_of_rms((self.sum / self.count as f64).sqrt()));
                self.smoothed = smooth(self.smoothed, raw);
                if self.levels.len() == LEVEL_HISTORY {
                    self.levels.pop_front();
                }
                self.levels.push_back(self.smoothed);
                self.sum = 0.;
                self.count = 0;
                self.recorded += 1;
                self.align_playhead(now);
                recorded = true;
            }
        }
        recorded
    }

    /// Nudge the playhead's clock toward the arrival of the level just
    /// recorded: its pace toward the pace levels arrive at, its phase toward
    /// this arrival. Changing the pace keeps the playhead where it is, so the
    /// waveform never jumps.
    fn align_playhead(&mut self, now: Instant) {
        let Some(anchor) = self.anchor else {
            // The first level arrives on time by definition.
            self.anchor = now.checked_sub(LEVEL_INTERVAL);
            return;
        };
        let error = signed_secs(now, anchor) - self.recorded as f64 * self.pace;
        let interval = LEVEL_INTERVAL.as_secs_f64();
        let pace = (self.pace + error * PLAYHEAD_PACE_GAIN).clamp(interval / 2., interval * 2.);
        // Re-anchor so the playhead's position at `now` is unchanged by the new pace.
        let elapsed_levels = signed_secs(now, anchor) / self.pace;
        let anchor = shift_instant(now, -elapsed_levels * pace);
        self.pace = pace;
        self.anchor = Some(shift_instant(anchor, error * PLAYHEAD_PHASE_GAIN));
    }

    /// Where the waveform should draw the newest level at `now`, in levels past
    /// the trailing edge (0.0 at the edge, positive further out). The playhead
    /// advances at an even pace of about one level per [`LEVEL_INTERVAL`],
    /// behind the newest level; `None` before the first level.
    pub(super) fn lead_at(&self, now: Instant) -> Option<f32> {
        let anchor = self.anchor?;
        let playhead = signed_secs(now, anchor) / self.pace - PLAYHEAD_LAG;
        let lead = (self.recorded as f64 - playhead) as f32;
        // Never draw past the newest level, and never fall so far behind that a
        // burst of levels stays hidden.
        Some(lead.clamp(0., PLAYHEAD_MAX_LEAD))
    }

    pub(super) fn levels(&self) -> impl ExactSizeIterator<Item = f32> + '_ {
        self.levels.iter().copied()
    }

    /// Levels recorded since the reset, including those dropped from history.
    pub(super) fn recorded(&self) -> u64 {
        self.recorded
    }
}

/// `later - earlier` in seconds, negative when `later` is earlier.
fn signed_secs(later: Instant, earlier: Instant) -> f64 {
    match later.checked_duration_since(earlier) {
        Some(elapsed) => elapsed.as_secs_f64(),
        None => -earlier.duration_since(later).as_secs_f64(),
    }
}

/// `instant` moved by `secs`, forward when positive.
fn shift_instant(instant: Instant, secs: f64) -> Instant {
    let by = Duration::from_secs_f64(secs.abs());
    if secs >= 0. {
        instant + by
    } else {
        instant.checked_sub(by).unwrap_or(instant)
    }
}

fn window_for(sample_rate: u32, channels: u16) -> usize {
    let per_second = sample_rate as u128 * channels.max(1) as u128;
    ((per_second * LEVEL_INTERVAL.as_millis() / 1_000) as usize).max(1)
}

/// The loudness of an RMS amplitude in `0.0..=1.0`, mapping -50 dBFS..0 dBFS
/// linearly so that normal speech fills most of the range.
pub(super) fn level_of_rms(rms: f64) -> f32 {
    if rms <= 0. {
        return 0.;
    }
    let db = 20. * rms.log10();
    ((db + 50.) / 50.).clamp(0., 1.) as f32
}

fn gate(level: f32) -> f32 {
    if level < NOISE_FLOOR { 0. } else { level }
}

/// One step of fast-attack, slow-release smoothing from `previous` toward `raw`.
pub(super) fn smooth(previous: f32, raw: f32) -> f32 {
    let rate = if raw > previous { ATTACK } else { RELEASE };
    previous + (raw - previous) * rate
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tone(amplitude: i16, len: usize) -> Vec<i16> {
        (0..len)
            .map(|ix| if ix % 2 == 0 { amplitude } else { -amplitude })
            .collect()
    }

    #[test]
    fn one_level_per_interval_across_pushes() {
        let mut meter = LevelMeter::new();
        meter.reset(16_000, 1);
        // Two and a half levels' worth of audio in uneven pushes.
        let window = window_for(16_000, 1);
        assert!(!meter.push(&tone(1_000, window / 3)));
        assert!(meter.push(&tone(1_000, window)));
        assert!(meter.push(&tone(1_000, window + window / 6)));
        assert_eq!(meter.levels().len(), 2);
        assert!(meter.lead_at(Instant::now()).is_some());
    }

    #[test]
    fn the_window_follows_the_stream_format() {
        // 80 ms of 16 kHz mono, and of 48 kHz stereo.
        assert_eq!(window_for(16_000, 1), 1_280);
        assert_eq!(window_for(48_000, 2), 7_680);
    }

    #[test]
    fn peaks_rise_fast_and_fall_slowly() {
        let up = smooth(0., 1.);
        assert!(up >= 0.85);
        let down = smooth(1., 0.);
        assert!(down >= 0.65, "{down}");
        assert!(smooth(down, 0.) < down);
    }

    #[test]
    fn background_noise_reads_as_silence() {
        let mut meter = LevelMeter::new();
        meter.reset(16_000, 1);
        // -60 dBFS: below the -50 dB floor of the scale.
        meter.push(&tone(32, window_for(16_000, 1)));
        assert_eq!(meter.levels().next(), Some(0.));
    }

    #[test]
    fn level_maps_decibels_to_the_unit_range() {
        assert_eq!(level_of_rms(0.), 0.);
        assert_eq!(level_of_rms(1.), 1.);
        // -20 dBFS sits at 0.6 on the -50..0 dB scale.
        assert!((level_of_rms(0.1) - 0.6).abs() < 0.01);
    }

    #[test]
    fn history_is_bounded() {
        let mut meter = LevelMeter::new();
        meter.reset(16_000, 1);
        meter.push(&tone(8_000, window_for(16_000, 1) * (LEVEL_HISTORY + 10)));
        assert_eq!(meter.levels().len(), LEVEL_HISTORY);
    }

    fn level_at(meter: &mut LevelMeter, at: Instant) {
        let window = window_for(16_000, 1);
        assert!(meter.push_at(&tone(1_000, window), at));
    }

    #[test]
    fn the_playhead_moves_at_an_even_pace_between_levels() {
        let mut meter = LevelMeter::new();
        meter.reset(16_000, 1);
        let start = Instant::now();
        level_at(&mut meter, start);
        // Right after a level the newest bar sits past the trailing edge, then
        // slides toward it at one level per interval.
        let lead = |ms: u64| meter.lead_at(start + Duration::from_millis(ms)).unwrap();
        assert!((lead(0) - 1.75).abs() < 1e-3, "{}", lead(0));
        assert!((lead(40) - 1.25).abs() < 1e-3, "{}", lead(40));
        assert!((lead(80) - 0.75).abs() < 1e-3, "{}", lead(80));
        // Long after the audio stopped arriving, the newest bar rests at the edge.
        assert_eq!(lead(1_000), 0.);
    }

    #[test]
    fn uneven_arrivals_do_not_jerk_the_playhead() {
        let mut meter = LevelMeter::new();
        meter.reset(16_000, 1);
        let start = Instant::now();
        level_at(&mut meter, start);
        // The second level arrives 20 ms early: the playhead barely moves with
        // it; the bars stay put and the new one waits further out.
        let before = meter.lead_at(start + Duration::from_millis(60)).unwrap();
        level_at(&mut meter, start + Duration::from_millis(60));
        let after = meter.lead_at(start + Duration::from_millis(60)).unwrap();
        assert!((after - before - 1.).abs() < 0.05, "{before} → {after}");
    }

    #[test]
    fn the_playhead_settles_on_the_pace_levels_arrive_at() {
        for interval_ms in [72u64, 92] {
            let mut meter = LevelMeter::new();
            meter.reset(16_000, 1);
            let start = Instant::now();
            // Levels 10 % fast, then 15 % slow, as a late timer or a slow device would.
            for ix in 0..300u64 {
                level_at(&mut meter, start + Duration::from_millis(ix * interval_ms));
            }
            let last = start + Duration::from_millis(299 * interval_ms);
            let half = Duration::from_millis(interval_ms / 2);
            // The newest bar arrives the usual lag behind the playhead and is
            // still out past the edge half an interval later: the waveform
            // neither runs ahead and stalls nor falls behind.
            let at_arrival = meter.lead_at(last).unwrap();
            let between = meter.lead_at(last + half).unwrap();
            assert!(
                (at_arrival - 1.75).abs() < 0.1,
                "{interval_ms} ms: {at_arrival}"
            );
            assert!((between - 1.25).abs() < 0.1, "{interval_ms} ms: {between}");
        }
    }

    #[test]
    fn nothing_leads_before_the_first_level() {
        let mut meter = LevelMeter::new();
        meter.reset(16_000, 1);
        assert_eq!(meter.lead_at(Instant::now()), None);
    }
}
