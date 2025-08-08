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

    /// Default policy: initial 60s, multiplier 2.0, max 1h
    pub const fn default_long() -> Self {
        Self {
            initial_delay: Duration::from_secs(60),
            multiplier: 2.0,
            max_delay: Duration::from_secs(60 * 60),
        }
    }
}

/// Compute the next backoff delay for a given attempt, capped at policy.max_delay.
///
/// attempt = 0 => initial_delay
/// attempt = n => initial_delay * multiplier^n
pub fn compute_next_delay(attempt: u32, policy: BackoffPolicy) -> Duration {
    // Work in whole seconds for simplicity and determinism.
    let base_secs = policy.initial_delay.as_secs_f64();
    let pow = policy.multiplier.powi(attempt as i32);
    let scaled_secs = (base_secs * pow).round();

    let scaled = if scaled_secs.is_finite() && scaled_secs > 0.0 {
        let secs_u64 = scaled_secs.min(u64::MAX as f64).max(0.0) as u64;
        Duration::from_secs(secs_u64)
    } else {
        policy.max_delay
    };

    scaled.min(policy.max_delay)
}

/// Convenience: given current attempt, return (next_attempt, delay_for_next_attempt)
/// E.g. if current_attempt = 0, we return (1, initial_delay)
pub fn next_attempt_and_delay(current_attempt: u32, policy: BackoffPolicy) -> (u32, Duration) {
    let next_attempt = current_attempt.saturating_add(1);
    let delay = compute_next_delay(current_attempt, policy);
    (next_attempt, delay)
}

/// Build operator/developer status_message and user-facing display message.
/// If a date range is provided, include it in the display message.
pub fn format_backoff_messages(date_range: Option<&str>, delay: Duration) -> (String, String) {
    let secs = delay.as_secs();
    let status = format!(
        "Rate limited (429). Scheduling retry in {}s. Waiting before next attempt.",
        secs
    );
    let display = match date_range {
        Some(dr) => format!(
            "Rate limit hit. Will retry in {}s. Date range: {}",
            secs, dr
        ),
        None => format!("Rate limit hit. Will retry in {}s.", secs),
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
            let d = compute_next_delay(attempt, p);
            assert_eq!(d.as_secs(), expected_secs, "attempt {}", attempt);
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
            let d = compute_next_delay(attempt, p);
            assert_eq!(d.as_secs(), expected_secs, "attempt {}", attempt);
        }
    }

    #[test]
    fn test_next_attempt_and_delay() {
        let p = BackoffPolicy::new(Duration::from_secs(10), 2.0, Duration::from_secs(1000));
        let (a1, d1) = next_attempt_and_delay(0, p);
        assert_eq!(a1, 1);
        assert_eq!(d1.as_secs(), 10);
        let (a2, d2) = next_attempt_and_delay(a1, p);
        assert_eq!(a2, 2);
        assert_eq!(d2.as_secs(), 20);
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
