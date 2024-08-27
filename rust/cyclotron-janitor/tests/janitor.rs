use chrono::{Duration, Utc};

use cyclotron_core::{JobInit, JobState, QueueManager, Worker};
use cyclotron_janitor::{config::JanitorSettings, janitor::Janitor};
use sqlx::PgPool;
use uuid::Uuid;

#[sqlx::test(migrations = "../cyclotron-core/migrations")]
async fn janitor_test(db: PgPool) {
    let worker = Worker::from_pool(db.clone());
    let manager = QueueManager::from_pool(db.clone());

    // Purposefully MUCH smaller than would be used in production, so
    // we can simulate stalled or poison jobs quickly
    let stall_timeout = Duration::milliseconds(10);
    let max_touches = 3;

    let settings = JanitorSettings {
        stall_timeout,
        max_touches,
        id: "test_janitor".to_string(),
        shard_id: "test_shard".to_string(),
    };
    let janitor = Janitor {
        inner: cyclotron_core::Janitor::from_pool(db.clone()),
        settings,
        metrics_labels: vec![],
    };

    let now = Utc::now() - Duration::seconds(10);
    let queue_name = "default".to_string();

    let job_init = JobInit {
        team_id: 1,
        queue_name: queue_name.clone(),
        priority: 0,
        scheduled: now,
        function_id: Some(Uuid::now_v7()),
        vm_state: None,
        parameters: None,
        blob: None,
        metadata: None,
    };

    // First test - if we mark a job as completed, the janitor will clean it up
    manager.create_job(job_init.clone()).await.unwrap();
    let job = worker
        .dequeue_jobs(&queue_name, 1)
        .await
        .unwrap()
        .pop()
        .unwrap();

    worker.set_state(job.id, JobState::Completed).unwrap();
    worker.flush_job(job.id).await.unwrap();

    let result = janitor.run_once().await.unwrap();
    assert_eq!(result.completed, 1);
    assert_eq!(result.failed, 0);
    assert_eq!(result.poisoned, 0);
    assert_eq!(result.stalled, 0);

    // Second test - if we mark a job as failed, the janitor will clean it up
    manager.create_job(job_init.clone()).await.unwrap();
    let job = worker
        .dequeue_jobs(&queue_name, 1)
        .await
        .unwrap()
        .pop()
        .unwrap();

    worker.set_state(job.id, JobState::Failed).unwrap();
    worker.flush_job(job.id).await.unwrap();

    let result = janitor.run_once().await.unwrap();
    assert_eq!(result.completed, 0);
    assert_eq!(result.failed, 1);
    assert_eq!(result.poisoned, 0);
    assert_eq!(result.stalled, 0);

    // Third test - if we pick up a job, and then hold it for longer than
    // the stall timeout, the janitor will reset it. After this, the worker
    // cannot flush updates to the job, and must re-dequeue it.

    manager.create_job(job_init.clone()).await.unwrap();
    let job = worker
        .dequeue_jobs(&queue_name, 1)
        .await
        .unwrap()
        .pop()
        .unwrap();

    // First, cleanup won't do anything
    let result = janitor.run_once().await.unwrap();
    assert_eq!(result.completed, 0);
    assert_eq!(result.failed, 0);
    assert_eq!(result.poisoned, 0);
    assert_eq!(result.stalled, 0);

    // Then we stall on the job
    tokio::time::sleep(stall_timeout.to_std().unwrap() * 2).await;

    // Now, cleanup will reset the job
    let result = janitor.run_once().await.unwrap();
    assert_eq!(result.completed, 0);
    assert_eq!(result.failed, 0);
    assert_eq!(result.poisoned, 0);
    assert_eq!(result.stalled, 1);

    // Now, the worker can't flush the job
    worker.set_state(job.id, JobState::Completed).unwrap();
    let result = worker.flush_job(job.id).await;
    assert!(result.is_err());

    // But if we re-dequeue the job, we can flush it
    let job = worker
        .dequeue_jobs(&queue_name, 1)
        .await
        .unwrap()
        .pop()
        .unwrap();
    worker.set_state(job.id, JobState::Completed).unwrap();
    worker.flush_job(job.id).await.unwrap();

    janitor.run_once().await.unwrap(); // Clean up the completed job to reset for the next test

    // Fourth test - if a worker holds a job for longer than the stall
    // time, but calls heartbeat, the job will not be reset

    manager.create_job(job_init.clone()).await.unwrap();
    let job = worker
        .dequeue_jobs(&queue_name, 1)
        .await
        .unwrap()
        .pop()
        .unwrap();

    let start = tokio::time::Instant::now();
    loop {
        worker.heartbeat(job.id).await.unwrap();
        tokio::time::sleep(Duration::milliseconds(1).to_std().unwrap()).await;
        if start.elapsed() > stall_timeout.to_std().unwrap() * 2 {
            break;
        }
    }

    let result = janitor.run_once().await.unwrap();
    assert_eq!(result.completed, 0);
    assert_eq!(result.failed, 0);
    assert_eq!(result.poisoned, 0);
    assert_eq!(result.stalled, 0);

    // The worker can still flush the job
    worker.set_state(job.id, JobState::Completed).unwrap();
    worker.flush_job(job.id).await.unwrap();

    // and now cleanup will work
    let result = janitor.run_once().await.unwrap();
    assert_eq!(result.completed, 1);
    assert_eq!(result.failed, 0);
    assert_eq!(result.poisoned, 0);
    assert_eq!(result.stalled, 0);

    // Fifth test - if a job stalls more than max_touches
    // it will be marked as poisoned and deleted

    manager.create_job(job_init.clone()).await.unwrap();
    let mut job = worker
        .dequeue_jobs(&queue_name, 1)
        .await
        .unwrap()
        .pop()
        .unwrap();

    for _ in 0..max_touches {
        tokio::time::sleep(stall_timeout.to_std().unwrap() * 2).await;
        let result = janitor.run_once().await.unwrap();
        assert_eq!(result.completed, 0);
        assert_eq!(result.failed, 0);
        assert_eq!(result.poisoned, 0);
        assert_eq!(result.stalled, 1);

        // assert we can't update the job (flush and heartbeat fail)
        worker.set_state(job.id, JobState::Completed).unwrap();
        let result = worker.heartbeat(job.id).await;
        assert!(result.is_err());
        let result = worker.flush_job(job.id).await;
        assert!(result.is_err());

        // re-dequeue the job
        job = worker
            .dequeue_jobs(&queue_name, 1)
            .await
            .unwrap()
            .pop()
            .unwrap();
    }
    // At this point, the "janitor touches" on the job is 3 (it's been stalled and reset 3 times), so one more cleanup loop will delete it

    // Now stall one more time, and on cleanup, we should see the job was considered poison and deleted
    tokio::time::sleep(stall_timeout.to_std().unwrap() * 2).await;
    let result: cyclotron_janitor::janitor::CleanupResult = janitor.run_once().await.unwrap();
    assert_eq!(result.completed, 0);
    assert_eq!(result.failed, 0);
    assert_eq!(result.poisoned, 1);
    assert_eq!(result.stalled, 0);

    // The worker can't flush the job
    worker.set_state(job.id, JobState::Completed).unwrap();
    let result = worker.flush_job(job.id).await;
    assert!(result.is_err());

    // Sixth test - the janitor can operate on multiple jobs at once
    manager.create_job(job_init.clone()).await.unwrap();
    manager.create_job(job_init.clone()).await.unwrap();
    let jobs = worker.dequeue_jobs(&queue_name, 2).await.unwrap();

    worker.set_state(jobs[0].id, JobState::Completed).unwrap();
    worker.set_state(jobs[1].id, JobState::Failed).unwrap();

    worker.flush_job(jobs[0].id).await.unwrap();
    worker.flush_job(jobs[1].id).await.unwrap();

    let result = janitor.run_once().await.unwrap();
    assert_eq!(result.completed, 1);
    assert_eq!(result.failed, 1);
    assert_eq!(result.poisoned, 0);
    assert_eq!(result.stalled, 0);
}
