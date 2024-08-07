use std::{
    sync::{atomic::AtomicUsize, Arc},
    time::Instant,
};

use chrono::{Duration, Utc};
use cyclotron_core::{
    base_ops::{JobInit, JobState, WaitingOn},
    manager::{ManagerConfig, QueueManager},
    worker::Worker,
    PoolConfig,
};
use futures::future::join_all;
use uuid::Uuid;

// This spins up a manager and 2 workers, and tries to simulate semi-realistic load (on the DB - the workers do nothing except complete jobs)
// - The manager inserts jobs as fast as it can, choosing randomly between hog and fetch workers, and between different priorities.
// - The workers will process jobs as fast as they can, in batches of 1000.
// - The manager and both workers track how long each insert and dequeue takes, in ms/job.
// - The manager never inserts more than 10,000 more jobs than the workers have processed.

struct SharedContext {
    jobs_inserted: AtomicUsize,
    jobs_dequeued: AtomicUsize,
}

async fn producer_loop(manager: QueueManager, shared_context: Arc<SharedContext>) {
    let mut time_spent_inserting = Duration::zero();
    let now = Utc::now() - Duration::minutes(1);
    loop {
        let waiting_on = if rand::random() {
            WaitingOn::Fetch
        } else {
            WaitingOn::Hog
        };

        let priority = (rand::random::<u16>() % 3) as i16;

        let test_job = JobInit {
            team_id: 1,
            waiting_on,
            queue_name: "default".to_string(),
            priority,
            scheduled: now,
            function_id: Some(Uuid::now_v7()),
            vm_state: None,
            parameters: None,
            metadata: None,
        };

        let start = Instant::now();
        manager.create_job(test_job).await.unwrap();
        let elapsed = start.elapsed();
        time_spent_inserting += Duration::from_std(elapsed).unwrap();

        let inserted = shared_context
            .jobs_inserted
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);

        if inserted % 100 == 0 {
            println!("Inserted: {} in {}, ", inserted, time_spent_inserting);
            let mut dequeued = shared_context
                .jobs_dequeued
                .load(std::sync::atomic::Ordering::Relaxed);
            while inserted > dequeued + 10_000 {
                println!(
                    "Waiting for workers to catch up, lagging by {}",
                    inserted - dequeued
                );
                tokio::time::sleep(Duration::milliseconds(100).to_std().unwrap()).await;
                dequeued = shared_context
                    .jobs_dequeued
                    .load(std::sync::atomic::Ordering::Relaxed);
            }
        }
    }
}

async fn worker_loop(worker: Worker, shared_context: Arc<SharedContext>, worker_type: WaitingOn) {
    let mut time_spent_dequeuing = Duration::zero();
    loop {
        let start = Instant::now();
        let jobs = worker
            .dequeue_jobs("default", worker_type, 1000)
            .await
            .unwrap();

        if jobs.is_empty() {
            println!(
                "Worker {:?} outpacing inserts, got no jobs, sleeping!",
                worker_type
            );
            tokio::time::sleep(Duration::milliseconds(100).to_std().unwrap()).await;
            continue;
        }

        let mut futs = Vec::with_capacity(jobs.len());
        for job in &jobs {
            worker.set_state(job.id, JobState::Completed).unwrap();
            futs.push(worker.flush_job(job.id));
        }

        for res in join_all(futs).await {
            res.unwrap();
        }

        time_spent_dequeuing += Duration::from_std(start.elapsed()).unwrap();

        let dequeued = shared_context
            .jobs_dequeued
            .fetch_add(jobs.len(), std::sync::atomic::Ordering::Relaxed);

        // To account for the bunch we just handled
        let dequeued = dequeued + jobs.len();

        println!(
            "Dequeued, processed and completed {} jobs in {} for {:?}",
            dequeued, time_spent_dequeuing, worker_type
        );

        if jobs.len() < 1000 {
            println!(
                "Worker {:?} outpacing manager, only got {} jobs, sleeping!",
                worker_type,
                jobs.len()
            );
            tokio::time::sleep(Duration::milliseconds(100).to_std().unwrap()).await;
        }
    }
}

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

    let shared_context = Arc::new(SharedContext {
        jobs_inserted: AtomicUsize::new(0),
        jobs_dequeued: AtomicUsize::new(0),
    });

    let manager = QueueManager::new(manager_config).await.unwrap();
    let worker_1 = Worker::new(pool_config.clone()).await.unwrap();
    let worker_2 = Worker::new(pool_config.clone()).await.unwrap();

    let producer = producer_loop(manager, shared_context.clone());
    let worker_1 = worker_loop(worker_1, shared_context.clone(), WaitingOn::Fetch);
    let worker_2 = worker_loop(worker_2, shared_context.clone(), WaitingOn::Hog);

    let producer = tokio::spawn(producer);
    let worker_1 = tokio::spawn(worker_1);
    let worker_2 = tokio::spawn(worker_2);

    tokio::try_join!(producer, worker_1, worker_2).unwrap();
}
