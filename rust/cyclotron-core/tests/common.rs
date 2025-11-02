use chrono::{DateTime, Duration, Utc};
use cyclotron_core::{Job, JobInit};
use uuid::Uuid;

#[allow(dead_code)]
pub fn create_new_job() -> JobInit {
    JobInit {
        id: None,
        team_id: 1,
        function_id: Some(Uuid::now_v7()), // Lets us uniquely identify jobs without having the Uuid
        queue_name: "test".to_string(),
        priority: 0,
        scheduled: Utc::now() - Duration::minutes(1),
        vm_state: None,

        parameters: None,
        blob: None,
        metadata: None,
    }
}

#[allow(dead_code)]
pub fn dates_match(left: &DateTime<Utc>, right: &DateTime<Utc>) -> bool {
    // Roundtripping a datetime to PG can cause sub-ms differences, so we need to check within a margin of error
    // Seeing errors like this in CI:
    //      assertion `left == right` failed
    //          left: 2024-08-08T20:41:55.964936Z
    //         right: 2024-08-08T20:41:55.964936997Z
    let diff = *left - *right;
    diff.abs() < Duration::milliseconds(1)
}

#[allow(dead_code)]
pub fn assert_job_matches_init(job: &Job, init: &JobInit) {
    assert_eq!(job.team_id, init.team_id);
    assert_eq!(job.function_id, init.function_id);
    assert_eq!(job.queue_name, init.queue_name);
    assert_eq!(job.priority, init.priority);
    assert!(dates_match(&job.scheduled, &init.scheduled));
    assert_eq!(job.vm_state, init.vm_state);
    assert_eq!(job.parameters, init.parameters);
    assert_eq!(job.metadata, init.metadata);
}
