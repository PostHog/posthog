use std::collections::HashMap;

use chrono::{DateTime, Utc};
use sqlx::PgPool;
use std::sync::Mutex;
use uuid::Uuid;

use crate::{
    ops::worker::{dequeue_jobs, dequeue_with_vm_state, flush_job, get_vm_state, set_heartbeat},
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
    // All dequeued job IDs that haven't been flushed yet. The idea is this lets us
    // manage, on the rust side of any API boundary, the "pending" update of any given
    // job, such that a user can progressively build up a full update, and then flush it,
    // rather than having to track the update state on their side and submit it all at once.
    // This also lets us "hide" all the locking logic, which we're not totally settled on yet.

    // TRICKY - this is a sync mutex, because that simplifies using the manager in an FFI
    // context (since most functions below can be sync). We have to be careful never to
    // hold a lock across an await point, though.
    pending: Mutex<HashMap<Uuid, JobUpdate>>,
}

impl Worker {
    pub async fn new(config: PoolConfig) -> Result<Self, QueueError> {
        let pool = config.connect().await?;
        Ok(Self {
            pool,
            pending: Default::default(),
        })
    }

    pub fn from_pool(pool: PgPool) -> Self {
        Self {
            pool,
            pending: Default::default(),
        }
    }

    /// Dequeues jobs from the queue, and returns them. Job sorting happens at the queue level,
    /// workers can't provide any filtering or sorting criteria - queue managers decide which jobs are run,
    /// workers just run them.
    pub async fn dequeue_jobs(&self, queue: &str, limit: usize) -> Result<Vec<Job>, QueueError> {
        let jobs = dequeue_jobs(&self.pool, queue, limit).await?;

        let mut pending = self.pending.lock().unwrap();
        for job in &jobs {
            // We need to hang onto the locks for a job until we flush it, so we can send updates.
            let update = JobUpdate::new(
                job.lock_id
                    .expect("Yell at oliver that the dequeuing code is broken. He's very sorry that your process just panicked"),
            );
            pending.insert(job.id, update);
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

        let mut pending = self.pending.lock().unwrap();
        for job in &jobs {
            // We need to hang onto the locks for a job until we flush it, so we can send updates.
            let update = JobUpdate::new(
                job.lock_id
                    .expect("Yell at oliver that the dequeuing (with vm) code is broken. He's very sorry that your process just panicked"),
            );
            pending.insert(job.id, update);
        }

        Ok(jobs)
    }

    /// Retrieve the VM state for a job, if, for example, you dequeued it and then realised you
    /// need the VM state as well.
    pub async fn get_vm_state(&self, job_id: Uuid) -> Result<Option<String>, QueueError> {
        let lock_id = {
            let pending = self.pending.lock().unwrap();
            pending
                .get(&job_id)
                .ok_or(QueueError::UnknownJobId(job_id))?
                .lock_id
        };

        get_vm_state(&self.pool, job_id, lock_id).await
    }

    /// NOTE - This function can only be called once, even though the underlying
    /// basic operation can be performed as many times as the caller likes (so long as
    /// the job state is never set to something other than running, as that clears the
    /// job lock). We're more strict here (flushes can only happen once, you must
    /// flush some non-running state) to try and enforce a good interaction
    /// pattern with the queue. I might return to this and loosen this constraint in the
    /// future, if there's a motivating case for needing to flush partial job updates.
    pub async fn flush_job(&self, job_id: Uuid) -> Result<(), QueueError> {
        // TODO - this drops the job from the known jobs before the flush succeeds,
        // which means that if the flush fails, we'll lose the job and can never
        // update it's state (leaving it to the reaper). This is a bug, but I'm not
        // sure I want to make flushes retryable just yet, so I'm leaving it for now.
        // NIT: this wrapping is to ensure pending is dropped prior to the await
        let update = {
            let mut pending = self.pending.lock().unwrap();
            let update = pending
                .remove(&job_id)
                .ok_or(QueueError::UnknownJobId(job_id))?;
            // It's a programming error to flush a job without setting a new state
            match update.state {
                Some(JobState::Running) | None => {
                    // Keep track of any /other/ updates that might have been stored, even in this case,
                    // so a user can queue up the appropriate state transition and flush properly
                    pending.insert(job_id, update);
                    return Err(QueueError::FlushWithoutNextState(job_id));
                }
                _ => update,
            }
        };
        let mut connection = self.pool.acquire().await?;
        flush_job(connection.as_mut(), job_id, update).await
    }

    /// Jobs are reaped after some seconds (the number is deployment specific, and may become
    /// specific on job properties like queue name in the future, as we figure out what /kinds/ of
    /// jobs are longer or shorter running). A job is considered "dead" if it's in a running state,
    /// and it's last heartbeat was more than the reaping time ago. This, like flush, returns an
    /// error if you try to set the heartbeat on a job whose lock you don't have (which can happen
    /// if e.g. the job was reaped out from under you).
    pub async fn heartbeat(&self, job_id: Uuid) -> Result<(), QueueError> {
        let lock_id = {
            let pending = self.pending.lock().unwrap();
            pending
                .get(&job_id)
                .ok_or(QueueError::UnknownJobId(job_id))?
                .lock_id
        };
        let mut connection = self.pool.acquire().await?;
        set_heartbeat(connection.as_mut(), job_id, lock_id).await
    }

    /// This is how you "return" a job to the queue, by setting the state to "available"
    pub fn set_state(&self, job_id: Uuid, state: JobState) -> Result<(), QueueError> {
        let mut pending = self.pending.lock().unwrap();
        pending
            .get_mut(&job_id)
            .ok_or(QueueError::UnknownJobId(job_id))?
            .state = Some(state);
        Ok(())
    }

    pub fn set_queue(&self, job_id: Uuid, queue: &str) -> Result<(), QueueError> {
        let mut pending = self.pending.lock().unwrap();
        pending
            .get_mut(&job_id)
            .ok_or(QueueError::UnknownJobId(job_id))?
            .queue_name = Some(queue.to_string());
        Ok(())
    }

    /// Jobs are dequeued lowest-priority-first, so this is how you change the "base" priority of a job
    /// (control tables may apply further deltas if e.g. a given function is in a degraded state)
    pub fn set_priority(&self, job_id: Uuid, priority: i16) -> Result<(), QueueError> {
        let mut pending = self.pending.lock().unwrap();
        pending
            .get_mut(&job_id)
            .ok_or(QueueError::UnknownJobId(job_id))?
            .priority = Some(priority);
        Ok(())
    }

    /// This is how you do e.g. retries after some time, by setting the scheduled time
    /// to some time in the future. Sleeping, retry backoff, scheduling - it's all the same operation,
    /// this one.
    pub fn set_scheduled_at(
        &self,
        job_id: Uuid,
        scheduled: DateTime<Utc>,
    ) -> Result<(), QueueError> {
        let mut pending = self.pending.lock().unwrap();
        pending
            .get_mut(&job_id)
            .ok_or(QueueError::UnknownJobId(job_id))?
            .scheduled = Some(scheduled);
        Ok(())
    }

    /// Passing None here will clear the vm_state
    pub fn set_vm_state(
        &self,
        job_id: Uuid,
        vm_state: Option<String>, // This (and the following) are Options, because the user can null them (by calling with None)
    ) -> Result<(), QueueError> {
        let mut pending = self.pending.lock().unwrap();
        pending
            .get_mut(&job_id)
            .ok_or(QueueError::UnknownJobId(job_id))?
            .vm_state = Some(vm_state);
        Ok(())
    }

    /// Passing None here will clear the metadata
    pub fn set_metadata(&self, job_id: Uuid, metadata: Option<String>) -> Result<(), QueueError> {
        let mut pending = self.pending.lock().unwrap();
        pending
            .get_mut(&job_id)
            .ok_or(QueueError::UnknownJobId(job_id))?
            .metadata = Some(metadata);
        Ok(())
    }

    /// Passing None here will clear the parameters
    pub fn set_parameters(
        &self,
        job_id: Uuid,
        parameters: Option<String>,
    ) -> Result<(), QueueError> {
        let mut pending = self.pending.lock().unwrap();
        pending
            .get_mut(&job_id)
            .ok_or(QueueError::UnknownJobId(job_id))?
            .parameters = Some(parameters);
        Ok(())
    }
}
