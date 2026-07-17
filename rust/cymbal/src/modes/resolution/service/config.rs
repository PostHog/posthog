use std::time::Duration;

/// Configuration handed to the gRPC service. Subset of the resolution-mode
/// [`crate::modes::resolution::Config`] that the handler actually needs;
/// isolating it lets tests construct the service without touching the env-var
/// surface.
#[derive(Clone, Debug)]
pub struct ServiceConfig {
    pub default_tick_interval: Duration,
    pub min_tick_interval: Duration,
    pub max_tick_interval: Duration,
}

impl From<&crate::modes::resolution::Config> for ServiceConfig {
    fn from(cfg: &crate::modes::resolution::Config) -> Self {
        Self {
            default_tick_interval: Duration::from_millis(cfg.subscribe_tick_interval_ms),
            min_tick_interval: Duration::from_millis(cfg.subscribe_min_tick_ms),
            max_tick_interval: Duration::from_millis(cfg.subscribe_max_tick_ms),
        }
    }
}

impl ServiceConfig {
    /// Resolve the effective tick cadence for a Subscribe stream given an
    /// optional caller hint. `0` means "use the server default"; other values
    /// are clamped to `[min, max]`.
    pub fn resolve_tick_interval(&self, hint_ms: u32) -> Duration {
        let candidate = if hint_ms == 0 {
            self.default_tick_interval
        } else {
            Duration::from_millis(hint_ms as u64)
        };
        let lo = self.min_tick_interval;
        let hi = self.max_tick_interval.max(lo);
        candidate.clamp(lo, hi)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_tick_interval_uses_default_when_hint_is_zero() {
        let cfg = ServiceConfig {
            default_tick_interval: Duration::from_millis(1000),
            min_tick_interval: Duration::from_millis(100),
            max_tick_interval: Duration::from_millis(5000),
        };
        assert_eq!(cfg.resolve_tick_interval(0), Duration::from_millis(1000));
    }

    #[test]
    fn resolve_tick_interval_clamps_hint_to_bounds() {
        let cfg = ServiceConfig {
            default_tick_interval: Duration::from_millis(1000),
            min_tick_interval: Duration::from_millis(100),
            max_tick_interval: Duration::from_millis(5000),
        };
        // Below the floor — clamped up.
        assert_eq!(cfg.resolve_tick_interval(10), Duration::from_millis(100));
        // Above the ceiling — clamped down.
        assert_eq!(
            cfg.resolve_tick_interval(60_000),
            Duration::from_millis(5000)
        );
        // Inside the band — taken as-is.
        assert_eq!(cfg.resolve_tick_interval(750), Duration::from_millis(750));
    }
}
