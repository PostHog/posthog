use std::time::Duration;

use moka::sync::{Cache, CacheBuilder};
use sqlx::PgPool;

use crate::{
    config::Config,
    error::Error,
    symbol_store::{saving::SymbolSetRecord, Catalog},
};

use super::{records::ErrorTrackingStackFrame, Frame, RawFrame};

pub struct Resolver {
    cache: Cache<String, ErrorTrackingStackFrame>,
}

impl Resolver {
    pub fn new(config: &Config) -> Self {
        let cache = CacheBuilder::new(config.frame_cache_size)
            .time_to_live(Duration::from_secs(config.frame_cache_ttl_seconds))
            .build();

        Self { cache }
    }

    pub async fn resolve(
        &self,
        frame: &RawFrame,
        team_id: i32,
        pool: &PgPool,
        catalog: &Catalog,
    ) -> Result<Frame, Error> {
        if let Some(result) = self.cache.get(&frame.frame_id()) {
            return Ok(result.contents);
        }

        if !frame.needs_symbols() {
            return frame.resolve(team_id, catalog).await;
        }

        if let Some(result) =
            ErrorTrackingStackFrame::load(&frame.frame_id(), team_id, pool).await?
        {
            self.cache.insert(frame.frame_id(), result.clone());
            return Ok(result.contents);
        }

        let resolved = frame.resolve(team_id, catalog).await?;

        let set = SymbolSetRecord::load(pool, team_id, &frame.symbol_set_ref()).await?;

        let record = ErrorTrackingStackFrame::new(
            frame.frame_id(),
            team_id,
            set.map(|s| s.id),
            resolved.clone(),
            resolved.resolved,
        );

        record.save(pool).await?;

        self.cache.insert(frame.frame_id(), record);
        Ok(resolved)
    }
}
