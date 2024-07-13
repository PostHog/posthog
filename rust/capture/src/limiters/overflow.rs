/// The analytics ingestion pipeline provides ordering guarantees for events of the same
/// token and distinct_id. We currently achieve this through a locality constraint on the
/// Kafka partition (consistent partition hashing through a computed key).
///
/// Volume spikes to a given key can create lag on the destination partition and induce
/// ingestion lag. To protect the downstream systems, capture can relax this locality
/// constraint when bursts are detected. When that happens, the excess traffic will be
/// spread across all partitions and be processed by the overflow consumer, without
/// strict ordering guarantees.
use std::collections::HashSet;
use std::num::NonZeroU32;
use std::sync::Arc;

use governor::{clock, state::keyed::DefaultKeyedStateStore, Quota, RateLimiter};
use metrics::gauge;
use rand::Rng;

// See: https://docs.rs/governor/latest/governor/_guide/index.html#usage-in-multiple-threads
#[derive(Clone)]
pub struct OverflowLimiter {
    limiter: Arc<RateLimiter<String, DefaultKeyedStateStore<String>, clock::DefaultClock>>,
    forced_keys: HashSet<String>,
}

impl OverflowLimiter {
    pub fn new(per_second: NonZeroU32, burst: NonZeroU32, forced_keys: Option<String>) -> Self {
        let quota = Quota::per_second(per_second).allow_burst(burst);
        let limiter = Arc::new(governor::RateLimiter::dashmap(quota));

        let forced_keys: HashSet<String> = match forced_keys {
            None => HashSet::new(),
            Some(values) => values.split(',').map(String::from).collect(),
        };

        OverflowLimiter {
            limiter,
            forced_keys,
        }
    }

    pub fn is_limited(&self, key: &String) -> bool {
        self.forced_keys.contains(key) || self.limiter.check_key(key).is_err()
    }

    /// Reports the number of tracked keys to prometheus every 10 seconds,
    /// needs to be spawned in a separate task.
    pub async fn report_metrics(&self) {
        let mut interval = tokio::time::interval(tokio::time::Duration::from_secs(10));
        loop {
            interval.tick().await;
            gauge!("partition_limits_key_count").set(self.limiter.len() as f64);
        }
    }

    /// Clean up the rate limiter state, once per minute. Ensure we don't use more memory than
    /// necessary.
    pub async fn clean_state(&self) {
        // Give a small amount of randomness to the interval to ensure we don't have all replicas
        // locking at the same time. The lock isn't going to be held for long, but this will reduce
        // impact regardless.
        let interval_secs = rand::thread_rng().gen_range(60..70);

        let mut interval = tokio::time::interval(tokio::time::Duration::from_secs(interval_secs));
        loop {
            interval.tick().await;

            self.limiter.retain_recent();
            self.limiter.shrink_to_fit();
        }
    }
}

#[cfg(test)]
mod tests {
    use crate::limiters::overflow::OverflowLimiter;
    use std::num::NonZeroU32;

    #[tokio::test]
    async fn low_limits() {
        let limiter = OverflowLimiter::new(
            NonZeroU32::new(1).unwrap(),
            NonZeroU32::new(1).unwrap(),
            None,
        );
        let token = String::from("test");

        assert!(!limiter.is_limited(&token));
        assert!(limiter.is_limited(&token));
    }

    #[tokio::test]
    async fn bursting() {
        let limiter = OverflowLimiter::new(
            NonZeroU32::new(1).unwrap(),
            NonZeroU32::new(3).unwrap(),
            None,
        );
        let token = String::from("test");

        assert!(!limiter.is_limited(&token));
        assert!(!limiter.is_limited(&token));
        assert!(!limiter.is_limited(&token));
        assert!(limiter.is_limited(&token));
    }

    #[tokio::test]
    async fn forced_key() {
        let key_one = String::from("one");
        let key_two = String::from("two");
        let key_three = String::from("three");
        let forced_keys = Some(String::from("one,three"));

        let limiter = OverflowLimiter::new(
            NonZeroU32::new(1).unwrap(),
            NonZeroU32::new(1).unwrap(),
            forced_keys,
        );

        // One and three are limited from the start, two is not
        assert!(limiter.is_limited(&key_one));
        assert!(!limiter.is_limited(&key_two));
        assert!(limiter.is_limited(&key_three));

        // Two is limited on the second event
        assert!(limiter.is_limited(&key_two));
    }
}
