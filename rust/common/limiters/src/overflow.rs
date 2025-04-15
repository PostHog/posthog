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

    // event_key is the candidate partition key for the outbound event. It is either
    // "<token>:<distinct_id>" for std events or "<token>:<ip_addr>" for cookieless.
    // If this method returns true, the event should be rerouted to the overflow topic
    // without a partition key, to avoid hot partitions in that pipeline.
    pub fn is_limited(&self, event_key: &String, token: &str) -> bool {
        // is the token or full event key in the forced_keys list?
        let forced_key_match = self.forced_keys.contains(event_key);
        let forced_token_match = self.forced_keys.contains(token);

        // should rate limiting be triggered for this event?
        let limiter_by_key = self.limiter.check_key(event_key).is_err();

        forced_key_match || forced_token_match || limiter_by_key
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
    use super::OverflowLimiter;
    use std::num::NonZeroU32;

    #[tokio::test]
    async fn low_limits() {
        let limiter = OverflowLimiter::new(
            NonZeroU32::new(1).unwrap(),
            NonZeroU32::new(1).unwrap(),
            None,
        );
        let token = "test";
        let distinct_id = "user1";
        let key = format!("{}:{}", token, distinct_id);

        assert!(!limiter.is_limited(&key, token));
        assert!(limiter.is_limited(&key, token));
    }

    #[tokio::test]
    async fn bursting() {
        let limiter = OverflowLimiter::new(
            NonZeroU32::new(1).unwrap(),
            NonZeroU32::new(3).unwrap(),
            None,
        );
        let token = "test";
        let distinct_id = "user1";
        let key = format!("{}:{}", token, distinct_id);

        assert!(!limiter.is_limited(&key, token));
        assert!(!limiter.is_limited(&key, token));
        assert!(!limiter.is_limited(&key, token));
        assert!(limiter.is_limited(&key, token));
    }

    #[tokio::test]
    async fn forced_key() {
        let token1 = "token1";
        let dist_id1 = "user1";
        let key1 = format!("{}:{}", token1, dist_id1);
        let token2 = "token2";
        let dist_id2 = "user2";
        let key2 = format!("{}:{}", token2, dist_id2);

        // replicate the above in forced_keys list
        let forced_keys = Some(format!("{},{}", key1, key2));
        let limiter = OverflowLimiter::new(
            NonZeroU32::new(1).unwrap(),
            NonZeroU32::new(1).unwrap(),
            forced_keys,
        );

        // token1:user1 and token2:user2 are limited from the start, token3:user3 is not
        assert!(limiter.is_limited(&key1, token1));
        assert!(!limiter.is_limited(&String::from("token3:user3"), "token3"));
        assert!(limiter.is_limited(&key2, token2));

        // token3:user3 is limited on the second event
        assert!(limiter.is_limited(&String::from("token3:user3"), "token3"));
    }

    #[tokio::test]
    async fn test_optional_distinct_id() {
        let token1 = "token1";
        let dist_id1 = "user1";
        let key1 = format!("{}:{}", token1, dist_id1);
        let token2 = "token2";
        let dist_id2 = "user2";
        let key2 = format!("{}:{}", token2, dist_id2);
        let token3 = "token3";
        let dist_id3 = "user3";
        let key3 = format!("{}:{}", token3, dist_id3);

        let limiter = OverflowLimiter::new(
            NonZeroU32::new(1).unwrap(),
            NonZeroU32::new(1).unwrap(),
            Some(format!("{},{}", token1, key2)),
        );

        // token1 is limited for all distinct_ids
        assert!(limiter.is_limited(&key1, token1));
        assert!(limiter.is_limited(&format!("{}:{}", token1, "other_user"), token1));
        assert!(limiter.is_limited(&token1.to_string(), token1));

        // token2:user2 is limited only for that specific user
        assert!(limiter.is_limited(&key2, token2));
        assert!(!limiter.is_limited(&format!("{}:{}", token2, "other_user"), token2));

        // token3 gets rate limited normally
        assert!(!limiter.is_limited(&key3, token3));
        assert!(limiter.is_limited(&key3, token3)); // Second hit is limited
    }
}
