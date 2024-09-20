pub const JOB_INSERT_ATTEMPT: &str = "cyclotron_insert_attemp";
pub const BULK_INSERT_ATTEMPT: &str = "cyclotron_bulk_insert_attempt";
pub const JOBS_INSERTS: &str = "cyclotron_jobs_inserted";
pub const FLUSH_ATTEMPT: &str = "cyclotron_flush_attempt";
pub const JOB_RELEASED: &str = "cyclotron_job_released";
// All updates flushed (i.e. all updates inserted into, and then removed from, a flush batch, regardless of flush outcome. Labels are used to distinguish different types of flush outcome)
pub const FLUSHED_UPDATES: &str = "cyclotron_flushed_updates";
// Labeled to indicate whether the bytes were committed or not, as well as what they are.
pub const UPDATE_FLUSHED_BYTES: &str = "cyclotron_committed_bytes";
pub const FLUSH_BATCH_SIZE: &str = "cyclotron_flush_batch_size";
