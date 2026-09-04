use std::sync::{Arc, Mutex};

use ahash::AHashSet;
use futures::TryStreamExt;
use sqlx::PgPool;
use tokio::sync::{mpsc, Semaphore};
use tracing::{info, warn};

use crate::{
    config::Config,
    metrics_consts::{CACHE_WARMING_ROWS, CACHE_WARMING_TEAMS, CACHE_WARMING_TEAM_TIME},
    types::{EventProperty, PropertyDefinition, PropertyParentType, PropertyValueType, Update},
    update_cache::Cache,
};

// Lazy per-team cache warming. The consumed topic is partitioned by team, so the set
// of teams a pod serves is exactly the set whose events arrive; there is nothing to
// enumerate up front. The first event of a team after boot enqueues it here, and a
// background worker streams the team's existing definition rows from Postgres into
// the dedup caches. Until that finishes the team's lookups miss and write no-op
// upserts, exactly as they would without warming, so the warm never blocks the
// pipeline and cannot affect correctness - it only converts future misses to hits.

#[derive(Clone, Copy)]
pub struct WarmingLimits {
    pub eventprops_per_team: i64,
    pub propdefs_per_team: i64,
    // Rows per event-property statement; see the config field for why chunking matters.
    pub chunk_size: i64,
}

impl WarmingLimits {
    pub fn from_config(config: &Config) -> Self {
        Self {
            eventprops_per_team: config.cache_warming_eventprops_per_team_limit,
            propdefs_per_team: config.cache_warming_propdefs_per_team_limit,
            chunk_size: config.cache_warming_chunk_size.max(1),
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct WarmTarget {
    team_id: i32,
    project_id: i64,
}

/// Shared warming state: the fleet of producer loops feeds it, one worker drains it.
pub struct Warming {
    // Teams enqueued or already warmed this process lifetime. A failed warm removes its
    // team so a later event can retry it.
    seen: Mutex<AHashSet<i32>>,
    tx: mpsc::Sender<WarmTarget>,
}

impl Warming {
    pub fn new(queue_depth: usize) -> (Arc<Self>, mpsc::Receiver<WarmTarget>) {
        let (tx, rx) = mpsc::channel(queue_depth);
        (
            Arc::new(Self {
                seen: Mutex::new(AHashSet::new()),
                tx,
            }),
            rx,
        )
    }

    fn notice(&self, team_id: i32, project_id: i64) {
        if !self.seen.lock().unwrap().insert(team_id) {
            return;
        }
        let target = WarmTarget {
            team_id,
            project_id,
        };
        if self.tx.try_send(target).is_err() {
            // Full queue: forget the team so a later event re-enqueues it.
            self.seen.lock().unwrap().remove(&team_id);
            metrics::counter!(CACHE_WARMING_TEAMS, &[("result", "queue_full")]).increment(1);
        }
    }

    fn forget(&self, team_id: i32) {
        self.seen.lock().unwrap().remove(&team_id);
    }
}

/// Per-producer-loop handle. The local set absorbs the per-event check without any
/// shared-state contention; the shared set only sees each team once per loop.
pub struct TeamWarmer {
    local_seen: AHashSet<i32>,
    shared: Arc<Warming>,
}

impl TeamWarmer {
    pub fn new(shared: Arc<Warming>) -> Self {
        Self {
            local_seen: AHashSet::new(),
            shared,
        }
    }

    pub fn notice(&mut self, team_id: i32, project_id: i64) {
        if self.local_seen.insert(team_id) {
            self.shared.notice(team_id, project_id);
        }
    }
}

/// Drains the warming queue, running at most `concurrency` team warms at a time.
pub async fn run_warming_worker(
    mut rx: mpsc::Receiver<WarmTarget>,
    warming: Arc<Warming>,
    pool: PgPool,
    cache: Arc<Cache>,
    limits: WarmingLimits,
    concurrency: usize,
) {
    let semaphore = Arc::new(Semaphore::new(concurrency.max(1)));
    while let Some(target) = rx.recv().await {
        let permit = semaphore.clone().acquire_owned().await;
        let Ok(permit) = permit else {
            return;
        };
        let warming = warming.clone();
        let pool = pool.clone();
        let cache = cache.clone();
        tokio::spawn(async move {
            let _permit = permit;
            let timer = common_metrics::timing_guard(CACHE_WARMING_TEAM_TIME, &[]);
            match warm_team(&pool, &cache, target.team_id, target.project_id, limits).await {
                Ok((eventprops, propdefs)) => {
                    timer.label("result", "completed").fin();
                    metrics::counter!(CACHE_WARMING_TEAMS, &[("result", "completed")]).increment(1);
                    info!(
                        team_id = target.team_id,
                        eventprops, propdefs, "warmed dedup caches for team"
                    );
                }
                Err(e) => {
                    timer.label("result", "failed").fin();
                    metrics::counter!(CACHE_WARMING_TEAMS, &[("result", "failed")]).increment(1);
                    warn!(
                        team_id = target.team_id,
                        "cache warming failed, team will retry on a later event: {e}"
                    );
                    // Retry on the next sighting of this team.
                    warming.forget(target.team_id);
                }
            }
        });
    }
}

/// Streams a team's existing definition rows into the dedup caches.
///
/// Bounded by the per-team limits: rows past the cap belong to teams whose keyspace
/// cannot fit a cache anyway, so a partial warm captures the recurring subset and
/// stops. Group-typed property definitions are skipped - their cache key wants the
/// group name while Postgres stores the resolved index, and they are a sliver of
/// write volume.
///
/// The event-property scan is keyset-paginated: with the COALESCE prefix pinned by
/// equality, ORDER BY (event, property) is the index order, so each chunk resumes
/// the same range scan where the previous one stopped and every statement stays
/// bounded to seconds even on the largest teams.
///
/// A row the cache already covers is not re-inserted. The live write path races
/// this scan, and its optimistic inserts can be fresher than the query snapshot
/// (a property typed after the scan started); overwriting would downgrade that
/// entry and cost a redundant no-op upsert later. Loaded rows describe successful
/// past writes, so what does get inserted satisfies the same invariant as the
/// write path: `Some` property types only enter the cache when the row is known
/// non-null in Postgres.
pub async fn warm_team(
    pool: &PgPool,
    cache: &Cache,
    team_id: i32,
    project_id: i64,
    limits: WarmingLimits,
) -> Result<(u64, u64), sqlx::Error> {
    let mut eventprops: u64 = 0;
    let mut keyset: Option<(String, String)> = None;
    loop {
        let remaining = limits.eventprops_per_team - eventprops as i64;
        if remaining <= 0 {
            break;
        }
        let chunk_limit = limits.chunk_size.min(remaining);
        let query = if let Some((last_event, last_property)) = keyset.take() {
            sqlx::query_as::<_, (String, String)>(
                r#"SELECT event, property FROM posthog_eventproperty
                   WHERE COALESCE(project_id, team_id::bigint) = $1
                     AND (event, property) > ($3, $4)
                   ORDER BY event, property LIMIT $2"#,
            )
            .bind(project_id)
            .bind(chunk_limit)
            .bind(last_event)
            .bind(last_property)
        } else {
            sqlx::query_as::<_, (String, String)>(
                r#"SELECT event, property FROM posthog_eventproperty
                   WHERE COALESCE(project_id, team_id::bigint) = $1
                   ORDER BY event, property LIMIT $2"#,
            )
            .bind(project_id)
            .bind(chunk_limit)
        };

        let rows = query.fetch_all(pool).await?;
        let chunk_rows = rows.len() as i64;
        keyset = rows.last().cloned();
        for (event, property) in rows {
            let update = Update::EventProperty(EventProperty {
                team_id,
                project_id,
                event,
                property,
            });
            if !cache.covers(&update) {
                cache.insert(update);
            }
            eventprops += 1;
        }
        if chunk_rows < chunk_limit {
            break;
        }
    }
    metrics::counter!(CACHE_WARMING_ROWS, &[("cache", "eventprops")]).increment(eventprops);

    let mut propdefs: u64 = 0;
    let mut rows = sqlx::query_as::<_, (String, Option<String>, i16)>(
        r#"SELECT name, property_type, type FROM posthog_propertydefinition
           WHERE COALESCE(project_id, team_id::bigint) = $1
             AND group_type_index IS NULL LIMIT $2"#,
    )
    .bind(project_id)
    .bind(limits.propdefs_per_team)
    .fetch(pool);
    while let Some((name, property_type, parent_type)) = rows.try_next().await? {
        let event_type = match parent_type {
            1 => PropertyParentType::Event,
            2 => PropertyParentType::Person,
            3 => PropertyParentType::Group,
            4 => PropertyParentType::Session,
            _ => continue,
        };
        // An unparseable stored type warms as untyped: the first typed sighting then
        // re-issues one upsert, which the DB guard no-ops. Never lossy.
        let property_type: Option<PropertyValueType> = property_type.and_then(|s| s.parse().ok());
        let update = Update::Property(PropertyDefinition {
            team_id,
            project_id,
            name,
            is_numerical: matches!(property_type, Some(PropertyValueType::Numeric)),
            property_type,
            event_type,
            group_type_index: None,
        });
        if !cache.covers(&update) {
            cache.insert(update);
        }
        propdefs += 1;
    }
    metrics::counter!(CACHE_WARMING_ROWS, &[("cache", "propdefs")]).increment(propdefs);

    Ok((eventprops, propdefs))
}
