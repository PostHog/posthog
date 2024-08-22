use chrono::{Duration, Utc};
use cyclotron_core::{JobInit, ManagerConfig, PoolConfig, QueueManager};
use uuid::Uuid;

// Just inserts jobs as fast as it can, choosing randomly between hog and fetch workers, and between different priorities.
// prints every 100 jobs inserted.
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

    let manager = QueueManager::new(manager_config).await.unwrap();

    let now = Utc::now() - Duration::minutes(1);
    let start = Utc::now();
    let mut count = 0;
    loop {
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
            metadata: None,
        };

        manager.create_job(test_job).await.unwrap();

        count += 1;
        if count % 100 == 0 {
            println!("Elapsed: {:?}, count: {}", Utc::now() - start, count);
        }
    }
}
