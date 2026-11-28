//! Read-only leader mode: the leader's cache, kept current by consuming the changelog
//! instead of producing it. A follower answers reads from that cache and holds no fence.

pub mod freshness;
pub mod handler;

use std::sync::{Arc, Mutex, PoisonError};
use std::time::{Duration, Instant};

use dashmap::DashMap;
use metrics::{counter, gauge, Gauge};
use personhog_coordination::changelog::{warm_sources, WarmSource};
use personhog_coordination::error::{Error as CoordError, Result as CoordResult};
use personhog_coordination::types::ChangelogConfig;
use tokio::task::AbortHandle;

use crate::cache::{CacheLookup, CachedPerson, PartitionedCache, PersonCacheKey};
use crate::warming::{
    end_offset, follow_source, warm_from_sources, WarmClientPools, WarmingConfig,
};
use freshness::Freshness;

#[derive(Debug, Clone, Copy)]
pub struct FollowConfig {
    /// A partition not confirmed current within this long answers no reads.
    pub staleness_threshold: Duration,
    pub end_check_interval: Duration,
}

/// Why a follower has no answer for a read. The caller reads Postgres instead.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Unanswered {
    /// The partition is not followed here under the caller's changelog config.
    NotFollowed,
    /// The partition is followed and is not confirmed current.
    NotCurrent,
    /// The cache holds no changelog record of the person.
    NotCached,
}

impl Unanswered {
    pub fn label(self) -> &'static str {
        match self {
            Self::NotFollowed => "not_followed",
            Self::NotCurrent => "not_current",
            Self::NotCached => "not_cached",
        }
    }
}

struct Followed {
    /// The changelog config epoch the partition was built under.
    epoch: u64,
    freshness: Arc<Mutex<Freshness>>,
    /// Set by a release. The reader applies each record under it, so no record lands in
    /// the cache after the release has cleared it.
    released: Arc<Mutex<bool>>,
    task: AbortHandle,
}

pub struct Follower {
    cfg: FollowConfig,
    warming: WarmingConfig,
    pools: Arc<WarmClientPools>,
    cache: Arc<PartitionedCache>,
    followed: DashMap<u32, Followed>,
}

impl Follower {
    pub fn new(
        cfg: FollowConfig,
        warming: WarmingConfig,
        pools: Arc<WarmClientPools>,
        cache: Arc<PartitionedCache>,
    ) -> Self {
        Self {
            cfg,
            warming,
            pools,
            cache,
            followed: DashMap::new(),
        }
    }

    /// Build the partition with the leader's warm, then keep applying the live changelog
    /// from where the warm stopped. Returns once the partition is current.
    ///
    /// The warm starts at the writer's position, so the cache holds every record Postgres
    /// may not have yet. Callers run one build of a partition at a time.
    pub async fn follow(&self, partition: u32, config: &ChangelogConfig) -> CoordResult<()> {
        self.release(partition);
        let mut sources = warm_sources(config, partition);
        let range = warm_from_sources(
            &self.warming,
            &self.pools,
            &self.cache,
            None,
            partition,
            &sources,
            false,
        )
        .await?;
        let live = sources
            .pop()
            .ok_or_else(|| CoordError::invalid_state("a warm has no live source".to_string()))?;

        let freshness = Arc::new(Mutex::new(Freshness::default()));
        lock(&freshness).advance(range.end);
        let released = Arc::new(Mutex::new(false));
        let task = tokio::spawn(keep_current(
            self.cfg,
            self.warming.clone(),
            Arc::clone(&self.pools),
            Arc::clone(&self.cache),
            partition,
            live,
            range.end,
            Arc::clone(&freshness),
            Arc::clone(&released),
        ));
        let followed = Followed {
            epoch: config.epoch,
            freshness,
            released,
            task: task.abort_handle(),
        };
        self.followed.insert(partition, followed);
        // The pod records a warm only once this returns, and never releases one it did
        // not record, so a caller that gives up must not leave the partition followed.
        let mut abandoned = Abandoned {
            follower: self,
            partition,
            armed: true,
        };

        // A changelog end that cannot be confirmed is a stalled warm, as a quiet read is.
        let deadline = Instant::now() + self.warming.recv_timeout;
        while !self.is_current(partition) {
            if task.is_finished() {
                return Err(CoordError::invalid_state(format!(
                    "partition {partition} stopped following before it was current"
                )));
            }
            if Instant::now() >= deadline {
                return Err(CoordError::invalid_state(format!(
                    "partition {partition} was not confirmed current within {:?}",
                    self.warming.recv_timeout
                )));
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        abandoned.armed = false;
        Ok(())
    }

    /// Stop following and drop the partition's cache.
    pub fn release(&self, partition: u32) {
        if let Some((_, followed)) = self.followed.remove(&partition) {
            let mut released = gate(&followed.released);
            *released = true;
            followed.task.abort();
            // Under the gate, so the reader cannot report after this.
            LagGauges::of(partition).reset();
        }
        self.cache.drop_partition(partition);
    }

    /// Stop following every partition.
    pub fn release_all(&self) {
        let followed: Vec<u32> = self.followed.iter().map(|entry| *entry.key()).collect();
        for partition in followed {
            self.release(partition);
        }
    }

    /// The person as the changelog last had them; a deleted person is their death
    /// document. Postgres has every person a current partition does not hold, unless the
    /// writer is further behind than the cache reaches back.
    ///
    /// `epoch` is the changelog config epoch the caller chose the partition under. A
    /// partition built under another one holds another layout: it has read all of a
    /// sealed topic, so it looks current, and it answers nothing until it is rebuilt.
    pub fn read(
        &self,
        partition: u32,
        key: &PersonCacheKey,
        epoch: u64,
    ) -> Result<CachedPerson, Unanswered> {
        let built_under = self.followed.get(&partition).map(|followed| followed.epoch);
        if built_under != Some(epoch) {
            return Err(Unanswered::NotFollowed);
        }
        if !self.is_current(partition) {
            return Err(Unanswered::NotCurrent);
        }
        match self.cache.get(partition, key) {
            CacheLookup::Found(person) => Ok(person),
            CacheLookup::PersonNotFound => Err(Unanswered::NotCached),
            CacheLookup::PartitionNotOwned => Err(Unanswered::NotFollowed),
        }
    }

    /// Whether the partition is still being kept current, however far behind it is.
    pub fn is_following(&self, partition: u32) -> bool {
        self.followed
            .get(&partition)
            .is_some_and(|followed| !followed.task.is_finished())
    }

    /// Whether the partition held every committed changelog record within the threshold.
    pub fn is_current(&self, partition: u32) -> bool {
        self.followed.get(&partition).is_some_and(|followed| {
            lock(&followed.freshness).is_current(Instant::now(), self.cfg.staleness_threshold)
        })
    }
}

struct Abandoned<'a> {
    follower: &'a Follower,
    partition: u32,
    armed: bool,
}

impl Drop for Abandoned<'_> {
    fn drop(&mut self) {
        if self.armed {
            self.follower.release(self.partition);
        }
    }
}

/// How far behind a followed partition is. A pod that released the partition reports
/// zero, so its last reading does not stand beside the new owner's.
struct LagGauges {
    offsets_behind: Gauge,
    confirmed_age_ms: Gauge,
}

impl LagGauges {
    fn of(partition: u32) -> Self {
        Self {
            offsets_behind: gauge!(
                "personhog_follower_offsets_behind",
                "partition" => partition.to_string()
            ),
            confirmed_age_ms: gauge!(
                "personhog_follower_confirmed_age_ms",
                "partition" => partition.to_string()
            ),
        }
    }

    fn reset(&self) {
        self.offsets_behind.set(0.0);
        self.confirmed_age_ms.set(0.0);
    }
}

fn lock(freshness: &Mutex<Freshness>) -> std::sync::MutexGuard<'_, Freshness> {
    freshness.lock().unwrap_or_else(PoisonError::into_inner)
}

fn gate(released: &Mutex<bool>) -> std::sync::MutexGuard<'_, bool> {
    released.lock().unwrap_or_else(PoisonError::into_inner)
}

fn apply(cache: &PartitionedCache, partition: u32, person: CachedPerson, released: &Mutex<bool>) {
    let released = gate(released);
    if *released {
        return;
    }
    let key = PersonCacheKey {
        team_id: person.team_id,
        person_id: person.id,
    };
    cache.put_if_newer(partition, key, person);
}

#[allow(clippy::too_many_arguments)]
async fn keep_current(
    cfg: FollowConfig,
    warming: WarmingConfig,
    pools: Arc<WarmClientPools>,
    cache: Arc<PartitionedCache>,
    partition: u32,
    live: WarmSource,
    start: i64,
    freshness: Arc<Mutex<Freshness>>,
    released: Arc<Mutex<bool>>,
) {
    let follow = follow_source(
        &warming,
        &pools,
        &live,
        start,
        |_offset, person| apply(&cache, partition, person, &released),
        |position| lock(&freshness).advance(position),
    );
    let confirm = async {
        let lag = LagGauges::of(partition);
        let mut tick = tokio::time::interval(cfg.end_check_interval);
        // After a slow check the missed ones are skipped, not fired in a burst.
        tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        loop {
            tick.tick().await;
            // The stall rule of a bounded read, for a reader with no fixed end.
            if lock(&freshness).stalled(Instant::now(), warming.recv_timeout) {
                return;
            }
            let asked_at = Instant::now();
            let mut behind = None;
            match end_offset(&warming, &pools, &live).await {
                Ok(end) => {
                    let mut freshness = lock(&freshness);
                    freshness.observe_end(asked_at, end);
                    behind = Some(freshness.behind(end));
                }
                Err(e) => {
                    counter!(
                        "personhog_follower_end_checks_failed_total",
                        "partition" => partition.to_string()
                    )
                    .increment(1);
                    tracing::warn!(partition, error = %e, "changelog end check failed");
                }
            }
            let confirmed_age = lock(&freshness).confirmed_age(Instant::now());
            let released = gate(&released);
            if !*released {
                if let Some(behind) = behind {
                    lag.offsets_behind.set(behind as f64);
                }
                if let Some(age) = confirmed_age {
                    lag.confirmed_age_ms.set(age.as_secs_f64() * 1000.0);
                }
            }
        }
    };
    tokio::select! {
        result = follow => {
            counter!(
                "personhog_follower_stopped_total",
                "partition" => partition.to_string()
            )
            .increment(1);
            tracing::error!(partition, error = ?result.err(), "stopped following the changelog");
        }
        () = confirm => {
            counter!(
                "personhog_follower_stopped_total",
                "partition" => partition.to_string()
            )
            .increment(1);
            tracing::error!(partition, "the changelog reader stalled short of the log's end");
        }
    }
}

#[cfg(test)]
mod tests {
    use personhog_proto::personhog::types::v1::Person;

    use super::*;

    #[test]
    fn a_record_applied_after_a_release_leaves_nothing_behind() {
        let cache = PartitionedCache::new(1 << 20);
        cache.begin_warm_partition(0);
        cache.publish_warmed_partition(0);
        let person = CachedPerson::try_from(Person {
            id: 7,
            team_id: 1,
            uuid: "00000000-0000-0000-0000-000000000007".to_string(),
            properties: b"{}".to_vec(),
            version: 3,
            ..Default::default()
        })
        .expect("a valid person");
        let key = PersonCacheKey {
            team_id: 1,
            person_id: 7,
        };

        let released = Mutex::new(true);
        apply(&cache, 0, person, &released);

        assert!(matches!(cache.get(0, &key), CacheLookup::PersonNotFound));
    }
}
