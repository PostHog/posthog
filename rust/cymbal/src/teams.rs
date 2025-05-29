use std::{collections::HashMap, sync::Arc, time::Duration};

use common_types::Team;
use moka::sync::{Cache, CacheBuilder};

use crate::{
    app_context::AppContext, config::Config, error::UnhandledError, pipeline::IncomingEvent,
    sanitize_string, WithIndices,
};

pub struct TeamManager {
    cache: Cache<String, Option<Team>>,
}

impl TeamManager {
    pub fn new(config: &Config) -> Self {
        let cache = CacheBuilder::new(config.max_team_cache_size)
            .time_to_live(Duration::from_secs(config.team_cache_ttl_secs))
            .build();

        Self { cache }
    }

    pub async fn get_team<'c, E>(
        &self,
        e: E,
        api_token: &str,
    ) -> Result<Option<Team>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        match self.cache.get(api_token) {
            // We cache "no team" results too, so we don't have to query the database again
            Some(maybe_team) => Ok(maybe_team),
            None => {
                let team = Team::load_by_token(e, api_token).await?;
                self.cache.insert(api_token.to_string(), team.clone());
                Ok(team)
            }
        }
    }
}

pub async fn do_team_lookups(
    context: Arc<AppContext>,
    events: &[IncomingEvent],
) -> Result<HashMap<String, Option<Team>>, (usize, UnhandledError)> {
    let mut team_lookups: HashMap<_, WithIndices<_>> = HashMap::new();
    for (index, event) in events.iter().enumerate() {
        let IncomingEvent::Captured(event) = event else {
            continue; // We don't need to look up teams that already have a team_id
        };

        if team_lookups.contains_key(&event.token) {
            team_lookups
                .get_mut(&event.token)
                .unwrap()
                .indices
                .push(index);
            continue;
        }

        let token = sanitize_string(event.token.clone());

        let m_ctx = context.clone();
        let m_token = token.clone();
        let fut = async move { m_ctx.team_manager.get_team(&m_ctx.pool, &m_token).await };
        let lookup = WithIndices {
            indices: vec![index],
            inner: tokio::spawn(fut),
        };
        team_lookups.insert(token, lookup);
    }

    let mut results = HashMap::new();
    for (token, lookup) in team_lookups {
        let (indices, task) = (lookup.indices, lookup.inner);
        match task.await.expect("Task was not cancelled") {
            Ok(maybe_team) => results.insert(token, maybe_team),
            Err(err) => return Err((indices[0], err)),
        };
    }

    Ok(results)
}
