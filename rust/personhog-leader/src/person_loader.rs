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

/// The most persons one statement may read. Past a few hundred keys the
/// planner can replace the index probe for each key with a merge join that
/// scans the id index of every partition, which reads far more of the
/// table than the batch needs.
pub const MAX_LOAD_BATCH: usize = 100;

/// Mirrors the config's `fallback_pg_load_batch_size` default.
pub const DEFAULT_MAX_LOAD_BATCH: usize = MAX_LOAD_BATCH;

const QUEUE_DEPTH: &str = "personhog_leader_pg_load_queue_depth";
const QUEUE_WAIT_MS: &str = "personhog_leader_pg_load_queue_wait_ms";
const DROPPED_TOTAL: &str = "personhog_leader_pg_load_dropped_total";
const STATEMENT_TIMEOUTS_TOTAL: &str = "personhog_leader_pg_load_statement_timeouts_total";
const DRIVER_PANICS_TOTAL: &str = "personhog_leader_pg_load_driver_panics_total";

/// A row, or none when the person is absent or tombstoned. The error is
/// shared because one failed statement answers every load it carried.
type Answer = Result<Option<PgRow>, Arc<sqlx::Error>>;

/// One load waiting for a statement to carry it.
struct Pending {
    team_id: i32,
    person_id: i64,
    queued_at: Instant,
    reply: oneshot::Sender<Answer>,
}

#[derive(Default)]
struct Queue {
    waiting: VecDeque<Pending>,
    /// Live `drive` tasks. Changed only under the queue lock, together
    /// with the check that decides it, so that a waiting load always has
    /// a driver.
    drivers: usize,
}

struct Shared {
    pool: PgPool,
    /// Reads one person. A load that runs alone uses this statement
    /// because the planner prunes it to one partition from the bound team
    /// id, which costs the database less than `many_sql` with one key.
    one_sql: String,
    /// Reads every person of a batch.
    many_sql: String,
    max_batch: usize,
    /// One driver for each pool connection. A driver beyond that could only
    /// wait on the pool, holding a load that a busy driver could batch.
    max_drivers: usize,
    /// The pool's acquire timeout, which bounds every wait here. A load
    /// that has waited this long for a statement is refused, a statement
    /// that has run this long is abandoned, and a caller gives up after
    /// both. It must exceed the pool's server-side statement timeout, so
    /// that a slow statement ends with the server's error and this bound
    /// only ends a statement whose connection has stopped answering.
    patience: Duration,
    queue: Mutex<Queue>,
}

/// Loads persons from the fallback table on a cache miss.
///
/// The fallback pool is small, and it also serves the lifecycle mark
/// checks. With one statement for each person, the pool size caps the
/// load rate, and a burst of misses queues on the pool in front of those
/// checks. Loads share statements instead. Each pool connection has one
/// driver. A load that arrives while a driver is free is claimed by that
/// driver and normally runs alone. Loads that arrive while every driver
/// is busy wait in a queue, and the next driver to get a connection reads
/// all of them in one statement, up to `max_batch`. Batches therefore
/// form when the pool is saturated, which is when one statement for each
/// person would hold the load rate down.
///
/// The loader only reads. The caller holds the person lock, has checked
/// the dirty index and partition ownership before the load, and writes
/// the cache after it.
#[derive(Clone)]
pub struct PersonLoader {
    shared: Arc<Shared>,
}

impl PersonLoader {
    /// `table` is interpolated into the statement, so it must be a
    /// configured identifier that passed `validate_table_name`, never
    /// request data. `max_batch` is held between 1 and [`MAX_LOAD_BATCH`].
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
        // The join condition gives the database no team id to prune the
        // table's hash partitions with before the join runs.
        // `team_id = ANY($1)` repeats the team ids as a plain filter so
        // that it can.
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
                // A statement always carries the load that opened it.
                max_batch: max_batch.clamp(1, MAX_LOAD_BATCH),
                max_drivers,
                patience,
                queue: Mutex::default(),
            }),
        }
    }

    /// Reads one person, or none when the person is absent or tombstoned.
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
        // A load that is served gets its answer inside two `patience`
        // spans: one for its wait and one for its statement. The timer
        // makes that bound hold when no driver comes back to answer, and
        // the dropped receiver then marks the load as abandoned.
        let row = match tokio::time::timeout(self.shared.patience * 2, answer).await {
            Ok(Ok(answer)) => answer.map_err(LoadError::Query)?,
            // The driver ended without an answer: it panicked, or the
            // runtime dropped it.
            Ok(Err(_)) => return Err(sqlx::Error::WorkerCrashed.into()),
            Err(_) => return Err(sqlx::Error::PoolTimedOut.into()),
        };

        histogram!("personhog_leader_pg_fallback_duration_ms")
            .record(started.elapsed().as_secs_f64() * 1000.0);

        let Some(row) = row else {
            counter!("personhog_leader_pg_fallback_total", "outcome" => "not_found").increment(1);
            return Ok(None);
        };
        // Decoded here, on the caller's task: parsing the properties must
        // not hold the pool slot, and one unreadable row must fail only
        // its own load.
        let person = decode_person_row(&row, key)?;
        counter!("personhog_leader_pg_fallback_total", "outcome" => "found").increment(1);
        Ok(Some(person))
    }
}

/// Registers the rare series at zero, so that `increase()` sees the first
/// event of each.
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
        // Every critical section only moves entries between collections,
        // so a poisoned lock still guards a consistent queue.
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

    /// Takes the load that opens a driver's next statement, or retires the
    /// driver when no load waits. The lock covers both the check and the
    /// retirement, so a load queued after the check finds a free driver
    /// slot and starts a driver of its own.
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

/// A driver's place among the `max_drivers`. A driver that ends without
/// retiring, by a panic or because the runtime dropped it, would keep its
/// place, and loads that arrive later would then start no driver. The
/// drop gives the place to a replacement while loads wait, and frees it
/// otherwise.
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

/// Serves waiting loads, one connection and one statement for each batch,
/// until no load waits.
async fn drive(shared: Arc<Shared>) {
    let mut slot = DriverSlot {
        shared: Arc::clone(&shared),
        retired: false,
    };
    // The driver claims a load before it asks for a connection. A free
    // driver therefore takes each new load for itself, and loads only
    // accumulate into one statement while every driver is busy.
    while let Some(first) = shared.claim_first() {
        // The connection goes back to the pool after every statement, so
        // the mark checks waiting on the pool take their turn between
        // batches.
        let conn = match acquire_timed(&shared.pool, "load_person").await {
            Ok(conn) => conn,
            Err(e) => {
                // Only the claimed load fails. The loads still waiting keep
                // their place, because another driver may hold a connection
                // that works.
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

/// The loads one statement carries: `first`, then the oldest waiting
/// loads, up to `max_batch`.
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

/// Pops the oldest waiting load that is still wanted.
fn pop_live(waiting: &mut VecDeque<Pending>, now: Instant, max_wait: Duration) -> Option<Pending> {
    while let Some(pending) = waiting.pop_front() {
        // Recorded for every load a driver reaches, served or not, so the
        // histogram does not hide the loads that waited too long.
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

/// Drops a load whose caller is gone, and refuses one that has waited
/// longer than the pool lets a caller wait for a connection. A stalled
/// database then sheds its backlog instead of reading rows for requests
/// that have already failed.
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

/// The outcome of a statement that had `patience` to finish. The driver
/// owns the statement, so no caller's deadline ends it, and a connection
/// that stopped answering would otherwise hold the driver and the loads
/// of its statement without end. A statement that ran out of time is
/// still in flight on its connection, so the connection closes instead of
/// going back to the pool.
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
    // A list for each key: the statement returns one row for each array
    // entry, so two loads of one person each get a row of their own.
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

/// Sends each row to its load when the row arrives instead of when the
/// statement ends, so a statement that fails part way has still answered
/// the loads whose rows it returned.
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

/// Answers the loads that got no row: not-found when the statement
/// completed, and its error when it did not. Callers treat not-found as
/// proof that the person is gone, so a failed statement must never
/// produce it.
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

    /// A loader on a pool that refuses every acquire at once.
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
        // The overdue caller is still waiting, so it gets the error a
        // caller waiting on the pool itself would get.
        assert!(matches!(
            overdue_answer.try_recv(),
            Ok(Err(error)) if matches!(*error, sqlx::Error::PoolTimedOut)
        ));
    }

    #[tokio::test(start_paused = true)]
    async fn a_load_that_gets_no_connection_fails_and_frees_its_driver() {
        let loader = loader_without_connections(2).await;

        // More loads than drivers: a driver that kept its slot after the
        // failure would leave the later loads to time out instead.
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
        // Every driver slot is taken and no driver runs, which is what
        // drivers stuck on unresponsive connections look like to a load.
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

        // The replacement serves the waiting load. It has no connection
        // to serve it with, so the load fails, but it is answered.
        assert!(matches!(
            answer.await,
            Ok(Err(error)) if matches!(*error, sqlx::Error::PoolClosed)
        ));
    }
}
