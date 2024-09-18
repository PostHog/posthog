use std::sync::Arc;

use chrono::{Duration, Utc};
use common::{assert_job_matches_init, create_new_job, dates_match};
use cyclotron_core::{JobState, QueueManager, Worker};
use sqlx::PgPool;
use uuid::Uuid;

mod common;

// I know this should be a bunch of tests, but for hacking together stuff right now, it'll do
#[sqlx::test(migrations = "./migrations")]
async fn test_queue(db: PgPool) {
    let manager = QueueManager::from_pool(db.clone());
    let mut worker = Worker::from_pool(db, Default::default());
    worker.max_buffered = 0; // No buffering for testing, flush immediately

    let job_1 = create_new_job();
    let mut job_2 = create_new_job();

    job_2.priority = 2; // Lower priority jobs should be returned second

    let queue_name = job_1.queue_name.clone();

    manager
        .create_job(job_1.clone())
        .await
        .expect("failed to create job");
    manager
        .create_job(job_2.clone())
        .await
        .expect("failed to create job");

    let jobs = worker
        .dequeue_jobs(&queue_name, 2)
        .await
        .expect("failed to dequeue job");

    assert_eq!(jobs.len(), 2);
    // This also assert that the ordering is correct in terms of priority
    assert_job_matches_init(&jobs[0], &job_1);
    assert_job_matches_init(&jobs[1], &job_2);

    // Now we can re-queue these jobs (imagine we had done work)
    worker
        .set_state(jobs[0].id, JobState::Available)
        .expect("failed to set state");
    worker
        .set_state(jobs[1].id, JobState::Available)
        .expect("failed to set state");

    // Flush the two jobs, having made no other changes, then assert we can re-dequeue them
    let handle_1 = worker.release_job(jobs[0].id, None);
    let handle_2 = worker.release_job(jobs[1].id, None);

    worker.force_flush().await.unwrap();
    handle_1.await.unwrap();
    handle_2.await.unwrap();

    let jobs = worker
        .dequeue_jobs(&queue_name, 2)
        .await
        .expect("failed to dequeue job");

    assert_eq!(jobs.len(), 2);
    assert_job_matches_init(&jobs[0], &job_1);
    assert_job_matches_init(&jobs[1], &job_2);

    // Re-queue them again
    worker
        .set_state(jobs[0].id, JobState::Available)
        .expect("failed to set state");
    worker
        .set_state(jobs[1].id, JobState::Available)
        .expect("failed to set state");

    let handle_1 = worker.release_job(jobs[0].id, None);
    let handle_2 = worker.release_job(jobs[1].id, None);

    worker.force_flush().await.unwrap();
    handle_1.await.unwrap();
    handle_2.await.unwrap();

    // Spin up two tasks to race on dequeuing, and assert at most 2 jobs are dequeued
    let worker: Arc<Worker> = Arc::new(worker);
    let moved = worker.clone();
    let queue_name_moved = queue_name.clone();
    let fut_1 = async move {
        moved
            .dequeue_jobs(&queue_name_moved, 2)
            .await
            .expect("failed to dequeue job")
    };
    let moved = worker.clone();
    let queue_name_moved = queue_name.clone();
    let fut_2 = async move {
        moved
            .dequeue_jobs(&queue_name_moved, 2)
            .await
            .expect("failed to dequeue job")
    };

    let (jobs_1, jobs_2) = tokio::join!(fut_1, fut_2);
    assert_eq!(jobs_1.len() + jobs_2.len(), 2);

    let jobs = jobs_1
        .into_iter()
        .chain(jobs_2.into_iter())
        .collect::<Vec<_>>();

    // And now, any subsequent dequeues will return no jobs
    let empty = worker
        .dequeue_jobs(&queue_name, 2)
        .await
        .expect("failed to dequeue job");
    assert_eq!(empty.len(), 0);

    // If we try to flush a job without setting what it's next state will be,
    // we should get an error. We don't bother forcing a flush here, because
    // the worker should return a handle that immediately resolves.
    assert!(worker.release_job(jobs[0].id, None).await.is_err());

    // Trying to flush a job with the state "running" should also fail
    worker
        .set_state(jobs[1].id, JobState::Running)
        .expect("failed to set state");
    assert!(worker.release_job(jobs[1].id, None).await.is_err());

    // But if we properly set the state to completed or failed, now we can flush
    worker
        .set_state(jobs[0].id, JobState::Completed)
        .expect("failed to set state");
    worker
        .set_state(jobs[1].id, JobState::Failed)
        .expect("failed to set state");

    let handle_1 = worker.release_job(jobs[0].id, None);
    let handle_2 = worker.release_job(jobs[1].id, None);

    worker.force_flush().await.expect("failed to flush job");
    handle_1.await.unwrap();
    handle_2.await.unwrap();

    // And now, any subsequent dequeues will return no jobs (because these jobs are finished)
    let empty = worker
        .dequeue_jobs(&queue_name, 2)
        .await
        .expect("failed to dequeue job");
    assert_eq!(empty.len(), 0);

    // Now, lets check that we can set every variable on a job

    // Set up some initial values
    let now = Utc::now();
    let mut job = create_new_job();
    job.queue_name = "test".to_string();
    job.priority = 0;
    job.scheduled = now - Duration::minutes(2);
    job.vm_state = None;
    job.parameters = None;
    job.metadata = None;

    // Queue the job
    manager
        .create_job(job.clone())
        .await
        .expect("failed to create job");

    // Then dequeue it
    let job = worker
        .dequeue_jobs("test", 1)
        .await
        .expect("failed to dequeue job")
        .pop()
        .expect("failed to dequeue job");

    // Set everything we're able to set, including state to available, so we can dequeue it again
    worker
        .set_state(job.id, JobState::Available)
        .expect("failed to set state");
    worker
        .set_queue(job.id, "test_2")
        .expect("failed to set queue");
    worker
        .set_priority(job.id, 1)
        .expect("failed to set priority");
    worker
        .set_scheduled_at(job.id, now - Duration::minutes(10))
        .expect("failed to set scheduled_at");
    worker
        .set_vm_state(job.id, Some("test".as_bytes().to_owned()))
        .expect("failed to set vm_state");
    worker
        .set_parameters(job.id, Some("test".as_bytes().to_owned()))
        .expect("failed to set parameters");
    worker
        .set_blob(job.id, Some("test".as_bytes().to_owned()))
        .expect("failed to set blob");
    worker
        .set_metadata(job.id, Some("test".as_bytes().to_owned()))
        .expect("failed to set metadata");

    // Flush the job
    let handle = worker.release_job(job.id, None);

    worker.force_flush().await.unwrap();
    handle.await.unwrap();
    // Then dequeue it again (this time being sure to grab the vm state too)
    let job = worker
        .dequeue_with_vm_state("test_2", 1)
        .await
        .expect("failed to dequeue job")
        .pop()
        .expect("failed to dequeue job");

    // And every value should be the updated one
    assert_eq!(job.queue_name, "test_2");
    assert_eq!(job.priority, 1);
    assert!(dates_match(&job.scheduled, &(now - Duration::minutes(10))),);
    assert_eq!(job.vm_state, Some("test".as_bytes().to_owned()));
    assert_eq!(job.parameters, Some("test".as_bytes().to_owned()));
    assert_eq!(job.metadata, Some("test".as_bytes().to_owned()));
}

#[sqlx::test(migrations = "./migrations")]
pub async fn test_bulk_insert(db: PgPool) {
    let worker = Worker::from_pool(db.clone(), Default::default());
    let manager = QueueManager::from_pool(db.clone());

    let job_template = create_new_job();

    let jobs = (0..1000)
        .map(|_| {
            let mut job = job_template.clone();
            job.function_id = Some(Uuid::now_v7());
            job
        })
        .collect::<Vec<_>>();

    let result = manager.bulk_create_jobs(jobs).await;
    assert!(result.all_succeeded());

    let dequeue_jobs = worker
        .dequeue_jobs(&job_template.queue_name, 1000)
        .await
        .expect("failed to dequeue job");

    assert_eq!(dequeue_jobs.len(), 1000);
}
