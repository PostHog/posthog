//! Rage and dead clicks, with the session feature recorder's definitions (`session-feature-recorder.ts`).

/// Clicks closer than this in time and space continue a run of clicks.
const RUN_WINDOW_MS: f64 = 1000.0;
const RUN_DISTANCE_PX: f64 = 30.0;
/// The click in a run that starts counting as a rage click.
const RAGE_RUN_LENGTH: u32 = 3;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClickKind {
    Plain,
    Rage,
    /// The previous click was alone and nothing navigated after it. It is counted when this click arrives.
    AfterDead,
}

/// Click state that spans blocks, because a run of clicks can cross a flush.
#[derive(Default)]
pub struct ClickTracker {
    last: Option<(f64, f64, f64)>,
    run: u32,
    navigated_since_last_click: bool,
}

impl ClickTracker {
    pub fn navigated(&mut self) {
        self.navigated_since_last_click = true;
    }

    /// Records a click and says how to count it. A click without coordinates starts a new run.
    pub fn click(&mut self, ts: f64, position: Option<(f64, f64)>) -> ClickKind {
        let previous = self.last;
        let navigated = std::mem::take(&mut self.navigated_since_last_click);
        let Some((x, y)) = position else {
            self.run = 1;
            self.last = None;
            return ClickKind::Plain;
        };
        self.last = Some((ts, x, y));
        let Some((last_ts, last_x, last_y)) = previous else {
            self.run = 1;
            return ClickKind::Plain;
        };
        let (dx, dy) = (x - last_x, y - last_y);
        // `Math.sqrt(dx * dx + dy * dy)`, which can round differently from `hypot`.
        if ts - last_ts < RUN_WINDOW_MS && (dx * dx + dy * dy).sqrt() < RUN_DISTANCE_PX {
            self.run += 1;
            return if self.run >= RAGE_RUN_LENGTH {
                ClickKind::Rage
            } else {
                ClickKind::Plain
            };
        }
        let dead = self.run == 1 && !navigated;
        self.run = 1;
        if dead {
            ClickKind::AfterDead
        } else {
            ClickKind::Plain
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classifies_clicks_as_the_feature_recorder_does() {
        let at = |ts: f64, x: f64| (ts, Some((x, 100.0)));
        // (time, position, navigated before this click, expected)
        let cases = [
            (at(0.0, 10.0), false, ClickKind::Plain),
            (at(200.0, 12.0), false, ClickKind::Plain),
            (at(400.0, 14.0), false, ClickKind::Rage),
            (at(600.0, 16.0), false, ClickKind::Rage),
            // A distant click ends the run. The run was longer than one click, so nothing was dead.
            (at(5000.0, 500.0), false, ClickKind::Plain),
            // The lone click at 5000 had no navigation after it: dead, counted now.
            (at(9000.0, 10.0), false, ClickKind::AfterDead),
            // A navigation after the lone click at 9000 means the click did something.
            (at(15000.0, 500.0), true, ClickKind::Plain),
            ((16000.0, None), false, ClickKind::Plain),
        ];
        let mut tracker = ClickTracker::default();
        for ((ts, position), navigated, expected) in cases {
            if navigated {
                tracker.navigated();
            }
            assert_eq!(tracker.click(ts, position), expected, "click at {ts}");
        }
    }
}
