//! Kafka layer: the per-tile rate limiter that paces produce throughput. Depends only on the shared
//! metric-name constants.

use std::num::NonZeroU32;
use std::sync::Arc;
use std::time::Instant;

use governor::clock::DefaultClock;
use governor::state::{InMemoryState, NotKeyed};
use governor::{Quota, RateLimiter};
use metrics::histogram;

use crate::observability::metrics::PACER_WAIT_SECONDS;

type DirectLimiter = RateLimiter<NotKeyed, InMemoryState, DefaultClock>;

#[derive(Clone)]
pub struct TilePacer {
    limiter: Arc<DirectLimiter>,
}

impl TilePacer {
    pub fn new(tiles_per_second: NonZeroU32) -> Self {
        let quota = Quota::per_second(tiles_per_second).allow_burst(NonZeroU32::MIN);
        Self {
            limiter: Arc::new(RateLimiter::direct(quota)),
        }
    }

    pub async fn until_ready(&self) {
        let started_at = Instant::now();
        self.limiter.until_ready().await;
        histogram!(PACER_WAIT_SECONDS).record(started_at.elapsed().as_secs_f64());
    }
}
