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
        let secs_u64 = scaled_secs
            .min(u64::MAX as f64)
            .max(0.0) as u64;
        Duration::from_secs(secs_u64)
    } else {
        policy.max_delay
    };

    scaled.min(policy.max_delay)
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
}


