//! Per-partition live-consumption watermarks — the seed apply-fence's input.
//!
//! The running max of broker timestamps the partition worker has **folded**, advanced only
//! post-mark so unfolded events can never open the fence early; idle partitions advance via the
//! seed consumer's probe. Absent entries are fail-closed.

use dashmap::DashMap;

/// A live watermark instant (epoch ms, broker CreateTime ≈ arrival).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct WatermarkMs(pub i64);

/// Monotonic per-partition watermark map.
#[derive(Debug, Default)]
pub struct LiveWatermarks {
    partitions: DashMap<i32, i64>,
}

impl LiveWatermarks {
    pub fn new() -> Self {
        Self::default()
    }

    /// Fold-frontier advance; running max because broker CreateTime is not per-partition
    /// monotonic across shuffler replicas.
    pub fn observe(&self, partition: i32, broker_ts_ms: i64) {
        self.advance(partition, broker_ts_ms);
    }

    /// Idle advance: everything retained is folded, so "now" is a valid arrival bound.
    pub fn advance_idle(&self, partition: i32, now_ms: i64) {
        self.advance(partition, now_ms);
    }

    /// `None` = never observed (fail-closed for the fence).
    pub fn get(&self, partition: i32) -> Option<WatermarkMs> {
        self.partitions
            .get(&partition)
            .map(|entry| WatermarkMs(*entry))
    }

    pub fn forget_partition(&self, partition: i32) {
        self.partitions.remove(&partition);
    }

    fn advance(&self, partition: i32, candidate_ms: i64) {
        let mut entry = self.partitions.entry(partition).or_insert(candidate_ms);
        *entry = (*entry).max(candidate_ms);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn watermark_is_a_running_max_across_observe_and_idle_advances() {
        let watermarks = LiveWatermarks::new();
        assert_eq!(
            watermarks.get(5),
            None,
            "fail-closed before any observation"
        );

        watermarks.observe(5, 1_000);
        assert_eq!(watermarks.get(5), Some(WatermarkMs(1_000)));

        // Out-of-order broker timestamps (multiple shuffler replicas) never regress it.
        watermarks.observe(5, 900);
        assert_eq!(watermarks.get(5), Some(WatermarkMs(1_000)));

        watermarks.advance_idle(5, 2_000);
        assert_eq!(watermarks.get(5), Some(WatermarkMs(2_000)));
        watermarks.observe(5, 1_500);
        assert_eq!(watermarks.get(5), Some(WatermarkMs(2_000)));
    }

    #[test]
    fn forget_partition_returns_it_to_fail_closed() {
        let watermarks = LiveWatermarks::new();
        watermarks.observe(3, 1_000);
        watermarks.observe(4, 2_000);

        watermarks.forget_partition(3);

        assert_eq!(watermarks.get(3), None, "the next tenure re-derives");
        assert_eq!(watermarks.get(4), Some(WatermarkMs(2_000)), "others keep");
    }
}
