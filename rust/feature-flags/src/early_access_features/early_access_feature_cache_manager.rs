use crate::early_access_features::early_access_feature_models::EarlyAccessFeature;
use common_database::PostgresReader;
use common_types::ProjectId;
use moka::future::Cache;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;


#[derive(Clone)]
pub struct EarlyAccessFeatureCacheManager {
    reader: PostgresReader,
    cache: Cache<ProjectId, Vec<EarlyAccessFeature>>,
    fetch_lock: Arc<Mutex<()>>,
}

impl EarlyAccessFeatureCacheManager{
    pub fn new(
        reader: PostgresReader,
        max_capacity: Option<u64>,
        ttl_seconds: Option<u64>,
    ) -> Self {
        let cache = Cache::builder()
            .time_to_live((Duration::from_secs(ttl_seconds.unwrap_or(300))))
            .max_capacity((max_capacity.unwrap_or(100_000)))
            .build();

        Self {
            reader,
            cache,
            fetch_lock: Arc::new(Mutex::new(())),
        }
    }
}