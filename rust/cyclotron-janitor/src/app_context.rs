use chrono::{DateTime, Duration, Utc};
use common_kafka::kafka_producer::{create_kafka_producer, KafkaContext};
use cyclotron_core::{DeleteSet, SHARD_ID_KEY};
use health::{HealthHandle, HealthRegistry};
use rdkafka::producer::FutureProducer;
use serde::Serialize;
use tokio::sync::Mutex;

use crate::{
    config::{Config, JanitorSettings},
    janitor::run_once,
};

pub struct AppContext {
    pub janitor: cyclotron_core::Janitor,
    pub kafka_producer: FutureProducer<KafkaContext>,
    pub metrics_labels: Vec<(String, String)>,
    pub health: HealthRegistry,
    pub janitor_liveness: HealthHandle,
    pub state: AppState,
    pub shard_id: String,
    pub janitor_id: String,
    pub metrics: bool,
}

impl AppContext {
    pub async fn new(config: Config) -> Self {
        let config = config.get_janitor_config();
        let janitor = cyclotron_core::Janitor::new(config.pool)
            .await
            .expect("Failed to create janitor"); // If he dies, he dies (we'd rather panic than try and handle a hard dependecy failure)

        let health = HealthRegistry::new("liveness");

        let metrics_labels = vec![
            ("janitor_id".to_string(), config.janitor.id.clone()),
            (SHARD_ID_KEY.to_string(), config.janitor.shard_id.clone()),
        ];

        let kafka_liveness = health
            .register("rdkafka".to_string(), time::Duration::seconds(30))
            .await;

        let kafka_producer = create_kafka_producer(&config.kafka, kafka_liveness)
            .await
            .expect("failed to create kafka producer");

        let janitor_liveness = health
            .register(
                "janitor".to_string(),
                time::Duration::seconds(config.janitor.cleanup_interval.num_seconds() * 4),
            )
            .await;

        let state = AppState::new(&config.janitor);

        Self {
            janitor,
            kafka_producer,
            metrics_labels,
            health,
            janitor_liveness,
            state,
            shard_id: config.janitor.shard_id,
            janitor_id: config.janitor.id,
            metrics: config.janitor.metrics,
        }
    }

    pub async fn run_migrations(&self) {
        self.janitor.run_migrations().await;
    }

    pub async fn cleanup_loop(&self) {
        // Where we're going, we don't need `break`
        loop {
            let next_run = Utc::now() + self.state.get_control().await.cleanup_interval;
            let mut next_status = run_once(self).await;
            next_status.next_run = Some(next_run);
            self.state.set_status(next_status).await;
            let sleep_time = next_run - Utc::now();
            tokio::time::sleep(sleep_time.to_std().unwrap_or(Default::default())).await;
        }
    }
}

// Cross-cutting state, shared between the cleanup loop and the control interface.
#[derive(Debug)]
pub struct AppState {
    status: Mutex<JanitorStatus>,
    control: Mutex<ControlFlags>,
}

// Transient state, displayed to the user on the control interface. Includes "status" and "control"
#[derive(Debug, Clone, Serialize, Default)]
pub struct JanitorStatus {
    pub last_delete: Option<DeleteSet>,
    pub last_poisoned: Option<u64>,
    pub last_stalled: Option<u64>,
    pub last_available: Option<Vec<(u64, String)>>,
    pub last_dlq_count: Option<u64>,
    pub last_error: Option<String>,
    pub last_error_time: Option<DateTime<Utc>>,
    pub last_successful_run: Option<DateTime<Utc>>,
    pub next_run: Option<DateTime<Utc>>,
}

// Control flags
#[derive(Debug, Clone, Default)]
pub struct ControlFlags {
    // Top-level cleanup loop pause
    pub paused_until: Option<DateTime<Utc>>,
    // Top level cleanup loop interval
    pub cleanup_interval: Duration,
    // How long a lock can be held by a worker before it's considered stalled
    pub stall_timeout: Duration,
    // How many times a job can be touched before it's considered poison
    pub max_touches: i16,
}

impl AppState {
    pub fn new(settings: &JanitorSettings) -> Self {
        let status = Default::default();
        let control = ControlFlags {
            cleanup_interval: settings.cleanup_interval,
            stall_timeout: settings.stall_timeout,
            max_touches: settings.max_touches,
            paused_until: None, // Default to unpaused
        };
        Self {
            status: Mutex::new(status),
            control: Mutex::new(control),
        }
    }

    // The idea with these getters/setters is that the control server
    // or loop should never block each other, so they get a
    // "snapshot" of the current state values, and then call
    // a setter with an updated value, if they're changing anything.
    pub async fn get_status(&self) -> JanitorStatus {
        self.status.lock().await.clone()
    }

    pub async fn get_control(&self) -> ControlFlags {
        self.control.lock().await.clone()
    }

    pub async fn set_control(&self, control: ControlFlags) {
        *self.control.lock().await = control;
    }

    pub async fn set_status(&self, status: JanitorStatus) {
        *self.status.lock().await = status;
    }
}
