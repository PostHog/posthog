use std::str::FromStr;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::postgres::{PgHasArrayType, PgTypeInfo};
use uuid::Uuid;

use crate::QueueError;

#[derive(Debug, Deserialize, Serialize, sqlx::Type)]
#[serde(rename_all = "lowercase")]
#[sqlx(type_name = "JobState", rename_all = "lowercase")]
pub enum JobState {
    Available,
    Running,
    Completed,
    Failed,
    Paused,
}

impl FromStr for JobState {
    type Err = ();

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "available" => Ok(JobState::Available),
            "running" => Ok(JobState::Running),
            "completed" => Ok(JobState::Completed),
            "failed" => Ok(JobState::Failed),
            _ => Err(()),
        }
    }
}

impl PgHasArrayType for JobState {
    fn array_type_info() -> sqlx::postgres::PgTypeInfo {
        // Postgres default naming convention for array types is "_typename"
        PgTypeInfo::with_name("_JobState")
    }
}

// The chunk of data needed to enqueue a job
#[derive(Debug, Deserialize, Serialize, Clone, Eq, PartialEq)]
pub struct JobInit {
    pub team_id: i32,
    pub queue_name: String,
    pub priority: i16,
    pub scheduled: DateTime<Utc>,
    pub function_id: Option<Uuid>,
    pub vm_state: Option<String>,
    pub parameters: Option<String>,
    pub metadata: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct Job {
    // Job metadata
    pub id: Uuid,
    pub team_id: i32,
    pub function_id: Option<Uuid>, // Some jobs might not come from hog, and it doesn't /kill/ use to support that
    pub created: DateTime<Utc>,

    // Queue bookkeeping
    // This will be set for any worker that ever has a job in the "running" state (so any worker that dequeues a job)
    // but I don't want to do the work to encode that in the type system right now - later it should be
    pub lock_id: Option<Uuid>,
    pub last_heartbeat: Option<DateTime<Utc>>,
    pub janitor_touch_count: i16,
    pub transition_count: i16,
    pub last_transition: DateTime<Utc>,

    // Virtual queue components
    pub queue_name: String, // We can have multiple "virtual queues" workers pull from

    // Job availability
    pub state: JobState,
    pub priority: i16, // For sorting "available" jobs. Lower is higher priority
    pub scheduled: DateTime<Utc>,

    // Job data
    pub vm_state: Option<String>, // The state of the VM this job is running on (if it exists)
    pub metadata: Option<String>, // Additional fields a worker can tack onto a job, for e.g. tracking some state across retries (or number of retries in general by a given class of worker)
    pub parameters: Option<String>, // The actual parameters of the job (function args for a hog function, http request for a fetch function)
}

// A struct representing a set of updates for a job. Outer none values mean "don't update this field",
// with nested none values meaning "set this field to null" for nullable fields
#[derive(Debug, Deserialize, Serialize)]
pub struct JobUpdate {
    pub lock_id: Uuid, // The ID of the lock acquired when this worker dequeued the job, required for any update to be valid
    pub state: Option<JobState>,
    pub queue_name: Option<String>,
    pub priority: Option<i16>,
    pub scheduled: Option<DateTime<Utc>>,
    pub vm_state: Option<Option<String>>,
    pub metadata: Option<Option<String>>,
    pub parameters: Option<Option<String>>,
}

impl JobUpdate {
    pub fn new(lock_id: Uuid) -> Self {
        Self {
            lock_id,
            state: None,
            queue_name: None,
            priority: None,
            scheduled: None,
            vm_state: None,
            metadata: None,
            parameters: None,
        }
    }
}

// Bulk inserts across multiple shards can partially succeed, so we need to track failures
// and hand back failed job inits to the caller.
pub struct BulkInsertResult {
    pub failures: Vec<(QueueError, Vec<JobInit>)>,
}

impl BulkInsertResult {
    pub fn new() -> Self {
        Self { failures: vec![] }
    }

    pub fn add_failure(&mut self, err: QueueError, jobs: Vec<JobInit>) {
        self.failures.push((err, jobs));
    }

    pub fn all_succeeded(&self) -> bool {
        self.failures.is_empty()
    }
}

impl Default for BulkInsertResult {
    fn default() -> Self {
        Self::new()
    }
}
