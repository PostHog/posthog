use std::sync::Arc;

use cymbal::app_context::build_symbol_resolver;
use cymbal::config::Config as CymbalConfig;
use cymbal::error::UnhandledError;
use cymbal::stages::resolution::symbol::SymbolResolver;
use tokio::sync::Semaphore;

use crate::config::Config;
use crate::load_monitor::LoadMonitor;

/// Process-wide handles required to serve `cymbal.resolution.v1`.
///
/// v1 reuses cymbal's symbol-resolution stack (catalog + frame cache + PG-
/// backed resolved-frame reuse) via [`build_symbol_resolver`]. That builder
/// only connects to Postgres and S3 — Kafka producers, Redis, the issue
/// cache, signals, and the remote-resolution pool are intentionally NOT
/// started here. cymbal-resolution owns symbol resolution only.
pub struct AppContext {
    pub symbol_resolver: Arc<dyn SymbolResolver>,
    pub symbol_resolution_limiter: Arc<Semaphore>,
    pub load_monitor: LoadMonitor,
    pub config: Config,
    pub service_instance_id: String,
}

impl AppContext {
    pub async fn from_config(
        config: Config,
        cymbal_config: &CymbalConfig,
    ) -> Result<Self, UnhandledError> {
        let symbol_resolver = build_symbol_resolver(cymbal_config).await?;
        Ok(Self::from_resolver(
            config,
            symbol_resolver,
            // Use a dedicated limiter for this service so its concurrency
            // surface is independent of any cymbal-side configuration.
            None,
        ))
    }

    /// Constructor for tests and integrations that already own a resolver. The
    /// optional limiter override is used by tests that need to force the
    /// permit acquisition path; production callers pass `None`.
    pub fn from_resolver(
        config: Config,
        symbol_resolver: Arc<dyn SymbolResolver>,
        symbol_resolution_limiter: Option<Arc<Semaphore>>,
    ) -> Self {
        let symbol_resolution_limiter = symbol_resolution_limiter.unwrap_or_else(|| {
            Arc::new(Semaphore::new(config.symbol_resolution_concurrency.max(1)))
        });
        let max_item_concurrency = config.max_item_concurrency.max(1);
        let load_monitor = LoadMonitor::new(max_item_concurrency as u32);
        let service_instance_id = config
            .service_instance_id
            .clone()
            .unwrap_or_else(|| uuid::Uuid::now_v7().to_string());
        Self {
            symbol_resolver,
            symbol_resolution_limiter,
            load_monitor,
            config,
            service_instance_id,
        }
    }
}
