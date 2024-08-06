use chrono::{Duration, Utc};
use cyclotron_core::{
    base_ops::{JobInit, JobState, WaitingOn},
    manager::{ManagerConfig, QueueManager},
    worker::Worker,
    PoolConfig,
};
use uuid::Uuid;

// See the comment at the top of deqeueu_ordering.js in the node libraries examples folder for
// a description of what this is for. This function happily runs forever, but the exact equivalent
// in javascript fails almost immediately, and I do not know why.
#[tokio::main]
async fn main() {
    let pool_config = PoolConfig {
        host: "localhost".to_string(),
        port: 5432,
        user: "posthog".to_string(),
        password: "posthog".to_string(),
        db: "posthog".to_string(),
        max_connections: None,
        min_connections: None,
        acquire_timeout_seconds: None,
        max_lifetime_seconds: None,
        idle_timeout_seconds: None,
    };

    let manager_config = ManagerConfig {
        shards: vec![pool_config.clone()],
    };

    let manager = QueueManager::new(manager_config).await.unwrap();
    let worker = Worker::new(pool_config).await.unwrap();

    let now = Utc::now() - Duration::minutes(1);
    let start = Utc::now();
    let mut count = 0;
    loop {
        let test_job = JobInit {
            team_id: 1,
            waiting_on: WaitingOn::Fetch,
            queue_name: "default".to_string(),
            priority: 0,
            scheduled: now,
            function_id: Some(Uuid::now_v7()),
            vm_state: None,
            parameters: None,
            metadata: None,
        };

        let mut test_job_2 = test_job.clone();
        test_job_2.priority = 1;
        let test_job_2 = test_job_2;

        manager.create_job(test_job).await.unwrap();
        manager.create_job(test_job_2).await.unwrap();

        let jobs = worker
            .dequeue_jobs("default", WaitingOn::Fetch, 2)
            .await
            .unwrap();

        assert!(jobs.len() == 2);
        assert!(jobs[0].priority == 0);
        assert!(jobs[1].priority == 1);

        let job_1_id = jobs[0].id;
        let job_2_id = jobs[1].id;

        worker.set_state(jobs[0].id, JobState::Available).unwrap();
        worker.set_state(jobs[1].id, JobState::Available).unwrap();

        // Set job 1 to have the same priority as job 2 originally had
        worker.set_priority(jobs[0].id, 2).unwrap();
        // And set job 2 to have a priority higher than job 1
        worker.set_priority(jobs[1].id, 1).unwrap();

        worker.flush_job(jobs[0].id).await.unwrap();
        worker.flush_job(jobs[1].id).await.unwrap();

        let jobs = worker
            .dequeue_with_vm_state("default", WaitingOn::Fetch, 2)
            .await
            .unwrap();

        assert!(jobs.len() == 2);
        // Assert our priority re-ordering was respected
        assert!(jobs[0].id == job_2_id);
        assert!(jobs[1].id == job_1_id);

        // mark these as completed
        worker.set_state(jobs[0].id, JobState::Completed).unwrap();
        worker.set_state(jobs[1].id, JobState::Completed).unwrap();

        worker.flush_job(jobs[0].id).await.unwrap();
        worker.flush_job(jobs[1].id).await.unwrap();

        count += 1;
        println!("Elapsed: {:?}, count: {}", Utc::now() - start, count);
    }
}
