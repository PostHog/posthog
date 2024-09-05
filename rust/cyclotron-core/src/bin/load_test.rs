use std::{
    sync::{atomic::AtomicUsize, Arc},
    time::Instant,
};

use chrono::{Duration, Utc};
use cyclotron_core::{JobInit, JobState, ManagerConfig, PoolConfig, QueueManager, Worker};
use futures::future::join_all;
use uuid::Uuid;

// This spins up a manager and 2 workers, and tries to simulate semi-realistic load (on the DB - the workers do nothing except complete jobs)
// - The manager inserts jobs as fast as it can, choosing randomly between hog and fetch workers, and between different priorities.
// - The workers will process jobs as fast as they can, in batches of 1000.
// - The manager and both workers track how long each insert and dequeue takes, in ms/job.
// - The manager never inserts more than 10,000 more jobs than the workers have processed.
const INSERT_BATCH_SIZE: usize = 1000;

struct SharedContext {
    jobs_inserted: AtomicUsize,
    jobs_dequeued: AtomicUsize,
}

async fn producer_loop(manager: QueueManager, shared_context: Arc<SharedContext>) {
    let mut time_spent_inserting = Duration::zero();
    let now = Utc::now() - Duration::minutes(1);
    loop {
        let mut to_insert = Vec::with_capacity(1000);
        for _ in 0..INSERT_BATCH_SIZE {
            let queue = if rand::random() { "fetch" } else { "hog" };

            let priority = (rand::random::<u16>() % 3) as i16;

            let test_job = JobInit {
                team_id: 1,
                queue_name: queue.to_string(),
                priority,
                scheduled: now,
                function_id: Some(Uuid::now_v7()),
                vm_state: None,
                parameters: None,
                blob: None,
                metadata: None,
            };

            to_insert.push(test_job);
        }

        let start = Instant::now();
        manager.bulk_create_jobs(to_insert).await;
        let elapsed = start.elapsed();
        time_spent_inserting += Duration::from_std(elapsed).unwrap();

        let inserted = shared_context
            .jobs_inserted
            .fetch_add(INSERT_BATCH_SIZE, std::sync::atomic::Ordering::Relaxed);

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

async fn worker_loop(worker: Worker, shared_context: Arc<SharedContext>, queue: &str) {
    let mut time_spent_dequeuing = Duration::zero();
    let start = Utc::now();
    loop {
        let loop_start = Instant::now();
        let jobs = worker.dequeue_jobs(queue, 1000).await.unwrap();

        if jobs.is_empty() {
            println!(
                "Worker {:?} outpacing inserts, got no jobs, sleeping!",
                queue
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

        time_spent_dequeuing += Duration::from_std(loop_start.elapsed()).unwrap();

        let dequeued = shared_context
            .jobs_dequeued
            .fetch_add(jobs.len(), std::sync::atomic::Ordering::Relaxed);

        // To account for the bunch we just handled
        let dequeued = dequeued + jobs.len();

        println!(
            "Dequeued, processed and completed {} jobs in {} for {:?}. Total time running: {}",
            dequeued,
            time_spent_dequeuing,
            queue,
            Utc::now() - start
        );

        if jobs.len() < 1000 {
            println!(
                "Worker {:?} outpacing manager, only got {} jobs, sleeping!",
                queue,
                jobs.len()
            );
            tokio::time::sleep(Duration::milliseconds(100).to_std().unwrap()).await;
        }
    }
}

#[tokio::main]
async fn main() {
    let pool_config = PoolConfig {
        db_url: "postgresql://posthog:posthog@localhost:5432/cyclotron".to_string(),
        max_connections: None,
        min_connections: None,
        acquire_timeout_seconds: None,
        max_lifetime_seconds: None,
        idle_timeout_seconds: None,
    };

    let manager_config = ManagerConfig {
        shards: vec![pool_config.clone()],
        shard_depth_limit: None,
        shard_depth_check_interval_seconds: None,
    };

    let shared_context = Arc::new(SharedContext {
        jobs_inserted: AtomicUsize::new(0),
        jobs_dequeued: AtomicUsize::new(0),
    });

    let manager = QueueManager::new(manager_config).await.unwrap();
    let worker_1 = Worker::new(pool_config.clone()).await.unwrap();
    let worker_2 = Worker::new(pool_config.clone()).await.unwrap();

    let producer = producer_loop(manager, shared_context.clone());
    let worker_1 = worker_loop(worker_1, shared_context.clone(), "fetch");
    let worker_2 = worker_loop(worker_2, shared_context.clone(), "hog");

    let producer = tokio::spawn(producer);
    let worker_1 = tokio::spawn(worker_1);
    let worker_2 = tokio::spawn(worker_2);

    tokio::try_join!(producer, worker_1, worker_2).unwrap();
}
