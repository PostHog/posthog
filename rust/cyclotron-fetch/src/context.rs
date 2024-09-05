use std::sync::{Arc, RwLock};

use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::create_kafka_producer;
use common_kafka::kafka_producer::KafkaContext;
use cyclotron_core::{PoolConfig, Worker, SHARD_ID_KEY};
use health::HealthHandle;
use rdkafka::producer::FutureProducer;
use tokio::sync::Semaphore;

use crate::{config::AppConfig, fetch::FetchError};

pub struct AppContext {
    pub worker: Worker,
    pub client: reqwest::Client,
    pub kafka_producer: FutureProducer<KafkaContext>,
    pub concurrency_limit: Arc<Semaphore>,
    pub liveness: HealthHandle,
    pub config: AppConfig,
    pub metric_labels: RwLock<Vec<(String, String)>>,
}

impl AppContext {
    pub async fn create(
        config: AppConfig,
        pool_config: PoolConfig,
        kafka_config: KafkaConfig,
        liveness: HealthHandle,
        kafka_liveness: HealthHandle,
    ) -> Result<Self, FetchError> {
        let concurrency_limit = Arc::new(Semaphore::new(config.concurrent_requests_limit as usize));

        let resolver = Arc::new(common_dns::PublicIPv4Resolver {});

        let mut client = reqwest::Client::builder().timeout(config.fetch_timeout.to_std().unwrap());

        if !config.allow_internal_ips {
            client = client.dns_resolver(resolver);
        }

        let client = client.build();

        let client = match client {
            Ok(c) => c,
            Err(e) => {
                return Err(FetchError::StartupError(format!(
                    "Failed to create reqwest client: {}",
                    e
                )));
            }
        };

        let worker = Worker::new(pool_config).await?;

        let labels = vec![
            (SHARD_ID_KEY.to_string(), config.shard_id.clone()),
            ("worker_id".to_string(), config.worker_id.clone()),
            ("queue_served".to_string(), config.queue_served.clone()),
        ];

        let kafka_producer = create_kafka_producer(&kafka_config, kafka_liveness)
            .await
            .expect("failed to create kafka producer");

        Ok(Self {
            worker,
            client,
            kafka_producer,
            concurrency_limit,
            liveness,
            config,
            metric_labels: RwLock::new(labels),
        })
    }

    // *Relatively* cheap, compared to the update above, but
    // still, better to grab at the top of your fn and then
    // reuse
    pub fn metric_labels(&self) -> Vec<(String, String)> {
        self.metric_labels.read().unwrap().clone()
    }
}
