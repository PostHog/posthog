//! Read-only leader mode: the leader's cache and pending index, kept current by consuming
//! the changelog instead of producing it. A follower serves reads and holds no fence.

pub mod freshness;
pub mod handler;

use std::future::Future;
use std::sync::{Arc, Mutex, PoisonError};
use std::time::{Duration, Instant};

use dashmap::DashMap;
use metrics::counter;
use personhog_coordination::changelog::{warm_sources, LiveChangelog, WarmSource};
use personhog_coordination::error::{Error as CoordError, Result as CoordResult};
use personhog_coordination::types::ChangelogConfig;
use tokio::task::AbortHandle;

use crate::cache::{
    CacheLookup, CachedPerson, DirtyIndex, DirtyMark, PartitionedCache, PersonCacheKey, Stream,
};
use crate::recovery::ChangelogRecovery;
use crate::settle::{prune_and_settle_after, retired_topic};
use crate::warming::{
    end_offset, follow_source, warm_from_sources, WarmClientPools, WarmingConfig,
};
use freshness::Freshness;

#[derive(Debug, Clone, Copy)]
pub struct FollowConfig {
    /// A partition not confirmed current within this long refuses reads.
    pub staleness_threshold: Duration,
    pub end_check_interval: Duration,
    /// A partition reports warm no sooner than this after its warm began. Misses load from
    /// a Postgres read replica, which must hold everything below the warm's start by then.
    pub min_warm: Duration,
}

/// Why a follower did not answer a read.
#[derive(Debug, PartialEq, Eq)]
pub enum ReadRefusal {
    /// The partition is not followed here, or is not confirmed current. Another owner may be.
    NotCurrent,
    /// The person has unapplied writes and their changelog record could not be fetched.
    Recovery(String),
    Load(String),
}

struct Followed {
    /// The changelog config epoch the partition was built under.
    epoch: u64,
    /// When the minimum warm time has passed; nothing is served before it.
    serves_from: Instant,
    freshness: Arc<Mutex<Freshness>>,
    /// Set by a release. The reader applies each record under it, so no record lands in
    /// the cache or the marks after the release has cleared them.
    released: Arc<Mutex<bool>>,
    task: AbortHandle,
}

pub struct Follower {
    cfg: FollowConfig,
    warming: WarmingConfig,
    pools: Arc<WarmClientPools>,
    cache: Arc<PartitionedCache>,
    dirty_index: Arc<DirtyIndex>,
    recovery: Arc<ChangelogRecovery>,
    followed: DashMap<u32, Followed>,
}

impl Follower {
    pub fn new(
        cfg: FollowConfig,
        warming: WarmingConfig,
        pools: Arc<WarmClientPools>,
        cache: Arc<PartitionedCache>,
        dirty_index: Arc<DirtyIndex>,
        recovery: Arc<ChangelogRecovery>,
    ) -> Self {
        Self {
            cfg,
            warming,
            pools,
            cache,
            dirty_index,
            recovery,
            followed: DashMap::new(),
        }
    }

    /// Build the partition with the leader's warm, then keep applying the live changelog
    /// from where the warm stopped. Returns once the partition is current.
    pub async fn follow(&self, partition: u32, config: &ChangelogConfig) -> CoordResult<()> {
        self.release(partition);
        let mut sources = warm_sources(config, partition);
        let range = warm_from_sources(
            &self.warming,
            &self.pools,
            &self.cache,
            &self.dirty_index,
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
            Arc::clone(&self.dirty_index),
            partition,
            live,
            range.end,
            Arc::clone(&freshness),
            Arc::clone(&released),
        ));
        let followed = Followed {
            epoch: config.epoch,
            // Counted from the end of the warm, which read the writer's position first.
            serves_from: Instant::now() + self.cfg.min_warm,
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

    /// Stop following and drop the partition's cache and marks.
    pub fn release(&self, partition: u32) {
        if let Some((_, followed)) = self.followed.remove(&partition) {
            *gate(&followed.released) = true;
            followed.task.abort();
        }
        self.cache.drop_partition(partition);
        self.dirty_index.clear_partition(partition);
    }

    /// The leader's read: a hit from the cache, a person with unapplied writes from the
    /// changelog, anyone else through `load`, which reads a Postgres read replica. `None`
    /// is a person that does not exist.
    ///
    /// `epoch` is the changelog config epoch the caller chose the partition under. A
    /// partition built under an older one holds the old layout: it has read all of a
    /// sealed topic, so it looks current, and it is refused until it is rebuilt. One built
    /// under a newer one is not the partition the caller meant.
    pub async fn read<F, Fut>(
        &self,
        partition: u32,
        key: &PersonCacheKey,
        epoch: u64,
        load: F,
    ) -> Result<Option<CachedPerson>, ReadRefusal>
    where
        F: FnOnce() -> Fut,
        Fut: Future<Output = Result<Option<CachedPerson>, String>>,
    {
        let build = self
            .followed
            .get(&partition)
            .map(|followed| (followed.epoch, Arc::clone(&followed.released)));
        let Some((built_under, build)) = build else {
            return Err(ReadRefusal::NotCurrent);
        };
        if built_under != epoch || !self.is_current(partition) {
            return Err(ReadRefusal::NotCurrent);
        }
        let mut found = self.cached(partition, key)?;
        if found.is_none() {
            match self.dirty_index.get(key) {
                Some(mark) => {
                    let recovered = self
                        .recovery
                        .fetch_person_at(&mark, key)
                        .await
                        .map_err(ReadRefusal::Recovery)?;
                    if !recovered.is_deleted {
                        return self.insert_fetched(partition, key, recovered, &build);
                    }
                    found = Some(recovered);
                }
                // A release drops the cache before its marks, so a partition still present
                // here had its marks intact when they were read.
                None => found = self.cached(partition, key)?,
            }
        }
        match found {
            Some(person) if !person.is_deleted => Ok(Some(person)),
            // As on the leader: a live Postgres row above a death document can only be a
            // person created again under the same id.
            Some(death) => match load().await.map_err(ReadRefusal::Load)? {
                Some(row) if row.version > death.version => {
                    self.insert_fetched(partition, key, row, &build)
                }
                _ => self.absent(partition, key, Some(death.version), &build),
            },
            None => match load().await.map_err(ReadRefusal::Load)? {
                Some(person) => self.insert_fetched(partition, key, person, &build),
                None => self.absent(partition, key, None, &build),
            },
        }
    }

    /// Cache and serve a person fetched across an await. The partition may have been
    /// rebuilt since, and a newer write may have been applied and evicted; the build's
    /// gate keeps both out while this looks, as it does for the reader's applies.
    fn insert_fetched(
        &self,
        partition: u32,
        key: &PersonCacheKey,
        person: CachedPerson,
        build: &Mutex<bool>,
    ) -> Result<Option<CachedPerson>, ReadRefusal> {
        let released = gate(build);
        if *released {
            return Err(ReadRefusal::NotCurrent);
        }
        let superseded = self
            .dirty_index
            .get(key)
            .is_some_and(|mark| mark.version > person.version);
        if !superseded
            && self
                .cache
                .put_if_newer(partition, key.clone(), person.clone())
        {
            return Ok(living(person));
        }
        match self.cached(partition, key)? {
            Some(newer) => Ok(living(newer)),
            None => Err(ReadRefusal::NotCurrent),
        }
    }

    /// Answer "does not exist" for a person Postgres did not have, unless they were
    /// written while it was asked. `death` is the version of the death document that was
    /// already known, whose own mark is not a later write.
    fn absent(
        &self,
        partition: u32,
        key: &PersonCacheKey,
        death: Option<i64>,
        build: &Mutex<bool>,
    ) -> Result<Option<CachedPerson>, ReadRefusal> {
        let released = gate(build);
        if *released {
            return Err(ReadRefusal::NotCurrent);
        }
        if let Some(written) = self.cached(partition, key)? {
            return Ok(living(written));
        }
        let written_since = self
            .dirty_index
            .get(key)
            .is_some_and(|mark| death.is_none_or(|death| mark.version > death));
        if written_since {
            return Err(ReadRefusal::NotCurrent);
        }
        Ok(None)
    }

    fn cached(
        &self,
        partition: u32,
        key: &PersonCacheKey,
    ) -> Result<Option<CachedPerson>, ReadRefusal> {
        match self.cache.get(partition, key) {
            CacheLookup::Found(person) => Ok(Some(person)),
            CacheLookup::PersonNotFound => Ok(None),
            CacheLookup::PartitionNotOwned => Err(ReadRefusal::NotCurrent),
        }
    }

    /// Whether the partition is still being kept current, however far behind it is.
    pub fn is_following(&self, partition: u32) -> bool {
        self.followed
            .get(&partition)
            .is_some_and(|followed| !followed.task.is_finished())
    }

    /// Clear the marks of records the writer has applied, forever. `grace` is longer than
    /// the read replica can lag, so a person is unmarked only once the replica holds them.
    pub async fn clear_applied_marks(
        &self,
        changelog: LiveChangelog,
        interval: Duration,
        grace: Duration,
    ) {
        // The settle takes a per-person lock from this map; a follower has no other holder.
        let locks = DashMap::new();
        let mut tick = tokio::time::interval(interval);
        loop {
            tick.tick().await;
            prune_and_settle_after(
                grace,
                &self.dirty_index,
                &self.cache,
                &locks,
                &self.pools,
                self.warming.committed_offsets_timeout,
                |topic| {
                    retired_topic(
                        &changelog.current(),
                        &self.warming.writer_consumer_group,
                        topic,
                    )
                },
            )
            .await;
        }
    }

    /// Whether the partition may serve: its minimum warm time has passed and it held
    /// every committed changelog record within the threshold.
    pub fn is_current(&self, partition: u32) -> bool {
        self.followed.get(&partition).is_some_and(|followed| {
            let now = Instant::now();
            now >= followed.serves_from
                && lock(&followed.freshness).is_current(now, self.cfg.staleness_threshold)
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

/// A cached death document is a person that no longer exists.
fn living(person: CachedPerson) -> Option<CachedPerson> {
    (!person.is_deleted).then_some(person)
}

fn lock(freshness: &Mutex<Freshness>) -> std::sync::MutexGuard<'_, Freshness> {
    freshness.lock().unwrap_or_else(PoisonError::into_inner)
}

fn gate(released: &Mutex<bool>) -> std::sync::MutexGuard<'_, bool> {
    released.lock().unwrap_or_else(PoisonError::into_inner)
}

/// Mark first, as the warm does: a miss must never find the cache behind an unmarked person.
fn apply(
    cache: &PartitionedCache,
    dirty_index: &DirtyIndex,
    partition: u32,
    stream: &Stream,
    offset: i64,
    person: CachedPerson,
    released: &Mutex<bool>,
) {
    let released = gate(released);
    if *released {
        return;
    }
    let key = PersonCacheKey {
        team_id: person.team_id,
        person_id: person.id,
    };
    dirty_index.mark(
        key.clone(),
        DirtyMark {
            version: person.version,
            offset,
            partition,
            stream: stream.clone(),
            is_deleted: person.is_deleted,
        },
    );
    cache.put_if_newer(partition, key, person);
}

#[allow(clippy::too_many_arguments)]
async fn keep_current(
    cfg: FollowConfig,
    warming: WarmingConfig,
    pools: Arc<WarmClientPools>,
    cache: Arc<PartitionedCache>,
    dirty_index: Arc<DirtyIndex>,
    partition: u32,
    live: WarmSource,
    start: i64,
    freshness: Arc<Mutex<Freshness>>,
    released: Arc<Mutex<bool>>,
) {
    let stream = Stream {
        topic: Arc::clone(&live.topic),
        cluster: live.cluster.clone().map(Arc::new),
        partition: live.partition,
    };
    let follow = follow_source(
        &warming,
        &pools,
        &live,
        start,
        |offset, person| {
            apply(
                &cache,
                &dirty_index,
                partition,
                &stream,
                offset,
                person,
                &released,
            )
        },
        |position| lock(&freshness).advance(position),
    );
    let confirm = async {
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
            match end_offset(&warming, &pools, &live).await {
                Ok(end) => lock(&freshness).observe_end(asked_at, end),
                Err(e) => {
                    counter!(
                        "personhog_follower_end_checks_failed_total",
                        "partition" => partition.to_string()
                    )
                    .increment(1);
                    tracing::warn!(partition, error = %e, "changelog end check failed");
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
        let dirty_index = DirtyIndex::new(100);
        let stream = Stream {
            topic: Arc::from("changelog"),
            cluster: None,
            partition: 0,
        };
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
        apply(&cache, &dirty_index, 0, &stream, 5, person, &released);

        assert!(dirty_index.get(&key).is_none());
        assert!(matches!(cache.get(0, &key), CacheLookup::PersonNotFound));
    }
}
