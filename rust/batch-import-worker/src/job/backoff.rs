use std::time::Duration;

/// Exponential backoff policy.
///
/// - initial_delay: base delay for attempt 0
/// - multiplier: factor by which delay grows each attempt (> 1.0)
/// - max_delay: cap for the computed delay
#[derive(Debug, Clone, Copy)]
pub struct BackoffPolicy {
    pub initial_delay: Duration,
    pub multiplier: f64,
    pub max_delay: Duration,
}

impl BackoffPolicy {
    pub const fn new(initial_delay: Duration, multiplier: f64, max_delay: Duration) -> Self {
        Self {
            initial_delay,
            multiplier,
            max_delay,
        }
    }

    pub const fn default_long() -> Self {
        Self {
            initial_delay: Duration::from_secs(60),
            multiplier: 2.0,
            max_delay: Duration::from_secs(60 * 60),
        }
    }

    pub fn next_delay(&self, attempt: u32) -> Duration {
        let pow = self.multiplier.powi(attempt as i32);
        let scaled = if pow.is_finite() {
            self.initial_delay.mul_f64(pow)
        } else {
            self.max_delay
        };
        scaled.min(self.max_delay)
    }
}

/// Build operator/developer status_message and user-facing display message.
/// If a date range is provided, include it in the display message.
pub fn format_backoff_messages(date_range: Option<&str>, delay: Duration) -> (String, String) {
    let secs = delay.as_secs();
    let status =
        format!("Rate limited (429). Scheduling retry in {secs}s. Waiting before next attempt.");
    let display = match date_range {
        Some(dr) => format!("Rate limit hit. Will retry in {secs}s. Date range: {dr}"),
        None => format!("Rate limit hit. Will retry in {secs}s."),
    };
    (status, display)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_policy_progression_and_cap() {
        let p = BackoffPolicy::default_long();

        // attempt -> expected seconds (cap at 3600s)
        let cases = vec![
            (0, 60),
            (1, 120),
            (2, 240),
            (3, 480),
            (4, 960),
            (5, 1920),
            (6, 3600), // 3840 capped to 3600
            (10, 3600),
            (20, 3600),
        ];

        for (attempt, expected_secs) in cases {
            let d = p.next_delay(attempt);
            assert_eq!(d.as_secs(), expected_secs, "attempt {attempt}");
        }
    }

    #[test]
    fn test_custom_policy_progression() {
        let p = BackoffPolicy::new(Duration::from_secs(5), 3.0, Duration::from_secs(70));
        let cases = vec![
            (0, 5),  // 5
            (1, 15), // 5*3
            (2, 45), // 5*9
            (3, 70), // 5*27=135 -> cap 70
            (4, 70),
        ];
        for (attempt, expected_secs) in cases {
            let d = p.next_delay(attempt);
            assert_eq!(d.as_secs(), expected_secs, "attempt {attempt}");
        }
    }

    #[test]
    fn test_format_backoff_messages() {
        let (s1, d1) = format_backoff_messages(None, Duration::from_secs(90));
        assert!(s1.contains("90s"));
        assert!(d1.contains("90s"));
        let (s2, d2) = format_backoff_messages(
            Some("2023-01-01 00:00 UTC to 01:00 UTC"),
            Duration::from_secs(30),
        );
        assert!(s2.contains("30s"));
        assert!(d2.contains("Date range"));
    }
}
