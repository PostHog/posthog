//! The lines that mark a spike: an issue or a project that is large against the project's typical day.

/// The ledger keeps this many previous days, so a longer history can never be met.
pub const MAX_HISTORY_DAYS: usize = 29;
/// The stream health goal starts at 1,000 exceptions a month, so a smaller typical day is not a baseline.
const MIN_TYPICAL_DAY: f64 = 1_000.0 / 30.0;
/// Under this count an hour is over its line by chance on a small project.
const MIN_ISSUE_HOUR: f64 = 20.0;

/// The median of the days that had exceptions, so that one earlier spike or a silent weekend does not move it.
///
/// A median over few days follows a new project's first days closely, so `min_history_days` sets how many of them
/// are needed before anything is called a spike.
pub fn typical_day(previous_days: &[u64], min_history_days: usize) -> Option<Baseline> {
    let mut active: Vec<u64> = previous_days.iter().copied().filter(|n| *n > 0).collect();
    if active.len() < min_history_days {
        return None;
    }
    active.sort_unstable();
    let middle = active.len() / 2;
    let median = if active.len().is_multiple_of(2) {
        (active[middle - 1] + active[middle]) as f64 / 2.0
    } else {
        active[middle] as f64
    };
    Some(Baseline {
        typical_day: median.max(MIN_TYPICAL_DAY),
        history_days: active.len(),
    })
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Baseline {
    pub typical_day: f64,
    /// The days with exceptions behind the median.
    pub history_days: usize,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Reading {
    pub typical_day: f64,
    pub history_days: usize,
    pub issue_hour: f64,
    pub issue_day: f64,
    pub project_day: f64,
}

impl Reading {
    pub fn issue_hour_ratio(&self) -> f64 {
        self.issue_hour / (self.typical_day / 24.0)
    }

    pub fn issue_day_ratio(&self) -> f64 {
        self.issue_day / self.typical_day
    }

    pub fn project_day_ratio(&self) -> f64 {
        self.project_day / self.typical_day
    }
}

/// Multiples of the typical day, or of the typical hour for `issue_hour`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Thresholds {
    pub issue_hour: f64,
    pub issue_day: f64,
    pub project_day: f64,
}

impl Thresholds {
    pub fn is_valid(&self) -> bool {
        [self.issue_hour, self.issue_day, self.project_day]
            .iter()
            .all(|multiple| multiple.is_finite() && *multiple > 0.0)
    }

    pub fn over_issue_line(&self, reading: &Reading) -> bool {
        let fast =
            reading.issue_hour >= MIN_ISSUE_HOUR && reading.issue_hour_ratio() > self.issue_hour;
        fast || reading.issue_day_ratio() > self.issue_day
    }

    pub fn over_project_line(&self, reading: &Reading) -> bool {
        reading.project_day_ratio() > self.project_day
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const THRESHOLDS: Thresholds = Thresholds {
        issue_hour: 12.0,
        issue_day: 2.0,
        project_day: 3.0,
    };

    #[test]
    fn typical_day_is_the_median_of_the_days_with_exceptions() {
        let baseline = |typical_day, history_days| {
            Some(Baseline {
                typical_day,
                history_days,
            })
        };
        let mut days = vec![0; 15];
        days.extend([240; 13]);
        assert_eq!(typical_day(&days, 14), None);
        assert_eq!(typical_day(&days, 7), baseline(240.0, 13));

        days.push(90_000);
        assert_eq!(typical_day(&days, 14), baseline(240.0, 14));

        assert_eq!(typical_day(&[2; 29], 14), baseline(MIN_TYPICAL_DAY, 29));
    }

    #[test]
    fn an_issue_is_over_its_line_by_the_hour_or_by_the_day() {
        let quiet = Reading {
            typical_day: 240.0,
            history_days: 14,
            issue_hour: 100.0,
            issue_day: 400.0,
            project_day: 700.0,
        };
        assert!(!THRESHOLDS.over_issue_line(&quiet));
        assert!(!THRESHOLDS.over_project_line(&quiet));

        let burst = Reading {
            issue_hour: 121.0,
            ..quiet
        };
        assert!(THRESHOLDS.over_issue_line(&burst));

        let slow = Reading {
            issue_day: 481.0,
            ..quiet
        };
        assert!(THRESHOLDS.over_issue_line(&slow));

        let small_project = Reading {
            typical_day: MIN_TYPICAL_DAY,
            history_days: 14,
            issue_hour: 19.0,
            issue_day: 19.0,
            project_day: 19.0,
        };
        assert!(small_project.issue_hour_ratio() > THRESHOLDS.issue_hour);
        assert!(!THRESHOLDS.over_issue_line(&small_project));

        let busy_project = Reading {
            project_day: 721.0,
            ..quiet
        };
        assert!(THRESHOLDS.over_project_line(&busy_project));
    }
}
