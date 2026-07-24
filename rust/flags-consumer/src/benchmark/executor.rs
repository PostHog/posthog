use std::collections::btree_map::Entry;
use std::collections::BTreeMap;
use std::future::Future;
use std::num::NonZeroUsize;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use common_database::is_transient_error;
use tokio::sync::{mpsc, Mutex};
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

use crate::storage::postgres::PostgresStorage;
use crate::storage::types::{DistinctIdAssignmentData, PersonDeletionData, PersonUpdateData};

use super::ops::{
    CompletionOutcome, CompletionRecord, DispatchedOperation, FullMergePayload, OpClass, OpPayload,
    ReadExpectation,
};
use super::scheduler::{BoundedDispatcher, PhaseClock};

const DEFAULT_READ_CAPACITY: usize = 28_948;
const DEFAULT_MERGE_CAPACITY: usize = 110;
const DEFAULT_PERSON_CAPACITY: usize = 11_576;
const DEFAULT_DISTINCT_ID_CAPACITY: usize = 7_188;

#[derive(Debug, Clone)]
pub struct ExecutorConfig {
    pub read_workers: NonZeroUsize,
    pub merge_workers: NonZeroUsize,
    pub person_batch_workers: NonZeroUsize,
    pub distinct_id_batch_workers: NonZeroUsize,
    pub batch_size: NonZeroUsize,
    pub batch_flush: Duration,
    pub batch_queue_capacity: NonZeroUsize,
    pub completion_queue_capacity: NonZeroUsize,
    pub ingress_capacities: IngressCapacities,
    pub retry: RetryConfig,
}

impl Default for ExecutorConfig {
    fn default() -> Self {
        Self {
            read_workers: nonzero(64),
            merge_workers: nonzero(16),
            person_batch_workers: nonzero(8),
            distinct_id_batch_workers: nonzero(8),
            batch_size: nonzero(500),
            batch_flush: Duration::from_millis(100),
            batch_queue_capacity: nonzero(32),
            completion_queue_capacity: nonzero(50_000),
            ingress_capacities: IngressCapacities::default(),
            retry: RetryConfig::default(),
        }
    }
}

const fn nonzero(value: usize) -> NonZeroUsize {
    match NonZeroUsize::new(value) {
        Some(value) => value,
        None => panic!("executor constants are nonzero"),
    }
}

#[derive(Debug, Clone, Copy)]
pub struct IngressCapacities {
    pub person_upsert: NonZeroUsize,
    pub distinct_id_assignment: NonZeroUsize,
    pub merge: NonZeroUsize,
    pub canonical_read: NonZeroUsize,
}

impl Default for IngressCapacities {
    fn default() -> Self {
        Self {
            person_upsert: nonzero(DEFAULT_PERSON_CAPACITY),
            distinct_id_assignment: nonzero(DEFAULT_DISTINCT_ID_CAPACITY),
            merge: nonzero(DEFAULT_MERGE_CAPACITY),
            canonical_read: nonzero(DEFAULT_READ_CAPACITY),
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct RetryConfig {
    pub max_retries: u32,
    pub backoff_base: Duration,
    pub attempt_timeout: Duration,
}

impl Default for RetryConfig {
    fn default() -> Self {
        Self {
            max_retries: 3,
            backoff_base: Duration::from_millis(50),
            attempt_timeout: Duration::from_secs(30),
        }
    }
}

#[derive(Debug)]
pub struct ExecutorIngress {
    dispatchers: [BoundedDispatcher; OpClass::COUNT],
}

impl ExecutorIngress {
    pub fn dispatcher_mut(&mut self, class: OpClass) -> &mut BoundedDispatcher {
        &mut self.dispatchers[class.index()]
    }

    pub fn shed_count(&self, class: OpClass) -> u64 {
        self.dispatchers[class.index()].shed_count()
    }

    pub fn into_dispatchers(self) -> ExecutorDispatchers {
        let [person_upserts, distinct_id_assignments, merges, canonical_reads] = self.dispatchers;
        ExecutorDispatchers {
            person_upserts,
            distinct_id_assignments,
            merges,
            canonical_reads,
        }
    }
}

#[derive(Debug)]
pub struct ExecutorDispatchers {
    pub person_upserts: BoundedDispatcher,
    pub distinct_id_assignments: BoundedDispatcher,
    pub merges: BoundedDispatcher,
    pub canonical_reads: BoundedDispatcher,
}

#[derive(Debug)]
pub struct ExecutorTasks {
    handles: Vec<JoinHandle<anyhow::Result<()>>>,
}

impl ExecutorTasks {
    pub async fn join(self) -> anyhow::Result<()> {
        let mut first_error = None;
        for handle in self.handles {
            match handle.await {
                Ok(Ok(())) => {}
                Ok(Err(error)) => {
                    first_error.get_or_insert(error);
                }
                Err(error) => {
                    first_error.get_or_insert_with(|| {
                        anyhow::Error::new(error).context("benchmark executor task panicked")
                    });
                }
            }
        }
        match first_error {
            Some(error) => Err(error),
            None => Ok(()),
        }
    }
}

#[derive(Debug)]
pub struct ExecutorRuntime {
    completion_receiver: mpsc::Receiver<CompletionRecord>,
    tasks: ExecutorTasks,
    cancellation: CancellationToken,
}

impl ExecutorRuntime {
    pub fn completion_receiver_mut(&mut self) -> &mut mpsc::Receiver<CompletionRecord> {
        &mut self.completion_receiver
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancellation.is_cancelled()
    }

    pub fn cancellation_token(&self) -> CancellationToken {
        self.cancellation.clone()
    }

    /// Drains completions until the workers exit. Callers must have dropped every
    /// ingress or dispatcher handle first, otherwise the workers never see a close.
    pub async fn drain<F>(mut self, mut record_completion: F) -> anyhow::Result<()>
    where
        F: FnMut(CompletionRecord) -> anyhow::Result<()>,
    {
        let mut drain_error = None;
        while let Some(completion) = self.completion_receiver.recv().await {
            if let Err(error) = record_completion(completion) {
                drain_error.get_or_insert(error);
            }
        }
        let task_result = self.tasks.join().await;
        task_result?;
        match drain_error {
            Some(error) => Err(error).context("record drained benchmark completion"),
            None => Ok(()),
        }
    }
}

pub fn start(
    storage: Arc<PostgresStorage>,
    clock: PhaseClock,
    config: ExecutorConfig,
) -> (ExecutorIngress, ExecutorRuntime) {
    let (person_dispatcher, person_receiver) =
        BoundedDispatcher::channel(config.ingress_capacities.person_upsert);
    let (distinct_id_dispatcher, distinct_id_receiver) =
        BoundedDispatcher::channel(config.ingress_capacities.distinct_id_assignment);
    let (merge_dispatcher, merge_receiver) =
        BoundedDispatcher::channel(config.ingress_capacities.merge);
    let (read_dispatcher, read_receiver) =
        BoundedDispatcher::channel(config.ingress_capacities.canonical_read);
    let ingress = ExecutorIngress {
        dispatchers: [
            person_dispatcher,
            distinct_id_dispatcher,
            merge_dispatcher,
            read_dispatcher,
        ],
    };

    let (completion_sender, completion_receiver) =
        mpsc::channel(config.completion_queue_capacity.get());
    let cancellation = CancellationToken::new();
    let (person_batch_sender, person_batch_receiver) =
        mpsc::channel(config.batch_queue_capacity.get());
    let (distinct_id_batch_sender, distinct_id_batch_receiver) =
        mpsc::channel(config.batch_queue_capacity.get());
    let mut handles = vec![
        tokio::spawn(run_batcher(
            person_receiver,
            person_batch_sender,
            config.batch_size,
            config.batch_flush,
            cancellation.clone(),
        )),
        tokio::spawn(run_batcher(
            distinct_id_receiver,
            distinct_id_batch_sender,
            config.batch_size,
            config.batch_flush,
            cancellation.clone(),
        )),
    ];

    let context = WorkerContext {
        storage,
        completion_sender,
        clock,
        retry: config.retry,
        cancellation: cancellation.clone(),
    };

    let person_batches = Arc::new(Mutex::new(person_batch_receiver));
    for _ in 0..config.person_batch_workers.get() {
        handles.push(tokio::spawn(run_batch_worker(
            context.clone(),
            Arc::clone(&person_batches),
            dedupe_person_updates,
            async |storage: &PostgresStorage, updates| storage.batch_upsert_persons(updates).await,
        )));
    }
    let distinct_id_batches = Arc::new(Mutex::new(distinct_id_batch_receiver));
    for _ in 0..config.distinct_id_batch_workers.get() {
        handles.push(tokio::spawn(run_batch_worker(
            context.clone(),
            Arc::clone(&distinct_id_batches),
            dedupe_distinct_id_assignments,
            async |storage: &PostgresStorage, assignments| {
                storage.batch_upsert_distinct_ids(assignments).await
            },
        )));
    }
    let merge_receiver = Arc::new(Mutex::new(merge_receiver));
    for _ in 0..config.merge_workers.get() {
        handles.push(tokio::spawn(run_merge_worker(
            context.clone(),
            Arc::clone(&merge_receiver),
        )));
    }
    let read_receiver = Arc::new(Mutex::new(read_receiver));
    for _ in 0..config.read_workers.get() {
        handles.push(tokio::spawn(run_read_worker(
            context.clone(),
            Arc::clone(&read_receiver),
        )));
    }
    drop(context);

    (
        ingress,
        ExecutorRuntime {
            completion_receiver,
            tasks: ExecutorTasks { handles },
            cancellation,
        },
    )
}

/// Plumbing every worker needs, so worker signatures carry only their own inputs.
#[derive(Clone)]
struct WorkerContext {
    storage: Arc<PostgresStorage>,
    completion_sender: mpsc::Sender<CompletionRecord>,
    clock: PhaseClock,
    retry: RetryConfig,
    cancellation: CancellationToken,
}

async fn run_batcher(
    mut receiver: mpsc::Receiver<DispatchedOperation>,
    sender: mpsc::Sender<Vec<DispatchedOperation>>,
    batch_size: NonZeroUsize,
    flush_after: Duration,
    cancellation: CancellationToken,
) -> anyhow::Result<()> {
    loop {
        let first = tokio::select! {
            biased;
            () = cancellation.cancelled() => break,
            operation = receiver.recv() => match operation {
                Some(operation) => operation,
                None => break,
            },
        };
        let mut batch = Vec::with_capacity(batch_size.get());
        batch.push(first);
        let deadline = tokio::time::Instant::now() + flush_after;
        while batch.len() < batch_size.get() {
            tokio::select! {
                biased;
                () = cancellation.cancelled() => return Ok(()),
                next = receiver.recv() => match next {
                    Some(operation) => batch.push(operation),
                    None => break,
                },
                () = tokio::time::sleep_until(deadline) => break,
            }
        }
        tokio::select! {
            biased;
            () = cancellation.cancelled() => break,
            result = sender.send(batch) => if result.is_err() {
                break;
            },
        }
    }
    Ok(())
}

async fn receive_shared<T>(
    receiver: &Mutex<mpsc::Receiver<T>>,
    cancellation: &CancellationToken,
) -> Option<T> {
    tokio::select! {
        biased;
        () = cancellation.cancelled() => None,
        item = async { receiver.lock().await.recv().await } => item,
    }
}

/// Shared batch-worker loop. `prepare` collapses a dispatched batch into the write
/// payload (dedupe rules differ per class) and `execute` issues the storage call.
async fn run_batch_worker<T, Prepare, Execute>(
    context: WorkerContext,
    receiver: Arc<Mutex<mpsc::Receiver<Vec<DispatchedOperation>>>>,
    prepare: Prepare,
    execute: Execute,
) -> anyhow::Result<()>
where
    Prepare: Fn(&[DispatchedOperation]) -> Result<Vec<T>, BatchPayloadError>,
    Execute: AsyncFn(&PostgresStorage, &[T]) -> Result<u64, sqlx::Error>,
{
    let WorkerContext {
        storage,
        completion_sender,
        clock,
        retry,
        cancellation,
    } = context;
    while let Some(batch) = receive_shared(&receiver, &cancellation).await {
        let payload = prepare(&batch);
        let started_at = clock.now()?;
        let execution = match payload {
            Ok(payload) => with_retry(retry, &cancellation, || execute(&storage, &payload)).await,
            Err(error) => RetryResult::<u64>::terminal(error.to_string()),
        };
        if execution.cancelled {
            return Ok(());
        }
        let terminal_error = execution.error.clone();
        let emission =
            emit_batch_completions(&batch, started_at, &execution, &clock, &completion_sender)
                .await;
        cancel_on_error(&emission, &cancellation);
        emission?;
        abort_after_terminal(terminal_error.as_deref(), &cancellation)?;
    }
    Ok(())
}

async fn run_read_worker(
    context: WorkerContext,
    receiver: Arc<Mutex<mpsc::Receiver<DispatchedOperation>>>,
) -> anyhow::Result<()> {
    let WorkerContext {
        storage,
        completion_sender,
        clock,
        retry,
        cancellation,
    } = context;
    while let Some(operation) = receive_shared(&receiver, &cancellation).await {
        let prepared = match &operation.descriptor().payload {
            OpPayload::CanonicalRead(payload) => Ok(payload.clone()),
            payload => Err(format!(
                "read worker received {:?} operation",
                payload.class()
            )),
        };
        let started_at = clock.now()?;
        let execution = match prepared {
            Ok(payload) => {
                with_retry(retry, &cancellation, || {
                    storage.get_person_by_distinct_id(payload.team_id, &payload.distinct_id)
                })
                .await
            }
            Err(error) => RetryResult::terminal(error),
        };
        if execution.cancelled {
            return Ok(());
        }
        let mut terminal_error = execution.error.clone();
        if terminal_error.is_none() {
            let payload = match &operation.descriptor().payload {
                OpPayload::CanonicalRead(payload) => payload,
                _ => unreachable!("prepared canonical read"),
            };
            let found = execution
                .value
                .as_ref()
                .expect("successful retry result has a value")
                .is_some();
            terminal_error = validate_read_expectation(&payload.expectation, found).err();
        }
        let emission = emit_completion(
            &operation,
            started_at,
            terminal_error.as_deref(),
            execution.stats,
            &clock,
            &completion_sender,
        )
        .await;
        cancel_on_error(&emission, &cancellation);
        emission?;
        abort_after_terminal(terminal_error.as_deref(), &cancellation)?;
    }
    Ok(())
}

async fn run_merge_worker(
    context: WorkerContext,
    receiver: Arc<Mutex<mpsc::Receiver<DispatchedOperation>>>,
) -> anyhow::Result<()> {
    let WorkerContext {
        storage,
        completion_sender,
        clock,
        retry,
        cancellation,
    } = context;
    while let Some(operation) = receive_shared(&receiver, &cancellation).await {
        let prepared = match &operation.descriptor().payload {
            OpPayload::FullMerge(payload) => Ok(prepare_merge(payload)),
            payload => Err(format!(
                "merge worker received {:?} operation",
                payload.class()
            )),
        };
        let started_at = clock.now()?;
        let execution = match prepared {
            Ok(prepared) => execute_merge(&storage, &prepared, retry, &cancellation).await,
            Err(error) => RetryResult::<u64>::terminal(error),
        };
        if execution.cancelled {
            return Ok(());
        }
        let terminal_error = execution.error.clone();
        let emission = emit_completion(
            &operation,
            started_at,
            execution.error.as_deref(),
            execution.stats,
            &clock,
            &completion_sender,
        )
        .await;
        cancel_on_error(&emission, &cancellation);
        emission?;
        abort_after_terminal(terminal_error.as_deref(), &cancellation)?;
    }
    Ok(())
}

async fn execute_merge(
    storage: &PostgresStorage,
    merge: &PreparedMerge,
    retry: RetryConfig,
    cancellation: &CancellationToken,
) -> RetryResult<u64> {
    // Production commits these version-guarded batches independently as well;
    // replay converges a partial merge after a later step fails.
    let mut result = with_retry(retry, cancellation, || {
        storage.batch_upsert_distinct_ids(&merge.assignments)
    })
    .await;
    if result.error.is_none() {
        let next = with_retry(retry, cancellation, || {
            storage.batch_upsert_persons(&merge.target)
        })
        .await;
        result.merge_from(next);
    }
    if result.error.is_none() && !result.cancelled {
        let next = with_retry(retry, cancellation, || {
            storage.batch_delete_persons(&merge.source)
        })
        .await;
        result.merge_from(next);
    }
    result
}

#[derive(Debug)]
struct PreparedMerge {
    assignments: Vec<DistinctIdAssignmentData>,
    target: [PersonUpdateData; 1],
    source: [PersonDeletionData; 1],
}

fn prepare_merge(payload: &FullMergePayload) -> PreparedMerge {
    let mut assignments = payload
        .distinct_id_moves
        .iter()
        .map(|distinct_id| DistinctIdAssignmentData {
            team_id: payload.team_id,
            person_uuid: payload.target_person_uuid,
            distinct_id: distinct_id.distinct_id.clone(),
            version: distinct_id.version,
        })
        .collect::<Vec<_>>();
    assignments.sort_by(|left, right| {
        (left.team_id, left.distinct_id.as_ref()).cmp(&(right.team_id, right.distinct_id.as_ref()))
    });
    PreparedMerge {
        assignments,
        target: [PersonUpdateData {
            team_id: payload.team_id,
            person_uuid: payload.target_person_uuid,
            properties: payload.target_properties.clone(),
            version: payload.target_version,
        }],
        source: [PersonDeletionData {
            team_id: payload.team_id,
            person_uuid: payload.source_person_uuid,
            version: payload.source_tombstone_version,
        }],
    }
}

fn validate_read_expectation(expectation: &ReadExpectation, found: bool) -> Result<(), String> {
    match (expectation, found) {
        (ReadExpectation::Hit, true) | (ReadExpectation::Miss, false) => Ok(()),
        (ReadExpectation::Hit, false) => {
            Err("canonical read expected a hit but returned no person".to_owned())
        }
        (ReadExpectation::Miss, true) => {
            Err("canonical read expected a miss but returned a person".to_owned())
        }
    }
}

fn abort_after_terminal(
    terminal_error: Option<&str>,
    cancellation: &CancellationToken,
) -> anyhow::Result<()> {
    let Some(error) = terminal_error else {
        return Ok(());
    };
    cancellation.cancel();
    Err(anyhow::anyhow!(
        "terminal benchmark operation failure: {error}"
    ))
}

fn cancel_on_error<T>(result: &anyhow::Result<T>, cancellation: &CancellationToken) {
    if result.is_err() {
        cancellation.cancel();
    }
}

#[derive(Debug, Clone, Copy, Default)]
struct RetryStats {
    retries: u32,
    deadlocks: u32,
}

impl RetryStats {
    fn merge(&mut self, other: Self) {
        self.retries = self.retries.saturating_add(other.retries);
        self.deadlocks = self.deadlocks.saturating_add(other.deadlocks);
    }
}

#[derive(Debug)]
struct RetryResult<T> {
    value: Option<T>,
    error: Option<String>,
    stats: RetryStats,
    cancelled: bool,
}

impl<T> RetryResult<T> {
    fn terminal(error: String) -> Self {
        Self {
            value: None,
            error: Some(error),
            stats: RetryStats::default(),
            cancelled: false,
        }
    }

    fn cancelled(stats: RetryStats) -> Self {
        Self {
            value: None,
            error: None,
            stats,
            cancelled: true,
        }
    }

    fn merge_from<U>(&mut self, other: RetryResult<U>) {
        self.stats.merge(other.stats);
        self.cancelled |= other.cancelled;
        if self.error.is_none() {
            self.error = other.error;
        }
    }
}

async fn with_retry<T, F, Fut>(
    retry: RetryConfig,
    cancellation: &CancellationToken,
    mut operation: F,
) -> RetryResult<T>
where
    F: FnMut() -> Fut,
    Fut: Future<Output = Result<T, sqlx::Error>>,
{
    let mut stats = RetryStats::default();
    loop {
        let result = tokio::select! {
            biased;
            () = cancellation.cancelled() => return RetryResult::cancelled(stats),
            result = tokio::time::timeout(retry.attempt_timeout, operation()) => result,
        };
        let result = match result {
            Ok(result) => result,
            Err(_) => {
                return RetryResult {
                    value: None,
                    error: Some(format!(
                        "database attempt timed out after {:.1}s",
                        retry.attempt_timeout.as_secs_f64()
                    )),
                    stats,
                    cancelled: false,
                }
            }
        };
        match result {
            Ok(value) => {
                return RetryResult {
                    value: Some(value),
                    error: None,
                    stats,
                    cancelled: false,
                }
            }
            Err(error) => {
                if is_deadlock(&error) {
                    stats.deadlocks = stats.deadlocks.saturating_add(1);
                }
                if !is_transient_error(&error) || stats.retries >= retry.max_retries {
                    return RetryResult {
                        value: None,
                        error: Some(error.to_string()),
                        stats,
                        cancelled: false,
                    };
                }
                let multiplier = 1u32 << stats.retries.min(31);
                stats.retries = stats.retries.saturating_add(1);
                tokio::select! {
                    biased;
                    () = cancellation.cancelled() => return RetryResult::cancelled(stats),
                    () = tokio::time::sleep(retry.backoff_base.saturating_mul(multiplier)) => {}
                }
            }
        }
    }
}

fn is_deadlock(error: &sqlx::Error) -> bool {
    match error {
        sqlx::Error::Database(database_error) => {
            database_error
                .code()
                .is_some_and(|code| code.as_ref() == "40P01")
                || database_error.message().to_lowercase().contains("deadlock")
        }
        _ => false,
    }
}

async fn emit_batch_completions(
    batch: &[DispatchedOperation],
    started_at: super::ops::NanosSincePhaseStart,
    execution: &RetryResult<u64>,
    clock: &PhaseClock,
    sender: &mpsc::Sender<CompletionRecord>,
) -> anyhow::Result<()> {
    let completed_at = clock.now()?;
    for (index, operation) in batch.iter().enumerate() {
        let attributed_stats = if index == 0 {
            execution.stats
        } else {
            RetryStats::default()
        };
        let completion = build_completion(
            operation,
            started_at,
            completed_at,
            execution.error.as_deref(),
            execution.stats,
            attributed_stats,
        )?;
        sender
            .send(completion)
            .await
            .map_err(|_| anyhow::anyhow!("benchmark completion collector closed"))?;
    }
    Ok(())
}

async fn emit_completion(
    operation: &DispatchedOperation,
    started_at: super::ops::NanosSincePhaseStart,
    error: Option<&str>,
    stats: RetryStats,
    clock: &PhaseClock,
    sender: &mpsc::Sender<CompletionRecord>,
) -> anyhow::Result<()> {
    let completed_at = clock.now()?;
    let completion = build_completion(operation, started_at, completed_at, error, stats, stats)?;
    sender
        .send(completion)
        .await
        .map_err(|_| anyhow::anyhow!("benchmark completion collector closed"))
}

fn build_completion(
    operation: &DispatchedOperation,
    started_at: super::ops::NanosSincePhaseStart,
    completed_at: super::ops::NanosSincePhaseStart,
    error: Option<&str>,
    affected_stats: RetryStats,
    attributed_stats: RetryStats,
) -> anyhow::Result<CompletionRecord> {
    let timestamps = operation.completion_timestamps(started_at, completed_at)?;
    let outcome = match error {
        Some(message) => CompletionOutcome::Error {
            message: message.into(),
        },
        None => CompletionOutcome::Success,
    };
    Ok(CompletionRecord {
        operation_id: operation.operation_id(),
        class: operation.class(),
        timestamps,
        outcome,
        retry_affected: affected_stats.retries > 0,
        deadlock_affected: affected_stats.deadlocks > 0,
        retry_attempts: attributed_stats.retries,
        deadlock_attempts: attributed_stats.deadlocks,
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum BatchPayloadError {
    Person,
    DistinctId,
}

impl std::fmt::Display for BatchPayloadError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Person => formatter.write_str("person batch received a non-person operation"),
            Self::DistinctId => {
                formatter.write_str("distinct ID batch received a non-assignment operation")
            }
        }
    }
}

fn dedupe_person_updates(
    batch: &[DispatchedOperation],
) -> Result<Vec<PersonUpdateData>, BatchPayloadError> {
    let mut updates = BTreeMap::<(i32, uuid::Uuid), PersonUpdateData>::new();
    for operation in batch {
        let OpPayload::PersonUpsert(payload) = &operation.descriptor().payload else {
            return Err(BatchPayloadError::Person);
        };
        let candidate = PersonUpdateData {
            team_id: payload.team_id,
            person_uuid: payload.person_uuid,
            properties: payload.properties.clone(),
            version: payload.version,
        };
        match updates.entry((payload.team_id, payload.person_uuid)) {
            Entry::Vacant(entry) => {
                entry.insert(candidate);
            }
            Entry::Occupied(mut entry) if candidate.version > entry.get().version => {
                entry.insert(candidate);
            }
            Entry::Occupied(_) => {}
        }
    }
    Ok(updates.into_values().collect())
}

fn dedupe_distinct_id_assignments(
    batch: &[DispatchedOperation],
) -> Result<Vec<DistinctIdAssignmentData>, BatchPayloadError> {
    let mut assignments = BTreeMap::<(i32, Box<str>), DistinctIdAssignmentData>::new();
    for operation in batch {
        let OpPayload::DistinctIdAssignment(payload) = &operation.descriptor().payload else {
            return Err(BatchPayloadError::DistinctId);
        };
        let candidate = DistinctIdAssignmentData {
            team_id: payload.team_id,
            person_uuid: payload.person_uuid,
            distinct_id: payload.distinct_id.clone(),
            version: payload.version,
        };
        let key = (payload.team_id, payload.distinct_id.clone());
        match assignments.entry(key) {
            Entry::Vacant(entry) => {
                entry.insert(candidate);
            }
            Entry::Occupied(mut entry)
                if (candidate.version, candidate.person_uuid)
                    > (entry.get().version, entry.get().person_uuid) =>
            {
                entry.insert(candidate);
            }
            Entry::Occupied(_) => {}
        }
    }
    Ok(assignments.into_values().collect())
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};

    use serde_json::json;

    use super::*;
    use crate::benchmark::ops::{
        DistinctIdAssignmentPayload, DistinctIdMove, FullMergePayload, MergeShape,
        NanosSincePhaseStart, OpDescriptor, OperationId, PersonUpsertPayload, PhaseId,
    };

    const TEST_PHASE: PhaseId = PhaseId::new(1);

    fn dispatched(id: u64, payload: OpPayload) -> DispatchedOperation {
        let scheduled_at = NanosSincePhaseStart::from_nanos(TEST_PHASE, 0);
        DispatchedOperation::try_new(
            OpDescriptor::new(OperationId(id), scheduled_at, payload),
            scheduled_at,
        )
        .expect("on-time dispatch")
    }

    #[test]
    fn batch_dedupe_matches_processor_order_and_tie_breaks() {
        let first_person = uuid::Uuid::from_u128(1);
        let second_person = uuid::Uuid::from_u128(2);
        let person_batch = [
            dispatched(
                1,
                OpPayload::PersonUpsert(PersonUpsertPayload {
                    team_id: 2,
                    person_uuid: second_person,
                    properties: json!({"winner": "team_two"}),
                    version: 1,
                }),
            ),
            dispatched(
                2,
                OpPayload::PersonUpsert(PersonUpsertPayload {
                    team_id: 1,
                    person_uuid: second_person,
                    properties: json!({"winner": "high_version"}),
                    version: 3,
                }),
            ),
            dispatched(
                3,
                OpPayload::PersonUpsert(PersonUpsertPayload {
                    team_id: 1,
                    person_uuid: second_person,
                    properties: json!({"winner": "equal_version_late"}),
                    version: 3,
                }),
            ),
            dispatched(
                4,
                OpPayload::PersonUpsert(PersonUpsertPayload {
                    team_id: 1,
                    person_uuid: first_person,
                    properties: json!({}),
                    version: 1,
                }),
            ),
        ];
        let persons = dedupe_person_updates(&person_batch).expect("person payloads");

        assert_eq!(persons.len(), 3);
        assert_eq!(
            persons
                .iter()
                .map(|person| (person.team_id, person.person_uuid))
                .collect::<Vec<_>>(),
            vec![(1, first_person), (1, second_person), (2, second_person)]
        );
        assert_eq!(persons[1].properties, json!({"winner": "high_version"}));

        let did_batch = [
            dispatched(
                5,
                OpPayload::DistinctIdAssignment(DistinctIdAssignmentPayload {
                    team_id: 2,
                    person_uuid: first_person,
                    distinct_id: "z".into(),
                    version: 1,
                }),
            ),
            dispatched(
                6,
                OpPayload::DistinctIdAssignment(DistinctIdAssignmentPayload {
                    team_id: 1,
                    person_uuid: first_person,
                    distinct_id: "a".into(),
                    version: 4,
                }),
            ),
            dispatched(
                7,
                OpPayload::DistinctIdAssignment(DistinctIdAssignmentPayload {
                    team_id: 1,
                    person_uuid: second_person,
                    distinct_id: "a".into(),
                    version: 4,
                }),
            ),
        ];
        let distinct_ids =
            dedupe_distinct_id_assignments(&did_batch).expect("distinct ID payloads");

        assert_eq!(distinct_ids.len(), 2);
        assert_eq!(&*distinct_ids[0].distinct_id, "a");
        assert_eq!(distinct_ids[0].person_uuid, second_person);
        assert_eq!(
            (distinct_ids[1].team_id, &*distinct_ids[1].distinct_id),
            (2, "z")
        );
    }

    #[test]
    fn read_expectation_rejects_both_correctness_mismatches() {
        for (expectation, found, message) in [
            (ReadExpectation::Hit, false, "expected a hit"),
            (ReadExpectation::Miss, true, "expected a miss"),
        ] {
            let error = validate_read_expectation(&expectation, found)
                .expect_err("mismatched read must fail");
            assert!(error.contains(message));
        }
        assert!(validate_read_expectation(&ReadExpectation::Hit, true).is_ok());
        assert!(validate_read_expectation(&ReadExpectation::Miss, false).is_ok());
    }

    #[test]
    fn merge_preparation_sorts_distinct_id_moves_by_primary_key() {
        let payload = FullMergePayload {
            team_id: 7,
            source_person_uuid: uuid::Uuid::from_u128(1),
            target_person_uuid: uuid::Uuid::from_u128(2),
            distinct_id_moves: vec![
                DistinctIdMove {
                    distinct_id: "z".into(),
                    version: 2,
                },
                DistinctIdMove {
                    distinct_id: "a".into(),
                    version: 3,
                },
                DistinctIdMove {
                    distinct_id: "m".into(),
                    version: 4,
                },
            ]
            .into_boxed_slice(),
            target_properties: json!({}),
            target_version: 5,
            source_tombstone_version: 101,
            shape: MergeShape::Standard,
        };

        let prepared = prepare_merge(&payload);

        assert_eq!(
            prepared
                .assignments
                .iter()
                .map(|assignment| assignment.distinct_id.as_ref())
                .collect::<Vec<_>>(),
            vec!["a", "m", "z"]
        );
    }

    #[tokio::test(start_paused = true)]
    async fn batch_retry_attempts_are_attributed_once_without_losing_affected_flags() {
        let batch = [
            dispatched(
                10,
                OpPayload::PersonUpsert(PersonUpsertPayload {
                    team_id: 1,
                    person_uuid: uuid::Uuid::from_u128(1),
                    properties: json!({}),
                    version: 1,
                }),
            ),
            dispatched(
                11,
                OpPayload::PersonUpsert(PersonUpsertPayload {
                    team_id: 1,
                    person_uuid: uuid::Uuid::from_u128(2),
                    properties: json!({}),
                    version: 1,
                }),
            ),
        ];
        let execution = RetryResult {
            value: Some(2),
            error: None,
            stats: RetryStats {
                retries: 2,
                deadlocks: 1,
            },
            cancelled: false,
        };
        let clock = PhaseClock::start_now(TEST_PHASE);
        let (sender, mut receiver) = mpsc::channel(2);

        emit_batch_completions(
            &batch,
            clock.now().expect("phase time"),
            &execution,
            &clock,
            &sender,
        )
        .await
        .expect("emit completions");
        let first = receiver.recv().await.expect("first completion");
        let second = receiver.recv().await.expect("second completion");

        assert!(first.retry_affected && second.retry_affected);
        assert!(first.deadlock_affected && second.deadlock_affected);
        assert_eq!(first.retry_attempts + second.retry_attempts, 2);
        assert_eq!(first.deadlock_attempts + second.deadlock_attempts, 1);
    }

    #[tokio::test]
    async fn coordinated_close_drains_more_completions_than_channel_capacity() {
        let mut dispatchers = Vec::with_capacity(OpClass::COUNT);
        for _ in 0..OpClass::COUNT {
            let (dispatcher, receiver) = BoundedDispatcher::channel(nonzero(1));
            drop(receiver);
            dispatchers.push(dispatcher);
        }
        let ingress = ExecutorIngress {
            dispatchers: dispatchers.try_into().expect("four dispatchers"),
        };
        let (sender, receiver) = mpsc::channel(1);
        let producer = tokio::spawn(async move {
            for operation_id in 1..=3 {
                let operation = dispatched(
                    operation_id,
                    OpPayload::PersonUpsert(PersonUpsertPayload {
                        team_id: 1,
                        person_uuid: uuid::Uuid::from_u128(operation_id as u128),
                        properties: json!({}),
                        version: 1,
                    }),
                );
                let completion = build_completion(
                    &operation,
                    NanosSincePhaseStart::from_nanos(TEST_PHASE, 0),
                    NanosSincePhaseStart::from_nanos(TEST_PHASE, 0),
                    None,
                    RetryStats::default(),
                    RetryStats::default(),
                )?;
                sender
                    .send(completion)
                    .await
                    .map_err(|_| anyhow::anyhow!("receiver closed"))?;
            }
            Ok(())
        });
        let runtime = ExecutorRuntime {
            completion_receiver: receiver,
            tasks: ExecutorTasks {
                handles: vec![producer],
            },
            cancellation: CancellationToken::new(),
        };
        let mut drained = 0;

        drop(ingress);
        tokio::time::timeout(
            Duration::from_secs(1),
            runtime.drain(|_| {
                drained += 1;
                Ok(())
            }),
        )
        .await
        .expect("coordinated drain must not deadlock")
        .expect("normal shutdown");

        assert_eq!(drained, 3);
    }

    #[tokio::test]
    async fn cancellation_stops_before_starting_another_database_attempt() {
        let cancellation = CancellationToken::new();
        cancellation.cancel();
        let attempts = AtomicUsize::new(0);

        let result: RetryResult<()> = with_retry(RetryConfig::default(), &cancellation, || async {
            attempts.fetch_add(1, Ordering::Relaxed);
            Ok::<(), sqlx::Error>(())
        })
        .await;

        assert!(result.cancelled);
        assert_eq!(attempts.load(Ordering::Relaxed), 0);
    }

    #[tokio::test]
    async fn database_attempts_have_a_finite_timeout() {
        let cancellation = CancellationToken::new();
        let retry = RetryConfig {
            attempt_timeout: Duration::from_millis(1),
            ..RetryConfig::default()
        };

        let result: RetryResult<()> = with_retry(retry, &cancellation, || async {
            std::future::pending::<Result<(), sqlx::Error>>().await
        })
        .await;

        assert!(result
            .error
            .is_some_and(|error| error.contains("database attempt timed out")));
    }
}
