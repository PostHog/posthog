//! Per-minute latency histograms: a statement's quantiles cost one row of counters
//! per minute however often it runs. Bucket `i` (0-based) covers
//! `[10^(i/20 - 2), 10^((i+1)/20 - 2))` ms, 20 per decade from 0.01 ms to 100 s, plus
//! an overflow bucket; bucket 0 also takes anything smaller. pgapi derives the same
//! edges in SQL from the array ordinal, so the two must move together.

pub const PER_DECADE: usize = 20;
pub const DECADES: usize = 7;
pub const BUCKETS: usize = PER_DECADE * DECADES + 1;
const MIN_EXPONENT: f64 = -2.0;

pub fn bucket_index(ms: f64) -> usize {
    if ms.is_nan() || ms <= 0.0 {
        return 0;
    }
    // Nudged so a duration on an exact edge (10000 ms with 20/decade) lands in the
    // bucket that starts there rather than the one below it.
    let x = ((ms.log10() - MIN_EXPONENT) * PER_DECADE as f64 + 1e-9).floor();
    x.clamp(0.0, (BUCKETS - 1) as f64) as usize
}

#[cfg(test)]
pub fn lower_edge_ms(i: usize) -> f64 {
    10f64.powf(i as f64 / PER_DECADE as f64 + MIN_EXPONENT)
}

/// Sampled and always-logged durations are counted apart: a sampled one stands for
/// 1/rate statements and an always-logged one for itself, and the two share a
/// bucket whenever `log_min_duration_statement` falls inside it.
#[derive(Debug, Clone, PartialEq)]
pub struct Histogram {
    pub sampled: Vec<i32>,
    pub logged: Vec<i32>,
    pub n: i64,
    pub sum_ms: f64,
    pub max_ms: f64,
}

impl Default for Histogram {
    fn default() -> Self {
        Self {
            sampled: vec![0; BUCKETS],
            logged: vec![0; BUCKETS],
            n: 0,
            sum_ms: 0.0,
            max_ms: 0.0,
        }
    }
}

impl Histogram {
    pub fn add(&mut self, ms: f64, always_logged: bool) {
        let counts = if always_logged {
            &mut self.logged
        } else {
            &mut self.sampled
        };
        counts[bucket_index(ms)] += 1;
        self.n += 1;
        self.sum_ms += ms;
        if ms > self.max_ms {
            self.max_ms = ms;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn edges_are_powers_of_ten_and_thresholds_land_on_them() {
        assert_eq!(bucket_index(0.0), 0);
        assert_eq!(bucket_index(0.005), 0);
        assert_eq!(bucket_index(0.01), 0);
        assert_eq!(bucket_index(9999.9), 119);
        assert_eq!(bucket_index(10000.0), 120);
        assert!((lower_edge_ms(120) - 10000.0).abs() < 1e-6);
        assert_eq!(bucket_index(1e9), BUCKETS - 1);
        assert_eq!(bucket_index(f64::NAN), 0);
    }

    #[test]
    fn histogram_accumulates() {
        let mut h = Histogram::default();
        for ms in [0.4, 0.5] {
            h.add(ms, false);
        }
        h.add(250.0, true);
        assert_eq!(h.n, 3);
        assert_eq!(h.max_ms, 250.0);
        assert_eq!(h.sampled.iter().sum::<i32>(), 2);
        assert_eq!(h.logged[bucket_index(250.0)], 1);
    }
}
