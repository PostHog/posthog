use std::collections::VecDeque;
use std::sync::Arc;
use std::time::{Duration, Instant};

use lru::LruCache;
use metrics::{counter, histogram};
use rdkafka::consumer::Consumer;
use rdkafka::{Offset, TopicPartitionList};
use tokio::sync::mpsc;

use personhog_coordination::changelog::WarmSource;
use personhog_coordination::error::{Error as CoordError, Result as CoordResult};

use crate::cache::{CachedPerson, FillOutcome, PartitionedCache, PersonCache, PersonCacheKey};
use crate::warming::{consume_ranges, ConsumerPool, OffsetRange, WarmClientPools, WarmingConfig};

/// How far back a fill reads, and in what steps.
#[derive(Debug, Clone, Copy)]
pub struct FillConfig {
    pub lookback: Duration,
    /// Offsets per backward step; a transactional topic spends about half on markers.
    pub chunk_offsets: i64,
    /// The fill stops once the cache holds this fraction of its budget.
    pub target_fraction: f64,
    pub concurrency: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FillEnd {
    /// Reached the lookback bound or the start of the log.
    Bound,
    Budget,
    /// Put tracking passed its bound.
    Stopped,
    Failed,
}

impl FillEnd {
    pub fn label(self) -> &'static str {
        match self {
            Self::Bound => "bound",
            Self::Budget => "budget",
            Self::Stopped => "stopped",
            Self::Failed => "error",
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct FillStats {
    pub records: u64,
    pub inserted: u64,
    pub end: FillEnd,
}

/// The first offset written at or after `since_ms`, capped at `upper`.
pub async fn lookback_offset(
    cfg: &WarmingConfig,
    pools: &WarmClientPools,
    source: &WarmSource,
    since_ms: i64,
    upper: i64,
) -> CoordResult<i64> {
    let partition_i32 = i32::try_from(source.partition).map_err(|_| {
        CoordError::invalid_state(format!("partition {} exceeds i32::MAX", source.partition))
    })?;
    let pools = pools.on(source.cluster.as_ref());
    let consumer = pools.warming.checkout()?;
    let topic = Arc::clone(&source.topic);
    let timeout = cfg.fetch_watermarks_timeout;
    let (consumer, found) = tokio::task::spawn_blocking(move || {
        let mut tpl = TopicPartitionList::new();
        let found = tpl
            .add_partition_offset(&topic, partition_i32, Offset::Offset(since_ms))
            .and_then(|()| consumer.offsets_for_times(tpl, timeout))
            .map_err(|e| CoordError::invalid_state(format!("offsets for times: {e}")));
        (consumer, found)
    })
    .await
    .map_err(|e| CoordError::invalid_state(format!("offsets_for_times join: {e}")))?;
    let found = found?;
    pools.warming.give_back(consumer);
    let offset = found
        .find_partition(&source.topic, partition_i32)
        .and_then(|elem| match elem.offset() {
            Offset::Offset(offset) => Some(offset),
            _ => None,
        });
    Ok(offset.map_or(upper, |offset| offset.min(upper)))
}

/// One partition's fill from `[lower, upper)`, a chunk at a time, newest first, marking nothing.
pub struct PartitionFill {
    partition: u32,
    cache: Arc<PersonCache>,
    source: WarmSource,
    lower: i64,
    chunk_end: i64,
    started: Instant,
    records: u64,
    inserted: u64,
    end: Option<FillEnd>,
}

impl PartitionFill {
    pub fn new(
        partition: u32,
        cache: Arc<PersonCache>,
        source: WarmSource,
        lower: i64,
        upper: i64,
    ) -> Self {
        Self {
            partition,
            cache,
            source,
            lower,
            chunk_end: upper,
            started: Instant::now(),
            records: 0,
            inserted: 0,
            end: (upper <= lower).then_some(FillEnd::Bound),
        }
    }

    pub fn stats(&self) -> Option<FillStats> {
        self.end.map(|end| FillStats {
            records: self.records,
            inserted: self.inserted,
            end,
        })
    }

    fn fail(&mut self, error: &CoordError) {
        tracing::warn!(
            partition = self.partition,
            error = %error,
            "cache fill failed; the partition serves without it"
        );
        self.end = Some(FillEnd::Failed);
    }

    fn finish(&self, end: &'static str) {
        end_fill(&self.cache, end);
        histogram!("personhog_leader_cache_fill_duration_ms")
            .record(self.started.elapsed().as_secs_f64() * 1000.0);
        tracing::info!(
            partition = self.partition,
            records = self.records,
            inserted = self.inserted,
            end,
            elapsed_ms = self.started.elapsed().as_millis() as u64,
            "cache fill finished"
        );
    }
}

fn end_fill(cache: &PersonCache, end: &'static str) {
    cache.stop_tracking_puts();
    counter!("personhog_leader_cache_fills_total", "end" => end).increment(1);
}

struct Chunk {
    fill_index: usize,
    start: i64,
    room: usize,
    /// Each person's newest record in the chunk, least recently written first.
    latest: LruCache<PersonCacheKey, CachedPerson>,
    buffered: usize,
    overflowed: bool,
}

/// Every fill must be on the pool's cluster.
pub async fn fill_next_chunks(
    cfg: &WarmingConfig,
    fill: &FillConfig,
    pool: &ConsumerPool,
    fills: &mut [PartitionFill],
) {
    let mut chunks = Vec::new();
    let mut ranges = Vec::new();
    for (index, filling) in fills.iter_mut().enumerate() {
        if filling.end.is_some() {
            continue;
        }
        let room = filling.cache.free_room(fill.target_fraction);
        if room == 0 {
            filling.end = Some(FillEnd::Budget);
            continue;
        }
        let Ok(partition) = i32::try_from(filling.source.partition) else {
            filling.fail(&CoordError::invalid_state(format!(
                "partition {} exceeds i32::MAX",
                filling.source.partition
            )));
            continue;
        };
        let start = filling.lower.max(filling.chunk_end - fill.chunk_offsets);
        ranges.push(OffsetRange {
            leader_partition: filling.partition,
            topic: Arc::clone(&filling.source.topic),
            partition,
            start,
            end: filling.chunk_end,
        });
        chunks.push(Chunk {
            fill_index: index,
            start,
            room,
            latest: LruCache::unbounded(),
            buffered: 0,
            overflowed: false,
        });
    }
    if chunks.is_empty() {
        return;
    }

    let consumer = match pool.checkout() {
        Ok(consumer) => consumer,
        Err(e) => {
            for chunk in &chunks {
                fills[chunk.fill_index].fail(&e);
            }
            return;
        }
    };
    let reads = consume_ranges(cfg, &consumer, &ranges, |index, _offset, cached| {
        let chunk = &mut chunks[index];
        let filling = &mut fills[chunk.fill_index];
        filling.records += 1;
        counter!("personhog_leader_cache_fill_records_total").increment(1);
        let key = PersonCacheKey {
            team_id: cached.team_id,
            person_id: cached.id,
        };
        if filling.cache.was_put(&key) {
            return;
        }
        chunk.buffered += cached.properties.len();
        if let Some(replaced) = chunk.latest.put(key, cached) {
            chunk.buffered -= replaced.properties.len();
        }
        // A chunk holding more than the cache has room for keeps its newest persons.
        while chunk.buffered > chunk.room {
            let Some((_, dropped)) = chunk.latest.pop_lru() else {
                break;
            };
            chunk.buffered -= dropped.properties.len();
            chunk.overflowed = true;
        }
    })
    .await;
    // Given back before the inserts, because handoff warms draw on the same pool.
    if reads.iter().all(Result::is_ok) {
        pool.give_back(consumer);
    } else {
        drop(consumer);
    }

    for (mut chunk, read) in chunks.into_iter().zip(reads) {
        let filling = &mut fills[chunk.fill_index];
        // A chunk that was not read whole may lack a person's newest record, so none of it
        // is inserted.
        if let Err(e) = read {
            filling.fail(&e);
            continue;
        }
        while let Some((key, person)) = chunk.latest.pop_mru() {
            if filling.cache.free_room(fill.target_fraction) == 0 {
                filling.end = Some(FillEnd::Budget);
                break;
            }
            match filling.cache.fill(key, person) {
                FillOutcome::Inserted => {
                    filling.inserted += 1;
                    counter!("personhog_leader_cache_fill_inserted_total").increment(1);
                }
                FillOutcome::Skipped => {}
                FillOutcome::NotTracking => {
                    filling.end = Some(FillEnd::Stopped);
                    break;
                }
            }
            // Encoding a chunk is CPU work; requests on this worker must not wait for all of it.
            tokio::task::yield_now().await;
        }
        if filling.end.is_some() {
            continue;
        }
        // A dropped person never reached the guard, so an older record of theirs must not be read.
        if chunk.overflowed {
            filling.end = Some(FillEnd::Budget);
            continue;
        }
        filling.chunk_end = chunk.start;
        if filling.chunk_end <= filling.lower {
            filling.end = Some(FillEnd::Bound);
        }
    }
}

pub struct FillRequest {
    pub partition: u32,
    pub cache: Arc<PersonCache>,
    pub source: WarmSource,
    pub upper: i64,
}

pub struct Fills {
    cfg: WarmingConfig,
    fill: FillConfig,
    pools: Arc<WarmClientPools>,
    cache: Arc<PartitionedCache>,
    waiting: VecDeque<FillRequest>,
    active: Vec<PartitionFill>,
}

impl Fills {
    pub fn new(
        cfg: WarmingConfig,
        fill: FillConfig,
        pools: Arc<WarmClientPools>,
        cache: Arc<PartitionedCache>,
    ) -> Self {
        Self {
            cfg,
            fill,
            pools,
            cache,
            waiting: VecDeque::new(),
            active: Vec::new(),
        }
    }

    pub fn queue(&mut self, request: FillRequest) {
        self.waiting.push_back(request);
    }

    pub fn is_idle(&self) -> bool {
        self.waiting.is_empty() && self.active.is_empty()
    }

    pub async fn round(&mut self) {
        self.waiting.retain(|request| {
            let serving = self.cache.is_serving(request.partition, &request.cache);
            if !serving {
                tracing::info!(
                    partition = request.partition,
                    "cache fill skipped; its build no longer serves"
                );
                end_fill(&request.cache, "released");
            }
            serving
        });
        self.active.retain(|filling| {
            let serving = self.cache.is_serving(filling.partition, &filling.cache);
            if !serving {
                filling.finish("released");
            }
            serving
        });

        // With no slot the loop would admit nothing, and `run_fills` would spin on the
        // waiting requests.
        let slots = self.fill.concurrency.max(1);
        while self.active.len() < slots {
            let Some(request) = self.waiting.pop_front() else {
                break;
            };
            let begun = self.begin(request).await;
            self.active.extend(begun);
        }
        let Some(first) = self.active.first() else {
            return;
        };

        // A consumer reads one cluster. The fills on other clusters move to the front, so
        // that the next round is theirs.
        let cluster = first.source.cluster.clone();
        let (mut round, rest): (Vec<_>, Vec<_>) = self
            .active
            .drain(..)
            .partition(|filling| filling.source.cluster == cluster);
        self.active = rest;
        let pools = self.pools.on(cluster.as_ref());
        fill_next_chunks(&self.cfg, &self.fill, &pools.warming, &mut round).await;
        for filling in round {
            match filling.end {
                Some(end) => filling.finish(end.label()),
                None => self.active.push(filling),
            }
        }
    }

    async fn begin(&self, request: FillRequest) -> Option<PartitionFill> {
        let since_ms =
            chrono::Utc::now().timestamp_millis() - self.fill.lookback.as_millis() as i64;
        let lookup = lookback_offset(
            &self.cfg,
            &self.pools,
            &request.source,
            since_ms,
            request.upper,
        )
        .await;
        match lookup {
            Ok(lower) => Some(PartitionFill::new(
                request.partition,
                request.cache,
                request.source,
                lower,
                request.upper,
            )),
            Err(e) => {
                tracing::warn!(
                    partition = request.partition,
                    error = %e,
                    "cache fill failed; the partition serves without it"
                );
                end_fill(&request.cache, FillEnd::Failed.label());
                None
            }
        }
    }
}

pub async fn run_fills(mut fills: Fills, mut requests: mpsc::UnboundedReceiver<FillRequest>) {
    loop {
        if fills.is_idle() {
            let Some(request) = requests.recv().await else {
                return;
            };
            fills.queue(request);
        }
        while let Ok(request) = requests.try_recv() {
            fills.queue(request);
        }
        fills.round().await;
    }
}
