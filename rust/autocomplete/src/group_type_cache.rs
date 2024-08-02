use std::num::NonZeroUsize;

use lru::LruCache;
use sqlx::PgPool;
use tokio::sync::Mutex;
use tracing::warn;

use crate::types::TeamId;

pub const MAX_GROUP_TYPES_PER_TEAM: usize = 5;

#[derive(Debug, Clone)]
pub struct GroupType {
    index: i32,
    name: String,
}

pub struct GroupTypeCache {
    pool: PgPool,
    cache: Mutex<LruCache<TeamId, Vec<GroupType>>>,
}

impl GroupTypeCache {
    pub fn new(pool: &PgPool) -> Self {
        let capacity = NonZeroUsize::new(1_000_000).unwrap(); // TODO - pull this from the environment

        Self {
            pool: pool.clone(),
            cache: Mutex::new(LruCache::new(capacity)),
        }
    }

    pub async fn get_group_type_index(
        &self,
        team_id: TeamId,
        group_type: &str,
    ) -> Result<Option<i32>, sqlx::Error> {
        let mut cache = self.cache.lock().await;

        if let Some(group_types) = cache.get(&team_id) {
            let found_id = group_types
                .iter()
                .find(|gt: &&GroupType| gt.name == group_type)
                .map(|gt| gt.index);
            if found_id.is_some() {
                return Ok(found_id);
            }
        }

        let group_types = self.load_group_types(team_id).await?;

        let found_id = group_types
            .iter()
            .find(|gt: &&GroupType| gt.name == group_type)
            .map(|gt| gt.index);
        cache.put(team_id, group_types);

        // Afer a discussion with ben, we decided that if the group type is not found, we should discard
        // the property updates, rather than creating the group - this is a divergence from the TS impl's
        // behavior, and we should notify when it happens. Groups "should" be created by the UI or by
        // the plugin server, for various reasons - property definitions can be async, but group types
        // can't be.
        if found_id.is_none() {
            warn!("Group type not found: {}", group_type);
        }

        Ok(found_id)
    }

    async fn load_group_types(&self, team_id: TeamId) -> Result<Vec<GroupType>, sqlx::Error> {
        let group_types = sqlx::query_as!(
            GroupType,
            "SELECT group_type as name, group_type_index as index FROM posthog_grouptypemapping WHERE team_id = $1",
            team_id.0
        )
        .fetch_all(&self.pool)
        .await?;

        Ok(group_types)
    }

    pub async fn flush(&self) {
        self.cache.lock().await.clear();
    }
}
