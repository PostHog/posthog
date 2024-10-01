use std::{future::Future, time::Duration};

use common_types::Team;
use moka::sync::{Cache, CacheBuilder};
use tokio::sync::RwLock;

use crate::error::Error;

// This /could/ be moved into common/types, but I'd have to take
// a dependency on tokio and moka to do it, and I don't want to
// do that just yet (although it is used across here and feature
// flags, so....)
pub struct TeamCache {
    // The lock here isn't necessary (the Cache is concurrent),
    // but is used to ensure the DB is only hit once.
    // Note that we cache the none-case to prevent
    // people hammering us with false tokens and bringing
    // down PG.
    teams: RwLock<Cache<String, Option<Team>>>,
}

impl TeamCache {
    pub fn new(capacity: u64, ttl_seconds: u64) -> Self {
        let cache = CacheBuilder::new(capacity)
            .time_to_live(Duration::from_secs(ttl_seconds))
            .build();

        Self {
            teams: RwLock::new(cache),
        }
    }

    pub async fn get_or_insert_with<F>(&self, token: &str, f: F) -> Result<Option<Team>, Error>
    where
        F: Future<Output = Result<Option<Team>, Error>>,
    {
        let teams = self.teams.read().await;
        if let Some(team) = teams.get(token) {
            return Ok(team.clone());
        }
        drop(teams);
        let teams = self.teams.write().await;
        if let Some(team) = teams.get(token) {
            return Ok(team.clone());
        }
        let team = f.await?;
        teams.insert(token.to_string(), team.clone());
        Ok(team)
    }

    pub async fn contains(&self, token: &str) -> bool {
        self.teams.read().await.contains_key(token)
    }

    pub async fn remove(&self, token: &str) {
        self.teams.write().await.remove(token);
    }
}
