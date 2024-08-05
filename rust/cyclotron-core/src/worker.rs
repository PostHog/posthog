use std::{collections::HashMap, sync::Arc};

use chrono::{DateTime, Utc};
use sqlx::PgPool;
use tokio::sync::Mutex;
use uuid::Uuid;

use crate::{
    base_ops::{
        dequeue_jobs, dequeue_with_vm_state, flush_job, Job, JobState, JobUpdate, WaitingOn,
    },
    error::QueueError,
    PoolConfig,
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
    // rather than having to track the update state on their side and submit it all at once
    // TODO - we don't handle people "forgetting" to abort a job, because we expect that to
    //       only happen if a process dies (in which case the job queue janitor should handle
    //       it)... this is a memory leak, but I think it's ok.
    pending: Arc<Mutex<HashMap<Uuid, JobUpdate>>>,
}

impl Worker {
    pub async fn new(config: PoolConfig) -> Result<Self, QueueError> {
        let pool = config.connect().await?;
        Ok(Self {
            pool,
            pending: Arc::new(Mutex::new(HashMap::new())),
        })
    }

    pub fn from_pool(pool: PgPool) -> Self {
        Self {
            pool,
            pending: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    pub async fn dequeue_jobs(
        &self,
        queue: &str,
        worker_type: WaitingOn,
        limit: usize,
    ) -> Result<Vec<Job>, QueueError> {
        let jobs = dequeue_jobs(&self.pool, queue, worker_type, limit).await?;

        let mut pending = self.pending.lock().await;
        for job in &jobs {
            // This lets us know that if we receive an update piece for a job, and that
            // job isn't in our pending queue, that's due to some programming error, and
            // we can return an error to the user
            pending.insert(job.id, Default::default());
        }

        Ok(jobs)
    }

    pub async fn dequeue_with_vm_state(
        &self,
        queue: &str,
        worker_type: WaitingOn,
        limit: usize,
    ) -> Result<Vec<Job>, QueueError> {
        let jobs = dequeue_with_vm_state(&self.pool, queue, worker_type, limit).await?;

        let mut pending = self.pending.lock().await;
        for job in &jobs {
            pending.insert(job.id, Default::default());
        }

        Ok(jobs)
    }

    pub async fn flush_job(&self, job_id: Uuid) -> Result<(), QueueError> {
        let mut pending = self.pending.lock().await;
        let update = pending
            .remove(&job_id)
            .ok_or(QueueError::UnknownJobId(job_id))?;
        let mut connection = self.pool.acquire().await?;
        // It's a programming error to flush a job without setting a new state
        match update.state {
            Some(JobState::Running) | None => {
                pending.insert(job_id, update); // Keep track of any /other/ updates that might have been stored, even in this case
                return Err(QueueError::FlushWithoutNextState(job_id));
            }
            _ => {}
        }
        Ok(flush_job(connection.as_mut(), job_id, update).await?)
    }

    pub async fn set_state(&self, job_id: Uuid, state: JobState) -> Result<(), QueueError> {
        let mut pending = self.pending.lock().await;
        pending
            .get_mut(&job_id)
            .ok_or(QueueError::UnknownJobId(job_id))?
            .state = Some(state);
        Ok(())
    }

    pub async fn set_waiting_on(
        &self,
        job_id: Uuid,
        waiting_on: WaitingOn,
    ) -> Result<(), QueueError> {
        let mut pending = self.pending.lock().await;
        pending
            .get_mut(&job_id)
            .ok_or(QueueError::UnknownJobId(job_id))?
            .waiting_on = Some(waiting_on);
        Ok(())
    }

    pub async fn set_queue(&self, job_id: Uuid, queue: &str) -> Result<(), QueueError> {
        let mut pending = self.pending.lock().await;
        pending
            .get_mut(&job_id)
            .ok_or(QueueError::UnknownJobId(job_id))?
            .queue_name = Some(queue.to_string());
        Ok(())
    }

    pub async fn set_priority(&self, job_id: Uuid, priority: i16) -> Result<(), QueueError> {
        let mut pending = self.pending.lock().await;
        pending
            .get_mut(&job_id)
            .ok_or(QueueError::UnknownJobId(job_id))?
            .priority = Some(priority);
        Ok(())
    }

    pub async fn set_scheduled_at(
        &self,
        job_id: Uuid,
        scheduled: DateTime<Utc>,
    ) -> Result<(), QueueError> {
        let mut pending = self.pending.lock().await;
        pending
            .get_mut(&job_id)
            .ok_or(QueueError::UnknownJobId(job_id))?
            .scheduled = Some(scheduled);
        Ok(())
    }

    pub async fn set_vm_state(
        &self,
        job_id: Uuid,
        vm_state: Option<String>, // This (and the following) are Options, because the user can null them (by calling with None)
    ) -> Result<(), QueueError> {
        let mut pending = self.pending.lock().await;
        pending
            .get_mut(&job_id)
            .ok_or(QueueError::UnknownJobId(job_id))?
            .vm_state = Some(vm_state);
        Ok(())
    }

    pub async fn set_metadata(
        &self,
        job_id: Uuid,
        metadata: Option<String>,
    ) -> Result<(), QueueError> {
        let mut pending = self.pending.lock().await;
        pending
            .get_mut(&job_id)
            .ok_or(QueueError::UnknownJobId(job_id))?
            .metadata = Some(metadata);
        Ok(())
    }

    pub async fn set_parameters(
        &self,
        job_id: Uuid,
        parameters: Option<String>,
    ) -> Result<(), QueueError> {
        let mut pending = self.pending.lock().await;
        pending
            .get_mut(&job_id)
            .ok_or(QueueError::UnknownJobId(job_id))?
            .parameters = Some(parameters);
        Ok(())
    }
}
