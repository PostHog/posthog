use std::sync::Arc;

use tokio::sync::Semaphore;

use crate::core::config::ResolverConfig;
use crate::core::resolver::build_symbol_resolver;
use crate::error::UnhandledError;
use crate::symbolication::symbol::SymbolResolver;

use super::load_monitor::LoadMonitor;
use super::Config as ServiceConfig;

/// Process-wide handles required to serve `cymbal.resolution.v1`.
///
/// Reuses cymbal's symbol-resolution stack (catalog + frame cache + PG-backed
/// resolved-frame reuse) via [`build_symbol_resolver`]. That builder only
/// connects to Postgres and S3 — Kafka producers, Redis, the issue cache,
/// signals, and the remote-resolution pool are intentionally NOT started here.
/// Resolution mode owns symbol resolution only.
pub struct ResolutionAppContext {
    pub symbol_resolver: Arc<dyn SymbolResolver>,
    pub symbol_resolution_limiter: Arc<Semaphore>,
    pub load_monitor: LoadMonitor,
    pub service_instance_id: String,
}

impl ResolutionAppContext {
    pub async fn from_config(
        resolver: &ResolverConfig,
        service: &ServiceConfig,
    ) -> Result<Self, UnhandledError> {
        let symbol_resolver = build_symbol_resolver(resolver).await?;
        // Symbol-resolution concurrency is the shared knob on the resolver config.
        let symbol_resolution_limiter = Arc::new(Semaphore::new(
            resolver.symbol_resolution_concurrency.max(1),
        ));
        let load_monitor = LoadMonitor::new(service.max_item_concurrency.max(1) as u32);
        let service_instance_id = service
            .service_instance_id
            .clone()
            .unwrap_or_else(|| uuid::Uuid::now_v7().to_string());
        Ok(Self {
            symbol_resolver,
            symbol_resolution_limiter,
            load_monitor,
            service_instance_id,
        })
    }
}
