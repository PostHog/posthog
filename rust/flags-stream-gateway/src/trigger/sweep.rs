//! ETag sweep — the correctness backbone (plan §2.7).
//!
//! Once per `sweep_interval`, for each kind on the tier, read the companion
//! ETags of every currently-subscribed topic in ~100-key MGET batches and drive
//! the state machine. Trigger load scales with subscribed teams, not all teams,
//! because [`TopicRegistry::subscribed_topics`] is the input. A batch read failure
//! is skipped and repaired on the next tick; a value that fails to parse is
//! counted as `decode_error` and never touches the state machine.

use std::str::FromStr;
use std::sync::Arc;
use std::time::{Duration, Instant};

use common_hypercache::KeyType;
use lifecycle::Handle;
use rand::Rng;
use tokio::time::{interval, MissedTickBehavior};

use crate::domain::{Etag, Observation, Topic};
use crate::metrics;
use crate::registry::TopicRegistry;
use crate::trigger::{apply_observation, record_decode_error, Tier, TriggerSource};

/// Keys per MGET. HyperCache etag reads are tiny, so this bounds the pipelined
/// round trip without materializing an unbounded key list.
const SWEEP_CHUNK: usize = 100;

/// Registry GC cadence, in sweep ticks (~30 s at the default 1 s interval).
///
/// GC is not just about map growth: a receiver-less topic retains its last
/// `VersionState`, and the sweep skips it (no receivers ⇒ not swept), so a later
/// resubscribe would read a STALE non-null init beacon — an old etag the client
/// dutifully refetches against. Removing the entry restores the plan's model:
/// a fresh topic is `Unknown` (null) until the next sweep tick observes it.
/// `gc()` is global, cheap, and idempotent, so both tier loops calling it is fine.
const GC_EVERY_TICKS: u32 = 30;

/// Run the sweep loop for one tier until shutdown.
pub async fn run_sweep(
    handle: Handle,
    registry: Arc<TopicRegistry>,
    tier: Tier,
    sweep_interval: Duration,
) {
    let _scope = handle.process_scope();

    // Jitter the first tick per pod so N pods do not sweep in lockstep (plan §2.7).
    let first_delay_ms = {
        let mut rng = rand::thread_rng();
        rng.gen_range(0..sweep_interval.as_millis().max(1) as u64)
    };
    tokio::select! {
        _ = tokio::time::sleep(Duration::from_millis(first_delay_ms)) => {}
        _ = handle.shutdown_recv() => return,
    }

    let mut ticker = interval(sweep_interval);
    // A slow batch must not stampede catch-up ticks afterwards.
    ticker.set_missed_tick_behavior(MissedTickBehavior::Skip);

    let mut ticks_since_gc = 0u32;
    loop {
        tokio::select! {
            _ = handle.shutdown_recv() => return,
            _ = ticker.tick() => {
                sweep_once(&registry, &tier).await;
                maybe_gc(&registry, &mut ticks_since_gc);
                // Report health each tick so a stalled sweep is visible; the sweep
                // is the correctness backbone (plan §2.7, §2.11).
                handle.report_healthy();
            }
        }
    }
}

/// Run registry GC every [`GC_EVERY_TICKS`] calls (see the constant's doc for
/// why this is a correctness fix, not just hygiene).
fn maybe_gc(registry: &TopicRegistry, ticks_since_gc: &mut u32) {
    *ticks_since_gc += 1;
    if *ticks_since_gc >= GC_EVERY_TICKS {
        *ticks_since_gc = 0;
        registry.gc();
    }
}

/// One full sweep pass across every kind on the tier.
async fn sweep_once(registry: &TopicRegistry, tier: &Tier) {
    for &kind in &tier.kinds {
        let Some(reader) = tier.readers.get(&kind) else {
            continue;
        };

        let topics: Vec<Topic> = registry
            .subscribed_topics()
            .into_iter()
            .filter(|topic| topic.kind == kind)
            .collect();
        metrics::subscribed_topics(kind, topics.len());

        for chunk in topics.chunks(SWEEP_CHUNK) {
            let keys: Vec<KeyType> = chunk
                .iter()
                .map(|topic| KeyType::int(topic.team_id))
                .collect();

            let started = Instant::now();
            match reader.get_etags_batch(&keys).await {
                Ok(values) => {
                    metrics::sweep_batch_ms(kind, started.elapsed().as_secs_f64() * 1000.0);
                    for (topic, value) in chunk.iter().zip(values) {
                        match value {
                            None => {
                                apply_observation(
                                    registry,
                                    *topic,
                                    Observation::Absent,
                                    TriggerSource::Sweep,
                                );
                            }
                            Some(raw) => match Etag::from_str(&raw) {
                                Ok(etag) => {
                                    apply_observation(
                                        registry,
                                        *topic,
                                        Observation::Present(etag),
                                        TriggerSource::Sweep,
                                    );
                                }
                                Err(_) => record_decode_error(kind, TriggerSource::Sweep),
                            },
                        }
                    }
                }
                Err(e) => {
                    // Skip this batch; the next tick repairs it (plan §2.7).
                    tracing::warn!(
                        tier = tier.name,
                        kind = kind.wire_name(),
                        error = %e,
                        "sweep batch read failed; retrying next tick"
                    );
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{CacheKind, VersionState};

    // The regression maybe_gc exists to prevent: without GC, a receiver-less
    // topic keeps its last Known state and a later resubscribe reads a stale
    // non-null init beacon instead of Unknown.
    #[test]
    fn maybe_gc_clears_stale_state_on_cadence() {
        let registry = TopicRegistry::new();
        let topic = Topic {
            team_id: 1,
            kind: CacheKind::Definitions,
        };
        let rx = registry.subscribe(topic);
        registry.apply(
            topic,
            Observation::Present("0123456789abcdef".parse().expect("valid etag")),
        );
        drop(rx);

        let mut ticks = 0u32;
        for _ in 0..GC_EVERY_TICKS - 1 {
            maybe_gc(&registry, &mut ticks);
        }
        assert_eq!(registry.topic_count(), 1, "no GC before the cadence");

        maybe_gc(&registry, &mut ticks);
        assert_eq!(registry.topic_count(), 0, "GC fires on the cadence tick");
        assert_eq!(ticks, 0, "counter resets after GC");

        // A resubscribe now reads Unknown (null beacon), not the stale etag.
        let rx = registry.subscribe(topic);
        assert_eq!(*rx.borrow(), VersionState::Unknown);
    }
}
