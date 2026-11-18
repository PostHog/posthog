use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::{Duration, Instant};

use futures::TryStreamExt;
use metrics::{counter, gauge, histogram};
use personhog_common::query_tag;
use sqlx::pool::PoolConnection;
use sqlx::postgres::{PgPool, PgRow};
use sqlx::{Postgres, Row};
use tokio::sync::oneshot;
use tokio::time::error::Elapsed;

use crate::cache::{CachedPerson, PersonCacheKey};
use crate::pg::{acquire_timed, decode_person_row, LoadError, PERSON_ROW_COLUMNS};

/// Past a few hundred keys the planner can swap the index probe for each
/// key for a merge join that scans the id index of every partition.
pub const MAX_LOAD_BATCH: usize = 100;

/// Mirrors the config's `fallback_pg_load_batch_size` default.
pub const DEFAULT_MAX_LOAD_BATCH: usize = MAX_LOAD_BATCH;

const QUEUE_DEPTH: &str = "personhog_leader_pg_load_queue_depth";
const QUEUE_WAIT_MS: &str = "personhog_leader_pg_load_queue_wait_ms";
const DROPPED_TOTAL: &str = "personhog_leader_pg_load_dropped_total";
const STATEMENT_TIMEOUTS_TOTAL: &str = "personhog_leader_pg_load_statement_timeouts_total";
const DRIVER_PANICS_TOTAL: &str = "personhog_leader_pg_load_driver_panics_total";

type Answer = Result<Option<PgRow>, Arc<sqlx::Error>>;

struct Pending {
    team_id: i32,
    person_id: i64,
    queued_at: Instant,
    reply: oneshot::Sender<Answer>,
}

#[derive(Default)]
struct Queue {
    waiting: VecDeque<Pending>,
    /// Live `drive` tasks. Changed only under the queue lock, with the
    /// check that decides it, so that a waiting load always has a driver.
    drivers: usize,
}

struct Shared {
    pool: PgPool,
    one_sql: String,
    many_sql: String,
    max_batch: usize,
    /// One for each pool connection; more could only wait on the pool.
    max_drivers: usize,
    /// The pool's acquire timeout, which bounds a load's wait and one
    /// statement. It must exceed the pool's statement timeout.
    patience: Duration,
    queue: Mutex<Queue>,
}

/// Reads cache misses from the fallback table; see "Cache-miss loads" in
/// the README. The caller owns the person lock, the checks and the cache.
#[derive(Clone)]
pub struct PersonLoader {
    shared: Arc<Shared>,
}

impl PersonLoader {
    /// `table` is interpolated into the statements, so it must be a
    /// configured identifier that passed `validate_table_name`.
    pub fn new(pool: PgPool, table: &str, max_batch: usize) -> Self {
        register_metrics();
        let options = pool.options();
        let max_drivers = (options.get_max_connections() as usize).max(1);
        let patience = options.get_acquire_timeout();
        // A tombstoned person must not be re-served on a cache miss; not-found
        // is the truthful answer for a deleted person.
        let one_sql = query_tag!(
            "load_person",
            format!(
                "SELECT {PERSON_ROW_COLUMNS}
                 FROM {table} p
                 WHERE p.team_id = $1 AND p.id = $2 AND p.is_deleted = false",
            )
        );
        // `team_id = ANY($1)` repeats the team ids as a plain filter, so
        // that the database can prune hash partitions before the join.
        let many_sql = query_tag!(
            "load_persons",
            format!(
                "SELECT {PERSON_ROW_COLUMNS}
                 FROM unnest($1::int[], $2::bigint[]) AS k(team_id, id)
                 JOIN {table} p ON p.team_id = k.team_id AND p.id = k.id
                 WHERE p.team_id = ANY($1::int[]) AND p.is_deleted = false",
            )
        );
        Self {
            shared: Arc::new(Shared {
                pool,
                one_sql,
                many_sql,
                max_batch: max_batch.clamp(1, MAX_LOAD_BATCH),
                max_drivers,
                patience,
                queue: Mutex::default(),
            }),
        }
    }

    pub async fn load(&self, key: &PersonCacheKey) -> Result<Option<CachedPerson>, LoadError> {
        let started = Instant::now();
        let team_id = i32::try_from(key.team_id).map_err(|_| {
            LoadError::from(sqlx::Error::Protocol(format!(
                "team_id {} exceeds i32 range",
                key.team_id
            )))
        })?;

        let (reply, answer) = oneshot::channel();
        self.shared.submit(Pending {
            team_id,
            person_id: key.person_id,
            queued_at: started,
            reply,
        });
        // Drivers answer inside two `patience` spans, the wait and the
        // statement. The timer holds that bound when no driver comes back.
        let row = match tokio::time::timeout(self.shared.patience * 2, answer).await {
            Ok(Ok(answer)) => answer.map_err(LoadError::Query)?,
            // The driver panicked or the runtime dropped it.
            Ok(Err(_)) => return Err(sqlx::Error::WorkerCrashed.into()),
            Err(_) => return Err(sqlx::Error::PoolTimedOut.into()),
        };

        histogram!("personhog_leader_pg_fallback_duration_ms")
            .record(started.elapsed().as_secs_f64() * 1000.0);

        let Some(row) = row else {
            counter!("personhog_leader_pg_fallback_total", "outcome" => "not_found").increment(1);
            return Ok(None);
        };
        // Decoded on the caller's task: parsing must not hold the pool
        // slot, and an unreadable row must fail only its own load.
        let person = decode_person_row(&row, key)?;
        counter!("personhog_leader_pg_fallback_total", "outcome" => "found").increment(1);
        Ok(Some(person))
    }
}

/// Registers the rare series at zero so `increase()` sees their first event.
fn register_metrics() {
    for reason in ["abandoned", "expired"] {
        counter!(DROPPED_TOTAL, "reason" => reason).increment(0);
    }
    counter!(STATEMENT_TIMEOUTS_TOTAL).increment(0);
    counter!(DRIVER_PANICS_TOTAL).increment(0);
    gauge!(QUEUE_DEPTH).set(0.0);
}

impl Shared {
    fn queue(&self) -> MutexGuard<'_, Queue> {
        // The critical sections only move entries, so a poisoned lock
        // still guards a consistent queue.
        self.queue.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn submit(self: &Arc<Self>, pending: Pending) {
        let start_driver = {
            let mut queue = self.queue();
            queue.waiting.push_back(pending);
            gauge!(QUEUE_DEPTH).set(queue.waiting.len() as f64);
            let free_slot = queue.drivers < self.max_drivers;
            if free_slot {
                queue.drivers += 1;
            }
            free_slot
        };
        if start_driver {
            tokio::spawn(drive(Arc::clone(self)));
        }
    }

    /// Retires the driver when no load waits. One lock covers the check
    /// and the retirement, so a load queued after it starts a new driver.
    fn claim_first(&self) -> Option<Pending> {
        let mut queue = self.queue();
        let first = pop_live(&mut queue.waiting, Instant::now(), self.patience);
        gauge!(QUEUE_DEPTH).set(queue.waiting.len() as f64);
        if first.is_none() {
            queue.drivers -= 1;
        }
        first
    }

    fn fill_batch(&self, first: Pending) -> Vec<Pending> {
        let mut queue = self.queue();
        let batch = next_batch(
            first,
            &mut queue.waiting,
            self.max_batch,
            Instant::now(),
            self.patience,
        );
        gauge!(QUEUE_DEPTH).set(queue.waiting.len() as f64);
        batch
    }
}

/// A driver that ends without retiring, by a panic or a dropped task,
/// would keep its place among `max_drivers` and strand the waiting loads.
/// The drop hands the place to a replacement, or frees it.
struct DriverSlot {
    shared: Arc<Shared>,
    retired: bool,
}

impl Drop for DriverSlot {
    fn drop(&mut self) {
        if self.retired {
            return;
        }
        if std::thread::panicking() {
            counter!(DRIVER_PANICS_TOTAL).increment(1);
            tracing::error!("person load driver panicked; the loads of its statement fail");
        }
        let replace = {
            let mut queue = self.shared.queue();
            let waiting = !queue.waiting.is_empty();
            if !waiting {
                queue.drivers -= 1;
            }
            waiting
        };
        if replace {
            match tokio::runtime::Handle::try_current() {
                Ok(runtime) => drop(runtime.spawn(drive(Arc::clone(&self.shared)))),
                Err(_) => self.shared.queue().drivers -= 1,
            }
        }
    }
}

async fn drive(shared: Arc<Shared>) {
    let mut slot = DriverSlot {
        shared: Arc::clone(&shared),
        retired: false,
    };
    // Claiming before acquiring gives each new load to a free driver, so
    // loads only accumulate into one statement while every driver is busy.
    while let Some(first) = shared.claim_first() {
        let conn = match acquire_timed(&shared.pool, "load_person").await {
            Ok(conn) => conn,
            Err(e) => {
                // Only the claimed load fails: another driver may hold a
                // connection that works.
                drop(first.reply.send(Err(Arc::new(e))));
                continue;
            }
        };
        let batch = shared.fill_batch(first);
        if !batch.is_empty() {
            run_batch(&shared, conn, batch).await;
        }
    }
    // `claim_first` gave the slot back when it found no load.
    slot.retired = true;
}

fn next_batch(
    first: Pending,
    waiting: &mut VecDeque<Pending>,
    max_batch: usize,
    now: Instant,
    max_wait: Duration,
) -> Vec<Pending> {
    let mut batch = Vec::with_capacity(max_batch.min(waiting.len() + 1));
    batch.extend(still_wanted(first, now, max_wait));
    while batch.len() < max_batch {
        match pop_live(waiting, now, max_wait) {
            Some(pending) => batch.push(pending),
            None => break,
        }
    }
    batch
}

fn pop_live(waiting: &mut VecDeque<Pending>, now: Instant, max_wait: Duration) -> Option<Pending> {
    while let Some(pending) = waiting.pop_front() {
        // Recorded for dropped loads too, so the long waits show.
        histogram!(QUEUE_WAIT_MS).record(
            now.saturating_duration_since(pending.queued_at)
                .as_secs_f64()
                * 1000.0,
        );
        if let Some(live) = still_wanted(pending, now, max_wait) {
            return Some(live);
        }
    }
    None
}

/// A stalled database sheds its backlog here instead of reading rows for
/// callers that left or already waited out the pool's acquire timeout.
fn still_wanted(pending: Pending, now: Instant, max_wait: Duration) -> Option<Pending> {
    if pending.reply.is_closed() {
        counter!(DROPPED_TOTAL, "reason" => "abandoned").increment(1);
        return None;
    }
    if now.saturating_duration_since(pending.queued_at) > max_wait {
        counter!(DROPPED_TOTAL, "reason" => "expired").increment(1);
        drop(pending.reply.send(Err(Arc::new(sqlx::Error::PoolTimedOut))));
        return None;
    }
    Some(pending)
}

async fn run_batch(shared: &Shared, conn: PoolConnection<Postgres>, batch: Vec<Pending>) {
    let started = Instant::now();
    histogram!("personhog_leader_pg_load_batch_size").record(batch.len() as f64);
    match <[Pending; 1]>::try_from(batch) {
        Ok([only]) => load_one(shared, conn, only).await,
        Err(batch) => load_many(shared, conn, batch).await,
    }
    histogram!("personhog_leader_pg_load_batch_duration_ms")
        .record(started.elapsed().as_secs_f64() * 1000.0);
}

/// The driver owns the statement, so no caller's deadline ends one on a
/// connection that stopped answering. A statement that ran out of time is
/// still in flight, so its connection closes instead of rejoining the pool.
fn settle<T>(
    patience: Duration,
    conn: &mut PoolConnection<Postgres>,
    outcome: Result<Result<T, sqlx::Error>, Elapsed>,
) -> Result<T, sqlx::Error> {
    outcome.unwrap_or_else(|_| {
        conn.close_on_drop();
        counter!(STATEMENT_TIMEOUTS_TOTAL).increment(1);
        Err(sqlx::Error::Io(std::io::Error::new(
            std::io::ErrorKind::TimedOut,
            format!("person load statement did not finish in {patience:?}"),
        )))
    })
}

async fn load_one(shared: &Shared, mut conn: PoolConnection<Postgres>, only: Pending) {
    let statement = sqlx::query(&shared.one_sql)
        .bind(only.team_id)
        .bind(only.person_id)
        .fetch_optional(&mut *conn);
    let outcome = tokio::time::timeout(shared.patience, statement).await;
    let answer = settle(shared.patience, &mut conn, outcome);
    drop(conn);
    drop(only.reply.send(answer.map_err(Arc::new)));
}

async fn load_many(shared: &Shared, mut conn: PoolConnection<Postgres>, batch: Vec<Pending>) {
    let mut team_ids = Vec::with_capacity(batch.len());
    let mut person_ids = Vec::with_capacity(batch.len());
    // The statement returns one row for each array entry, so two loads
    // of one person each get a row.
    let mut unanswered: HashMap<(i32, i64), Vec<oneshot::Sender<Answer>>> =
        HashMap::with_capacity(batch.len());
    for pending in batch {
        team_ids.push(pending.team_id);
        person_ids.push(pending.person_id);
        unanswered
            .entry((pending.team_id, pending.person_id))
            .or_default()
            .push(pending.reply);
    }

    let statement = deliver_rows(
        &shared.many_sql,
        &mut conn,
        &team_ids,
        &person_ids,
        &mut unanswered,
    );
    let outcome = tokio::time::timeout(shared.patience, statement).await;
    let outcome = settle(shared.patience, &mut conn, outcome);
    drop(conn);
    answer_rest(
        unanswered.into_values().flatten(),
        &outcome.map_err(Arc::new),
    );
}

/// Rows go out as they arrive, so a statement that fails part way has
/// still answered the loads whose rows it returned.
async fn deliver_rows(
    sql: &str,
    conn: &mut PoolConnection<Postgres>,
    team_ids: &[i32],
    person_ids: &[i64],
    unanswered: &mut HashMap<(i32, i64), Vec<oneshot::Sender<Answer>>>,
) -> Result<(), sqlx::Error> {
    let mut rows = sqlx::query(sql)
        .bind(team_ids)
        .bind(person_ids)
        .fetch(&mut **conn);
    while let Some(row) = rows.try_next().await? {
        let key: (i32, i64) = (row.try_get("team_id")?, row.try_get("id")?);
        if let Some(reply) = unanswered.get_mut(&key).and_then(Vec::pop) {
            drop(reply.send(Ok(Some(row))));
        }
    }
    Ok(())
}

/// Callers treat not-found as proof that the person is gone, so only a
/// statement that completed may answer it.
fn answer_rest(
    replies: impl Iterator<Item = oneshot::Sender<Answer>>,
    outcome: &Result<(), Arc<sqlx::Error>>,
) {
    for reply in replies {
        let answer = match outcome {
            Ok(()) => Ok(None),
            Err(e) => Err(Arc::clone(e)),
        };
        drop(reply.send(answer));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const MAX_WAIT: Duration = Duration::from_secs(10);

    fn pending(person_id: i64, queued_at: Instant) -> (Pending, oneshot::Receiver<Answer>) {
        let (reply, answer) = oneshot::channel();
        let pending = Pending {
            team_id: 1,
            person_id,
            queued_at,
            reply,
        };
        (pending, answer)
    }

    fn person_ids<'a>(loads: impl IntoIterator<Item = &'a Pending>) -> Vec<i64> {
        loads.into_iter().map(|load| load.person_id).collect()
    }

    async fn loader_without_connections(max_connections: u32) -> PersonLoader {
        let pool = sqlx::postgres::PgPoolOptions::new()
            .max_connections(max_connections)
            .connect_lazy("postgres://localhost/unused")
            .unwrap();
        pool.close().await;
        PersonLoader::new(pool, "posthog_person", DEFAULT_MAX_LOAD_BATCH)
    }

    fn is_query_error(
        answer: &Result<Option<CachedPerson>, LoadError>,
        expected: fn(&sqlx::Error) -> bool,
    ) -> bool {
        matches!(answer, Err(LoadError::Query(error)) if expected(error))
    }

    #[test]
    fn a_statement_takes_the_oldest_waiting_loads_up_to_the_cap() {
        let now = Instant::now();
        let (first, _first_answer) = pending(0, now);
        let (mut waiting, _answers): (VecDeque<_>, Vec<_>) =
            (1..=5).map(|id| pending(id, now)).unzip();

        let batch = next_batch(first, &mut waiting, 3, now, MAX_WAIT);

        assert_eq!(person_ids(&batch), [0, 1, 2]);
        assert_eq!(person_ids(&waiting), [3, 4, 5]);
    }

    #[test]
    fn a_statement_carries_no_load_that_is_abandoned_or_overdue() {
        let queued_long_ago = Instant::now();
        let now = queued_long_ago + MAX_WAIT + Duration::from_millis(1);
        let (first, _first_answer) = pending(0, now);
        let (abandoned, abandoned_answer) = pending(1, now);
        drop(abandoned_answer);
        let (overdue, mut overdue_answer) = pending(2, queued_long_ago);
        let (live, _live_answer) = pending(3, now);
        let mut waiting = VecDeque::from([abandoned, overdue, live]);

        let batch = next_batch(first, &mut waiting, 10, now, MAX_WAIT);

        assert_eq!(person_ids(&batch), [0, 3]);
        assert!(matches!(
            overdue_answer.try_recv(),
            Ok(Err(error)) if matches!(*error, sqlx::Error::PoolTimedOut)
        ));
    }

    #[tokio::test(start_paused = true)]
    async fn a_load_that_gets_no_connection_fails_and_frees_its_driver() {
        let loader = loader_without_connections(2).await;

        // More loads than drivers, so a slot kept after a failure shows.
        for person_id in 0..5 {
            let key = PersonCacheKey {
                team_id: 1,
                person_id,
            };
            let answer = loader.load(&key).await;
            assert!(is_query_error(&answer, |e| matches!(
                e,
                sqlx::Error::PoolClosed
            )));
        }
    }

    #[tokio::test(start_paused = true)]
    async fn a_load_that_no_driver_answers_fails_as_a_pool_timeout() {
        let loader = loader_without_connections(1).await;
        // What drivers stuck on unresponsive connections look like.
        loader.shared.queue().drivers = loader.shared.max_drivers;

        let key = PersonCacheKey {
            team_id: 1,
            person_id: 1,
        };
        let answer = loader.load(&key).await;

        assert!(is_query_error(&answer, |e| matches!(
            e,
            sqlx::Error::PoolTimedOut
        )));
    }

    #[tokio::test(start_paused = true)]
    async fn a_driver_that_ends_without_retiring_is_replaced_while_loads_wait() {
        let loader = loader_without_connections(1).await;
        let (waiting, answer) = pending(1, Instant::now());
        {
            let mut queue = loader.shared.queue();
            queue.waiting.push_back(waiting);
            queue.drivers = 1;
        }

        drop(DriverSlot {
            shared: Arc::clone(&loader.shared),
            retired: false,
        });

        assert!(matches!(
            answer.await,
            Ok(Err(error)) if matches!(*error, sqlx::Error::PoolClosed)
        ));
    }
}
