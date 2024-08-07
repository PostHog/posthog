use chrono::{Duration, Utc};
use cyclotron_core::{
    base_ops::{JobInit, WaitingOn},
    manager::{ManagerConfig, QueueManager},
    PoolConfig,
};
use uuid::Uuid;

// Just inserts jobs as fast as it can, choosing randomly between hog and fetch workers, and between different priorities.
// prints every 100 jobs inserted.
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

    let now = Utc::now() - Duration::minutes(1);
    let start = Utc::now();
    let mut count = 0;
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

        manager.create_job(test_job).await.unwrap();

        count += 1;
        if count % 100 == 0 {
            println!("Elapsed: {:?}, count: {}", Utc::now() - start, count);
        }
    }
}
