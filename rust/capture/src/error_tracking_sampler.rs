//! Error tracking dual-write sampler.
//!
//! This module provides static configuration for error tracking dual-write rollout,
//! initialized once at startup from environment variables.

use std::sync::OnceLock;

use rand::Rng;

/// Configuration for error tracking dual-write rollout.
struct DualWriteConfig {
    enabled: bool,
    sample_rate: f64, // 0.0 to 100.0
}

static DUAL_WRITE_CONFIG: OnceLock<DualWriteConfig> = OnceLock::new();

/// Initialize dual-write configuration at startup.
///
/// Call this once from main() with values from environment config.
pub fn init_dual_write(enabled: bool, sample_rate: f64) {
    let _ = DUAL_WRITE_CONFIG.set(DualWriteConfig {
        enabled,
        sample_rate: sample_rate.clamp(0.0, 100.0),
    });
}

/// Check if error tracking dual-write should happen for this event.
///
/// Returns true if:
/// - Dual-write is enabled AND
/// - Random sample passes the configured rate
///
/// Returns false if not initialized or disabled.
pub fn should_dual_write_error_tracking() -> bool {
    let Some(config) = DUAL_WRITE_CONFIG.get() else {
        return false;
    };

    if !config.enabled {
        return false;
    }

    if config.sample_rate >= 100.0 {
        return true;
    }

    if config.sample_rate <= 0.0 {
        return false;
    }

    rand::thread_rng().gen_range(0.0..100.0) < config.sample_rate
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sample_rate_clamping() {
        let config = DualWriteConfig {
            enabled: true,
            sample_rate: 150.0_f64.clamp(0.0, 100.0),
        };
        assert_eq!(config.sample_rate, 100.0);

        let config = DualWriteConfig {
            enabled: true,
            sample_rate: (-10.0_f64).clamp(0.0, 100.0),
        };
        assert_eq!(config.sample_rate, 0.0);
    }
}
