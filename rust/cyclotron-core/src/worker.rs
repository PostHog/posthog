use std::{
    collections::HashMap,
    future::Future,
    sync::{Arc, Weak},
    task::Poll,
};

use chrono::{DateTime, Duration, Utc};
use futures::FutureExt;
use sqlx::PgPool;
use std::sync::Mutex;
use tokio::sync::oneshot;
use tracing::error;
use uuid::Uuid;

use crate::{
    config::WorkerConfig,
    error::JobError,
    ops::{
        meta::{dead_letter, run_migrations},
        worker::{dequeue_jobs, dequeue_with_vm_state, flush_job, get_vm_state, set_heartbeat},
    },
    types::Bytes,
    Job, JobState, JobUpdate, PoolConfig, QueueError,
};

// The worker's interface to the underlying queue system - a worker can do everything except
// create jobs (because job creation has to be shard-aware).
//
// This interface looks stange, because a lot of things that would normally be done with lifetimes
// and references are done with uuid's instead (and we lose some nice raii stuff as a result), but
// the reason for this is that this is designed to be embedded in other runtimes, where handing out
// lifetime'd references or things with drop impls isn't really practical. This makes it a little
// awkward to use, but since it's meant to be the core of other abstractions, I think it's ok for
// now (client libraries should wrap this to provide better interfaces).
pub struct Worker {
    pool: PgPool,
    // All the jobs the worker is currently working on, and hasn't released for returning
    // to the queue.
    // TRICKY - this is a sync mutex, because that simplifies using the manager in an FFI
    // context (since most functions below can be sync). We have to be careful never to
    // hold a lock across an await point, though.
    running: Mutex<HashMap<Uuid, JobUpdate>>,

    // When a user calls release, we queue up the update to be flushed, but only flush on
    // some conditions.
    flush_batch: Arc<Mutex<FlushBatch>>,

    pub heartbeat_window: Duration, // The worker will only pass one heartbeat to the DB per job every heartbeat_window
    pub linger: Duration,           // Updates will be held at most this long
    pub max_buffered: usize,        // Updates will be flushed after this many are buffered
    pub max_bytes: usize, // Updates will be flushed after the vm_state and blob sizes combined exceed this
    pub should_compress_vm_state: bool, // Compress vm_state when persisting to the DB?
}

impl Worker {
    pub async fn new(pool: PoolConfig, worker: WorkerConfig) -> Result<Self, QueueError> {
        let pool = pool.connect().await?;
        Ok(Self::from_pool(pool, worker))
    }

    pub fn from_pool(pool: PgPool, worker_config: WorkerConfig) -> Self {
        let worker = Self {
            pool,
            running: Default::default(),
            heartbeat_window: worker_config.heartbeat_window(),
            flush_batch: Arc::new(Mutex::new(FlushBatch::new(
                worker_config.should_compress_vm_state(),
            ))),
            linger: worker_config.linger_time(),
            max_buffered: worker_config.max_updates_buffered(),
            max_bytes: worker_config.max_bytes_buffered(),
            should_compress_vm_state: worker_config.should_compress_vm_state(),
        };

        tokio::spawn(flush_loop(
            worker.pool.clone(),
            Arc::downgrade(&worker.flush_batch),
            worker.max_buffered,
            worker.max_bytes,
            worker_config.flush_loop_interval(),
        ));

        worker
    }

    /// Run the latest cyclotron migrations. Panics if the migrations can't be run - failure to run migrations is purposefully fatal.
    pub async fn run_migrations(&self) {
        run_migrations(&self.pool).await;
    }

    /// Dequeues jobs from the queue, and returns them. Job sorting happens at the queue level,
    /// workers can't provide any filtering or sorting criteria - queue managers decide which jobs are run,
    /// workers just run them.
    pub async fn dequeue_jobs(&self, queue: &str, limit: usize) -> Result<Vec<Job>, QueueError> {
        let jobs = dequeue_jobs(&self.pool, queue, limit).await?;

        let mut running = self.running.lock().unwrap();
        for job in &jobs {
            // We need to hang onto the locks for a job until we flush it, so we can send updates.
            let update = JobUpdate::new(
                job.lock_id
                    .expect("Yell at oliver that the dequeuing code is broken. He's very sorry that your process just panicked"),
            );
            running.insert(job.id, update);
        }

        Ok(jobs)
    }

    /// This is the same as dequeue_jobs, but it also returns the vm_state of the job
    pub async fn dequeue_with_vm_state(
        &self,
        queue: &str,
        limit: usize,
    ) -> Result<Vec<Job>, QueueError> {
        let jobs = dequeue_with_vm_state(&self.pool, queue, limit).await?;

        let mut running = self.running.lock().unwrap();
        for job in &jobs {
            // We need to hang onto the locks for a job until we flush it, so we can send updates.
            let update = JobUpdate::new(
                job.lock_id
                    .expect("Yell at oliver that the dequeuing (with vm) code is broken. He's very sorry that your process just panicked"),
            );
            running.insert(job.id, update);
        }

        Ok(jobs)
    }

    /// Retrieve the VM state for a job, if, for example, you dequeued it and then realised you
    /// need the VM state as well.
    pub async fn get_vm_state(&self, job_id: Uuid) -> Result<Option<Bytes>, QueueError> {
        let lock_id = {
            let pending = self.running.lock().unwrap();
            pending
                .get(&job_id)
                .ok_or(JobError::UnknownJobId(job_id))?
                .lock_id
        };

        get_vm_state(&self.pool, job_id, lock_id).await
    }

    /// Release a job back to the queue. Callers are returned a flush handle, which they
    /// may use to await the flushing of the updated job state, which happens asynchronously
    /// to allow for batching of updates. Callers may drop the flush handle without impacting
    /// the flushing of the update. This function returns an error if the caller tries to release
    /// a job that this `Worker` doesn't know about, or if the worker tries to release a job
    /// without having provided a next state for it.
    ///
    /// The flush handle returned here will resolve to an error if the asynchronous flush operation
    /// fails in non-retryable fashion. Retryable errors during flush are not surfaced to the handle,
    /// and the flush will be retried until it succeeds, a non-retryable error is encountered (e.g.
    /// this workers lock on the job has been lost), or until the deadline is exceeded, if one is
    /// provided. All updates will have at least one flush attempt.
    pub fn release_job(&self, job_id: Uuid, deadline: Option<Duration>) -> FlushHandle {
        let update = {
            let mut running = self.running.lock().unwrap();
            let Some(update) = running.remove(&job_id) else {
                return FlushHandle::immediate(Err(JobError::UnknownJobId(job_id)));
            };
            match update.state {
                Some(JobState::Running) | None => {
                    // Keep track of any /other/ updates that might have been stored, so this
                    // error is recoverable simply by providing an appropriate new state.
                    running.insert(job_id, update);
                    return FlushHandle::immediate(Err(JobError::FlushWithoutNextState(job_id)));
                }
                _ => update,
            }
        };

        // If we were given a deadline, this update should be flushed at least as soon as then,
        // otherwise we can wait the full linger time before flushing it.
        let now = Utc::now();
        let flush_by = now + deadline.unwrap_or(self.linger);
        let deadline = deadline.map(|d| now + d);

        let (pending, handle) = PendingUpdate::new(job_id, update, deadline);

        let mut batch = self.flush_batch.lock().unwrap();
        batch.add(pending, flush_by);
        handle
    }

    /// Force flush all pending updates, regardless of linger time or buffer size.
    /// Transient errors encountered during the flush will cause the operation to
    /// be aborted, and the error to be returned to the caller. If no transient errors
    /// are encountered, all permanent errors will be dispatched to the relevant flush
    /// handle, and this function will return success.
    pub async fn force_flush(&self) -> Result<(), QueueError> {
        let mut to_flush = { self.flush_batch.lock().unwrap().take() };
        let res = if !to_flush.pending.is_empty() {
            to_flush.flush(&self.pool).await
        } else {
            Ok(())
        };
        // If the flush successed, to_flush is empty, otherwise, we need to retry any
        // updates still in it.
        self.flush_batch.lock().unwrap().merge(to_flush);
        res
    }

    /// Jobs are reaped after some seconds (the number is deployment specific, and may become
    /// specific on job properties like queue name in the future, as we figure out what /kinds/ of
    /// jobs are longer or shorter running). A job is considered "dead" if it's in a running state,
    /// and it's last heartbeat was more than the reaping time ago. This, like flush, returns an
    /// error if you try to set the heartbeat on a job whose lock you don't have (which can happen
    /// if e.g. the job was reaped out from under you).
    pub async fn heartbeat(&self, job_id: Uuid) -> Result<(), QueueError> {
        let lock_id = {
            let mut pending = self.running.lock().unwrap();
            let update = pending
                .get_mut(&job_id)
                .ok_or(JobError::UnknownJobId(job_id))?;

            let should_heartbeat = update
                .last_heartbeat
                .is_none_or(|last| Utc::now() - last > self.heartbeat_window);

            if !should_heartbeat {
                return Ok(());
            }

            update.last_heartbeat = Some(Utc::now());
            update.lock_id
        };
        let mut connection = self.pool.acquire().await?;
        set_heartbeat(connection.as_mut(), job_id, lock_id).await
    }

    /// This is how you "return" a job to the queue, by setting the state to "available"
    pub fn set_state(&self, job_id: Uuid, state: JobState) -> Result<(), JobError> {
        let mut pending = self.running.lock().unwrap();
        pending
            .get_mut(&job_id)
            .ok_or(JobError::UnknownJobId(job_id))?
            .state = Some(state);
        Ok(())
    }

    pub fn set_queue(&self, job_id: Uuid, queue: &str) -> Result<(), JobError> {
        let mut pending = self.running.lock().unwrap();
        pending
            .get_mut(&job_id)
            .ok_or(JobError::UnknownJobId(job_id))?
            .queue_name = Some(queue.to_string());
        Ok(())
    }

    /// Jobs are dequeued lowest-priority-first, so this is how you change the "base" priority of a job
    /// (control tables may apply further deltas if e.g. a given function is in a degraded state)
    pub fn set_priority(&self, job_id: Uuid, priority: i16) -> Result<(), JobError> {
        let mut pending = self.running.lock().unwrap();
        pending
            .get_mut(&job_id)
            .ok_or(JobError::UnknownJobId(job_id))?
            .priority = Some(priority);
        Ok(())
    }

    /// This is how you do e.g. retries after some time, by setting the scheduled time
    /// to some time in the future. Sleeping, retry backoff, scheduling - it's all the same operation,
    /// this one.
    pub fn set_scheduled_at(&self, job_id: Uuid, scheduled: DateTime<Utc>) -> Result<(), JobError> {
        let mut pending = self.running.lock().unwrap();
        pending
            .get_mut(&job_id)
            .ok_or(JobError::UnknownJobId(job_id))?
            .scheduled = Some(scheduled);
        Ok(())
    }

    /// Passing None here will clear the vm_state
    pub fn set_vm_state(
        &self,
        job_id: Uuid,
        vm_state: Option<Bytes>, // This (and the following) are Options, because the user can null them (by calling with None)
    ) -> Result<(), JobError> {
        let mut pending = self.running.lock().unwrap();
        pending
            .get_mut(&job_id)
            .ok_or(JobError::UnknownJobId(job_id))?
            .vm_state = Some(vm_state); // conditional compression applied in ops/worker.rs flush_job()
        Ok(())
    }

    /// Passing None here will clear the metadata
    pub fn set_metadata(&self, job_id: Uuid, metadata: Option<Bytes>) -> Result<(), JobError> {
        let mut pending = self.running.lock().unwrap();
        pending
            .get_mut(&job_id)
            .ok_or(JobError::UnknownJobId(job_id))?
            .metadata = Some(metadata);
        Ok(())
    }

    /// Passing None here will clear the parameters
    pub fn set_parameters(&self, job_id: Uuid, parameters: Option<Bytes>) -> Result<(), JobError> {
        let mut pending = self.running.lock().unwrap();
        pending
            .get_mut(&job_id)
            .ok_or(JobError::UnknownJobId(job_id))?
            .parameters = Some(parameters);
        Ok(())
    }

    pub async fn dead_letter(&self, job_id: Uuid, reason: &str) -> Result<(), QueueError> {
        // KLUDGE: Non-lexical lifetimes are good but they're just not perfect yet -
        // changing this to not be a scope bump, and instead explicitly drop'ing the
        // lock after the if check, makes the compiler think the lock is held across
        // the await point.
        {
            let pending = self.running.lock().unwrap();
            if !pending.contains_key(&job_id) {
                return Err(JobError::UnknownJobId(job_id).into());
            }
        }

        dead_letter(&self.pool, job_id, reason).await
    }

    /// Passing None here will clear the blob
    pub fn set_blob(&self, job_id: Uuid, blob: Option<Bytes>) -> Result<(), JobError> {
        let mut pending = self.running.lock().unwrap();
        pending
            .get_mut(&job_id)
            .ok_or(JobError::UnknownJobId(job_id))?
            .blob = Some(blob);
        Ok(())
    }
}

// Started by each worker on creation, just loops seeing if the passed batch can be flushed, and
// if it can, flushing it.
async fn flush_loop(
    pool: PgPool,
    batch: Weak<Mutex<FlushBatch>>,
    max_buffered: usize,
    max_bytes: usize,
    interval: Duration,
) {
    loop {
        let Some(batch) = batch.upgrade() else {
            // The batch has been dropped, we should exit.
            break;
        };
        // Contemplating sync mutexes on the tree of woe.
        let mut to_flush = { batch.lock().unwrap().take() };
        if to_flush.should_flush(max_buffered, max_bytes) {
            if let Err(e) = to_flush.flush(&pool).await {
                error!("Error flushing batch: {:?}", e);
            }
        }
        // We can always merge the taken batch back into the pending batch - on successful
        // flush, the taken batch will be empty, and on failure, we need to re-queue those updates.
        // TRICKY - we take care not to bind the lock here. Compilation WILL fail if it's bound,
        // because it makes this future !Send, and the tokio::spawn above will fail, but in case
        // we change the looping strategy, I'm calling it out explicitly too.
        batch.lock().unwrap().merge(to_flush);
        tokio::time::sleep(interval.to_std().unwrap()).await;
    }
}

struct FlushBatch {
    // The minimum of the "flush_by" times of all the updates in the batch
    pub next_mandatory_flush: DateTime<Utc>,
    // The list of pending updates. Note that the update batch makes no effort
    // to deduplicate or compact updates.
    pub pending: Vec<PendingUpdate>,
    // A running total of all blob bytes held in the batch
    pub blobs_size: usize,
    // A running total of all vm_state bytes held in the batch
    pub vm_states_size: usize,
    // Conditionally compress vm_state in write path?
    pub should_compress_vm_state: bool,
}

impl FlushBatch {
    pub fn new(should_compress_vm_state: bool) -> Self {
        Self {
            next_mandatory_flush: Utc::now(),
            pending: Default::default(),
            blobs_size: 0,
            vm_states_size: 0,
            should_compress_vm_state,
        }
    }

    pub fn add(&mut self, pending: PendingUpdate, flush_by: DateTime<Utc>) {
        // If this is the start of a new batch, reset the first_insert time
        if self.pending.is_empty() {
            self.next_mandatory_flush = flush_by;
        } else {
            self.next_mandatory_flush = self.next_mandatory_flush.min(flush_by);
        }

        // Update the sizes of the bytes we track
        if let Some(Some(blob)) = pending.update.blob.as_ref() {
            self.blobs_size += blob.len();
        }
        if let Some(Some(vm_state)) = pending.update.vm_state.as_ref() {
            self.vm_states_size += vm_state.len();
        }
        self.pending.push(pending);
    }

    async fn flush(&mut self, pool: &PgPool) -> Result<(), QueueError> {
        let now = Utc::now();
        // First, filter any updates whose deadline is exceeded that we have
        // already tried to flush once, sending a deadline exceeded error to the
        // handle.
        let mut i = 0;
        while i < self.pending.len() {
            if self.pending[i].deadline.is_some_and(|d| d < now) && self.pending[i].tries > 0 {
                self.pending.swap_remove(i).fail_deadline_exceeded();
            } else {
                i += 1;
            }
        }

        let mut txn = pool.begin().await?;
        let mut results = Vec::new();
        for to_flush in self.pending.iter_mut() {
            to_flush.tries += 1;
            let result = flush_job(
                &mut *txn,
                to_flush.job_id,
                &to_flush.update,
                self.should_compress_vm_state,
            )
            .await;
            match result {
                Ok(()) => {
                    results.push(Ok(()));
                }
                Err(QueueError::JobError(e)) => {
                    results.push(Err(e));
                }
                Err(e) => {
                    return Err(e);
                }
            }
        }
        txn.commit().await?;

        // We only dispatch results and clear the pending set if we actually commit the transaction, otherwise
        // the updates in this batch should be retried.
        for (update, result) in self.pending.drain(..).zip(results) {
            update.resolve(result);
        }
        Ok(())
    }

    fn should_flush(&self, max_buffered: usize, max_bytes: usize) -> bool {
        let would_flush = Utc::now() >= self.next_mandatory_flush
            || self.pending.len() >= max_buffered
            || self.blobs_size + self.vm_states_size >= max_bytes;

        would_flush && !self.pending.is_empty() // we only should flush if we have something to flush
    }

    // Take the current batch, replacing it in memory with an empty one. Used along with "merge"
    // to let us flush without holding the batch lock for the duration of the flush
    fn take(&mut self) -> Self {
        std::mem::replace(self, FlushBatch::new(self.should_compress_vm_state))
    }

    // Combine two batches, setting the next mandatory flush to the earliest of the two
    fn merge(&mut self, other: Self) {
        self.pending.extend(other.pending);
        self.blobs_size += other.blobs_size;
        self.vm_states_size += other.vm_states_size;
        self.next_mandatory_flush = self.next_mandatory_flush.min(other.next_mandatory_flush);
    }
}

struct PendingUpdate {
    job_id: Uuid,
    update: JobUpdate,
    deadline: Option<DateTime<Utc>>,
    tries: u8,
    tx: oneshot::Sender<Result<(), JobError>>,
}

impl PendingUpdate {
    pub fn new(
        job_id: Uuid,
        update: JobUpdate,
        deadline: Option<DateTime<Utc>>,
    ) -> (Self, FlushHandle) {
        let (tx, rx) = oneshot::channel();
        let update = Self {
            job_id,
            update,
            deadline,
            tries: 0,
            tx,
        };
        (update, FlushHandle { inner: rx })
    }

    pub fn fail_deadline_exceeded(self) {
        let job_id = self.job_id;
        self.resolve(Err(JobError::DeadlineExceeded(job_id)));
    }

    pub fn resolve(self, result: Result<(), JobError>) {
        // We do not care if someone is waiting for this result or not
        let _unused = self.tx.send(result);
    }
}

pub struct FlushHandle {
    inner: oneshot::Receiver<Result<(), JobError>>,
}

impl FlushHandle {
    pub fn immediate(result: Result<(), JobError>) -> Self {
        let (tx, rx) = oneshot::channel();
        let _unused = tx.send(result);
        Self { inner: rx }
    }
}

// If the inner oneshot resolves to an error, we know that the update was dropped before being flushed,
// so we just return a JobError::UpdateDropped. Otherwise, we return the result of the inner oneshot.
impl Future for FlushHandle {
    type Output = Result<(), JobError>;

    fn poll(
        mut self: std::pin::Pin<&mut Self>,
        cx: &mut std::task::Context<'_>,
    ) -> std::task::Poll<Self::Output> {
        match self.inner.poll_unpin(cx) {
            Poll::Ready(Ok(result)) => Poll::Ready(result),
            Poll::Ready(Err(_)) => Poll::Ready(Err(JobError::UpdateDropped)),
            Poll::Pending => Poll::Pending,
        }
    }
}
