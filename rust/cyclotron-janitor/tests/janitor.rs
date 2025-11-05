use chrono::{Duration, Timelike, Utc};
use common_kafka::kafka_messages::app_metrics2::{
    AppMetric2, Kind as AppMetric2Kind, Source as AppMetric2Source,
};
use cyclotron_core::{JobInit, JobState, QueueManager, Worker, WorkerConfig};
use cyclotron_janitor::{config::JanitorSettings, janitor::Janitor};
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::{ClientConfig, Message};
use sqlx::PgPool;
use uuid::Uuid;

use common_kafka::{test::create_mock_kafka, APP_METRICS2_TOPIC};

#[sqlx::test(migrations = "../cyclotron-core/migrations")]
async fn janitor_test(db: PgPool) {
    // kinda gross, but the from_pool methods are better suited to test usage
    let default_worker_cfg = WorkerConfig::default();
    let should_compress_vm_state = default_worker_cfg.should_compress_vm_state();

    let worker = Worker::from_pool(db.clone(), default_worker_cfg);
    let manager = QueueManager::from_pool(db.clone(), should_compress_vm_state, false);

    // Purposefully MUCH smaller than would be used in production, so
    // we can simulate stalled or poison jobs quickly
    let stall_timeout = Duration::milliseconds(20);
    let max_touches = 3;

    // Workers by default drop any heartbeats for the first 5 seconds, or between
    // the last heartbeat and the next 5 seconds. We need to override that window
    // to be smaller here, to test heartbeat behaviour
    let mut worker = worker;
    worker.heartbeat_window = stall_timeout / 2;
    worker.max_buffered = 0; // No buffering for testing, flush immediately
    let worker = worker;

    let (mock_cluster, mock_producer) = create_mock_kafka().await;
    mock_cluster
        .create_topic(APP_METRICS2_TOPIC, 1, 1)
        .expect("failed to create mock app_metrics2 topic");

    let kafka_consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", mock_cluster.bootstrap_servers())
        .set("group.id", "mock")
        .set("auto.offset.reset", "earliest")
        .create()
        .expect("failed to create mock consumer");
    kafka_consumer.subscribe(&[APP_METRICS2_TOPIC]).unwrap();

    let settings = JanitorSettings {
        stall_timeout,
        max_touches,
        id: "test_janitor".to_string(),
        shard_id: "test_shard".to_string(),
    };
    let janitor = Janitor {
        inner: cyclotron_core::Janitor::from_pool(db.clone()),
        kafka_producer: mock_producer,
        settings,
        metrics_labels: vec![],
    };

    let now = Utc::now() - Duration::seconds(10);
    let queue_name = "default".to_string();

    let uuid = Uuid::now_v7();
    let job_init = JobInit {
        id: None,
        team_id: 1,
        queue_name: queue_name.clone(),
        priority: 0,
        scheduled: now,
        function_id: Some(uuid),
        vm_state: None,
        parameters: None,
        blob: None,
        metadata: None,
    };

    // First test - if we mark a job as completed, the janitor will clean it up
    let mut job_now = Utc::now();
    manager.create_job(job_init.clone()).await.unwrap();
    let job = worker
        .dequeue_jobs(&queue_name, 1)
        .await
        .unwrap()
        .pop()
        .unwrap();

    worker.set_state(job.id, JobState::Completed).unwrap();
    worker.release_job(job.id, None).await.unwrap();

    let result = janitor.run_once().await.unwrap();
    assert_eq!(result.completed, 1);
    assert_eq!(result.failed, 0);
    assert_eq!(result.poisoned, 0);
    assert_eq!(result.stalled, 0);

    {
        let kafka_msg = kafka_consumer.recv().await.unwrap();
        let payload_str = String::from_utf8(kafka_msg.payload().unwrap().to_vec()).unwrap();
        let app_metric: AppMetric2 = serde_json::from_str(&payload_str).unwrap();

        assert_eq!(
            app_metric,
            AppMetric2 {
                team_id: 1,
                timestamp: job_now
                    .with_minute(0)
                    .unwrap()
                    .with_second(0)
                    .unwrap()
                    .with_nanosecond(0)
                    .unwrap(),
                app_source: AppMetric2Source::Cyclotron,
                app_source_id: uuid.to_string(),
                instance_id: None,
                metric_kind: AppMetric2Kind::Success,
                metric_name: "finished_state".to_owned(),
                count: 1
            }
        );
    }

    // Second test - if we mark a job as failed, the janitor will clean it up
    job_now = Utc::now();
    manager.create_job(job_init.clone()).await.unwrap();
    let job = worker
        .dequeue_jobs(&queue_name, 1)
        .await
        .unwrap()
        .pop()
        .unwrap();

    worker.set_state(job.id, JobState::Failed).unwrap();
    worker.release_job(job.id, None).await.unwrap();

    let result = janitor.run_once().await.unwrap();
    assert_eq!(result.completed, 0);
    assert_eq!(result.failed, 1);
    assert_eq!(result.poisoned, 0);
    assert_eq!(result.stalled, 0);

    {
        let kafka_msg = kafka_consumer.recv().await.unwrap();
        let payload_str = String::from_utf8(kafka_msg.payload().unwrap().to_vec()).unwrap();
        let app_metric: AppMetric2 = serde_json::from_str(&payload_str).unwrap();

        assert_eq!(
            app_metric,
            AppMetric2 {
                team_id: 1,
                timestamp: job_now
                    .with_minute(0)
                    .unwrap()
                    .with_second(0)
                    .unwrap()
                    .with_nanosecond(0)
                    .unwrap(),
                app_source: AppMetric2Source::Cyclotron,
                app_source_id: uuid.to_string(),
                instance_id: None,
                metric_kind: AppMetric2Kind::Failure,
                metric_name: "finished_state".to_owned(),
                count: 1
            }
        );
    }

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
    let result = worker.release_job(job.id, None).await;
    assert!(result.is_err());

    // But if we re-dequeue the job, we can flush it
    let job = worker
        .dequeue_jobs(&queue_name, 1)
        .await
        .unwrap()
        .pop()
        .unwrap();
    worker.set_state(job.id, JobState::Completed).unwrap();
    worker.release_job(job.id, None).await.unwrap();

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
    worker.release_job(job.id, None).await.unwrap();

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
        let result = worker.release_job(job.id, None).await;
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
    let result = worker.release_job(job.id, None).await;
    assert!(result.is_err());

    // Sixth test - the janitor can operate on multiple jobs at once
    manager.create_job(job_init.clone()).await.unwrap();
    manager.create_job(job_init.clone()).await.unwrap();

    let jobs = worker.dequeue_jobs(&queue_name, 2).await.unwrap();

    worker.set_state(jobs[0].id, JobState::Completed).unwrap();
    worker.set_state(jobs[1].id, JobState::Failed).unwrap();

    worker.release_job(jobs[0].id, None).await.unwrap();
    worker.release_job(jobs[1].id, None).await.unwrap();

    let result = janitor.run_once().await.unwrap();
    assert_eq!(result.completed, 1);
    assert_eq!(result.failed, 1);
    assert_eq!(result.poisoned, 0);
    assert_eq!(result.stalled, 0);
}
