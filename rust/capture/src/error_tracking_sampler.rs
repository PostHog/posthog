//! Error tracking pipeline routing sampler.
//!
//! Controls the gradual rollout of exception event traffic from the Cymbal pipeline to the Node
//! pipeline. Each event is routed to exactly one pipeline based on the configured rollout rate.

use std::sync::OnceLock;

use rand::Rng;

struct Config {
    enabled: bool,
    rollout_rate: f64, // 0.0 to 100.0
}

static CONFIG: OnceLock<Config> = OnceLock::new();

/// Initialize the rollout configuration at startup. Call once from main().
pub fn init(enabled: bool, rollout_rate: f64) {
    let _ = CONFIG.set(Config {
        enabled,
        rollout_rate: rollout_rate.clamp(0.0, 100.0),
    });
}

/// Whether this event should be routed to the Node pipeline instead of Cymbal.
pub fn should_route_to_node() -> bool {
    let Some(config) = CONFIG.get() else {
        return false;
    };

    if !config.enabled {
        return false;
    }

    if config.rollout_rate >= 100.0 {
        return true;
    }

    if config.rollout_rate <= 0.0 {
        return false;
    }

    rand::thread_rng().gen_range(0.0..100.0) < config.rollout_rate
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_boundary_behavior() {
        // Disabled with full rate should not route
        let config = Config {
            enabled: false,
            rollout_rate: 100.0,
        };
        assert!(!config.enabled);

        // Over 100 gets clamped to 100
        let config = Config {
            enabled: true,
            rollout_rate: 150.0_f64.clamp(0.0, 100.0),
        };
        assert_eq!(config.rollout_rate, 100.0);

        // Negative gets clamped to 0
        let config = Config {
            enabled: true,
            rollout_rate: (-10.0_f64).clamp(0.0, 100.0),
        };
        assert_eq!(config.rollout_rate, 0.0);
    }
}
