use std::{sync::Arc, time::Duration};

use async_trait::async_trait;
use common_types::error_tracking::RawFrameId;
use thiserror::Error;
use uuid::Uuid;

use crate::core::{error::FrameError, symbolication::symbol::records::ErrorTrackingStackFrame};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CacheReadOutcome<T> {
    Hit(T),
    Miss,
    Disabled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CacheWriteOutcome {
    Stored,
    Deleted,
    NotFound,
    SkippedDisabled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CacheGateOutcome {
    Acquired,
    Held,
    Disabled,
}

#[derive(Debug, Error)]
pub enum ResolutionCacheError {
    #[error("resolution cache timed out")]
    Timeout,
    #[error("resolution cache unavailable: {0}")]
    Unavailable(String),
    #[error("invalid resolution cache value: {0}")]
    InvalidValue(String),
    #[error("resolution cache value exceeds configured size limit")]
    Oversized,
}

pub type ResolutionCacheResult<T> = Result<T, ResolutionCacheError>;

#[async_trait]
pub trait ResolutionCache: Send + Sync {
    async fn get_frame(
        &self,
        id: &RawFrameId,
    ) -> ResolutionCacheResult<CacheReadOutcome<Vec<ErrorTrackingStackFrame>>>;

    async fn set_frame(
        &self,
        id: &RawFrameId,
        records: &[ErrorTrackingStackFrame],
        ttl: Duration,
    ) -> ResolutionCacheResult<CacheWriteOutcome>;

    async fn get_failure(
        &self,
        team_id: i32,
        symbol_set_ref: &str,
    ) -> ResolutionCacheResult<CacheReadOutcome<FrameError>>;

    async fn set_failure(
        &self,
        team_id: i32,
        symbol_set_ref: &str,
        failure: &FrameError,
        ttl: Duration,
    ) -> ResolutionCacheResult<CacheWriteOutcome>;

    async fn delete_failure(
        &self,
        team_id: i32,
        symbol_set_ref: &str,
    ) -> ResolutionCacheResult<CacheWriteOutcome>;

    async fn try_acquire_touch(
        &self,
        symbol_set_id: Uuid,
        token: &str,
        ttl: Duration,
    ) -> ResolutionCacheResult<CacheGateOutcome>;

    async fn release_touch(
        &self,
        symbol_set_id: Uuid,
        token: &str,
    ) -> ResolutionCacheResult<CacheWriteOutcome>;
}

#[derive(Debug, Default)]
pub struct DisabledResolutionCache;

#[async_trait]
impl ResolutionCache for DisabledResolutionCache {
    async fn get_frame(
        &self,
        _id: &RawFrameId,
    ) -> ResolutionCacheResult<CacheReadOutcome<Vec<ErrorTrackingStackFrame>>> {
        Ok(CacheReadOutcome::Disabled)
    }

    async fn set_frame(
        &self,
        _id: &RawFrameId,
        _records: &[ErrorTrackingStackFrame],
        _ttl: Duration,
    ) -> ResolutionCacheResult<CacheWriteOutcome> {
        Ok(CacheWriteOutcome::SkippedDisabled)
    }

    async fn get_failure(
        &self,
        _team_id: i32,
        _symbol_set_ref: &str,
    ) -> ResolutionCacheResult<CacheReadOutcome<FrameError>> {
        Ok(CacheReadOutcome::Disabled)
    }

    async fn set_failure(
        &self,
        _team_id: i32,
        _symbol_set_ref: &str,
        _failure: &FrameError,
        _ttl: Duration,
    ) -> ResolutionCacheResult<CacheWriteOutcome> {
        Ok(CacheWriteOutcome::SkippedDisabled)
    }

    async fn delete_failure(
        &self,
        _team_id: i32,
        _symbol_set_ref: &str,
    ) -> ResolutionCacheResult<CacheWriteOutcome> {
        Ok(CacheWriteOutcome::SkippedDisabled)
    }

    async fn try_acquire_touch(
        &self,
        _symbol_set_id: Uuid,
        _token: &str,
        _ttl: Duration,
    ) -> ResolutionCacheResult<CacheGateOutcome> {
        Ok(CacheGateOutcome::Disabled)
    }

    async fn release_touch(
        &self,
        _symbol_set_id: Uuid,
        _token: &str,
    ) -> ResolutionCacheResult<CacheWriteOutcome> {
        Ok(CacheWriteOutcome::SkippedDisabled)
    }
}

pub fn disabled_resolution_cache() -> Arc<dyn ResolutionCache> {
    Arc::new(DisabledResolutionCache)
}

#[cfg(test)]
#[derive(Debug)]
struct Expiring<T> {
    value: T,
    expires_at: Duration,
}

#[cfg(test)]
#[derive(Debug, Default)]
struct InMemoryState {
    now: Duration,
    frames: std::collections::HashMap<RawFrameId, Expiring<Vec<ErrorTrackingStackFrame>>>,
    failures: std::collections::HashMap<(i32, String), Expiring<FrameError>>,
    touches: std::collections::HashMap<Uuid, Expiring<String>>,
}

#[cfg(test)]
#[derive(Debug, Default)]
pub(crate) struct InMemoryResolutionCache(std::sync::Mutex<InMemoryState>);

#[cfg(test)]
impl InMemoryResolutionCache {
    pub fn advance(&self, duration: Duration) {
        self.0.lock().unwrap().now += duration;
    }
}

#[cfg(test)]
#[async_trait]
impl ResolutionCache for InMemoryResolutionCache {
    async fn get_frame(
        &self,
        id: &RawFrameId,
    ) -> ResolutionCacheResult<CacheReadOutcome<Vec<ErrorTrackingStackFrame>>> {
        let mut state = self.0.lock().unwrap();
        let now = state.now;
        let outcome = match state.frames.get(id) {
            Some(entry) if entry.expires_at > now => CacheReadOutcome::Hit(entry.value.clone()),
            Some(_) => {
                state.frames.remove(id);
                CacheReadOutcome::Miss
            }
            None => CacheReadOutcome::Miss,
        };
        Ok(outcome)
    }

    async fn set_frame(
        &self,
        id: &RawFrameId,
        records: &[ErrorTrackingStackFrame],
        ttl: Duration,
    ) -> ResolutionCacheResult<CacheWriteOutcome> {
        let mut state = self.0.lock().unwrap();
        let expires_at = state.now + ttl;
        state.frames.insert(
            id.clone(),
            Expiring {
                value: records.to_vec(),
                expires_at,
            },
        );
        Ok(CacheWriteOutcome::Stored)
    }

    async fn get_failure(
        &self,
        team_id: i32,
        symbol_set_ref: &str,
    ) -> ResolutionCacheResult<CacheReadOutcome<FrameError>> {
        let mut state = self.0.lock().unwrap();
        let now = state.now;
        let key = (team_id, symbol_set_ref.to_string());
        let outcome = match state.failures.get(&key) {
            Some(entry) if entry.expires_at > now => CacheReadOutcome::Hit(entry.value.clone()),
            Some(_) => {
                state.failures.remove(&key);
                CacheReadOutcome::Miss
            }
            None => CacheReadOutcome::Miss,
        };
        Ok(outcome)
    }

    async fn set_failure(
        &self,
        team_id: i32,
        symbol_set_ref: &str,
        failure: &FrameError,
        ttl: Duration,
    ) -> ResolutionCacheResult<CacheWriteOutcome> {
        let mut state = self.0.lock().unwrap();
        let expires_at = state.now + ttl;
        state.failures.insert(
            (team_id, symbol_set_ref.to_string()),
            Expiring {
                value: failure.clone(),
                expires_at,
            },
        );
        Ok(CacheWriteOutcome::Stored)
    }

    async fn delete_failure(
        &self,
        team_id: i32,
        symbol_set_ref: &str,
    ) -> ResolutionCacheResult<CacheWriteOutcome> {
        let mut state = self.0.lock().unwrap();
        let key = (team_id, symbol_set_ref.to_string());
        let exists = state
            .failures
            .get(&key)
            .is_some_and(|entry| entry.expires_at > state.now);
        state.failures.remove(&key);
        Ok(if exists {
            CacheWriteOutcome::Deleted
        } else {
            CacheWriteOutcome::NotFound
        })
    }

    async fn try_acquire_touch(
        &self,
        symbol_set_id: Uuid,
        token: &str,
        ttl: Duration,
    ) -> ResolutionCacheResult<CacheGateOutcome> {
        let mut state = self.0.lock().unwrap();
        let now = state.now;
        if state
            .touches
            .get(&symbol_set_id)
            .is_some_and(|entry| entry.expires_at > now)
        {
            return Ok(CacheGateOutcome::Held);
        }
        let expires_at = now + ttl;
        state.touches.insert(
            symbol_set_id,
            Expiring {
                value: token.to_string(),
                expires_at,
            },
        );
        Ok(CacheGateOutcome::Acquired)
    }

    async fn release_touch(
        &self,
        symbol_set_id: Uuid,
        token: &str,
    ) -> ResolutionCacheResult<CacheWriteOutcome> {
        let mut state = self.0.lock().unwrap();
        let now = state.now;
        let matches = state
            .touches
            .get(&symbol_set_id)
            .is_some_and(|entry| entry.expires_at > now && entry.value == token);
        if matches {
            state.touches.remove(&symbol_set_id);
            Ok(CacheWriteOutcome::Deleted)
        } else {
            Ok(CacheWriteOutcome::NotFound)
        }
    }
}

#[cfg(test)]
mod tests {
    use std::{sync::Arc, time::Duration};

    use common_types::error_tracking::RawFrameId;
    use uuid::Uuid;

    use super::{
        CacheGateOutcome, CacheReadOutcome, CacheWriteOutcome, DisabledResolutionCache,
        InMemoryResolutionCache, ResolutionCache,
    };
    use crate::core::error::{FrameError, JsResolveErr};

    fn object_safe(cache: Arc<dyn ResolutionCache>) -> Arc<dyn ResolutionCache> {
        cache
    }

    #[tokio::test]
    async fn disabled_cache_never_stores_or_blocks_work() {
        let cache = object_safe(Arc::new(DisabledResolutionCache));
        let frame_id = RawFrameId::new("frame".to_string(), 1);
        let symbol_set_id = Uuid::now_v7();

        assert!(matches!(
            cache.get_frame(&frame_id).await.unwrap(),
            CacheReadOutcome::Disabled
        ));
        assert_eq!(
            cache
                .set_frame(&frame_id, &[], Duration::from_secs(30))
                .await
                .unwrap(),
            CacheWriteOutcome::SkippedDisabled
        );
        assert_eq!(
            cache
                .get_failure(1, "https://example.test/app.js")
                .await
                .unwrap(),
            CacheReadOutcome::Disabled
        );
        assert_eq!(
            cache
                .set_failure(
                    1,
                    "https://example.test/app.js",
                    &FrameError::JavaScript(JsResolveErr::NoSourcemap("missing".to_string())),
                    Duration::from_secs(30),
                )
                .await
                .unwrap(),
            CacheWriteOutcome::SkippedDisabled
        );
        assert_eq!(
            cache
                .delete_failure(1, "https://example.test/app.js")
                .await
                .unwrap(),
            CacheWriteOutcome::SkippedDisabled
        );
        assert_eq!(
            cache
                .try_acquire_touch(symbol_set_id, "token", Duration::from_secs(30))
                .await
                .unwrap(),
            CacheGateOutcome::Disabled
        );
        assert_eq!(
            cache.release_touch(symbol_set_id, "token").await.unwrap(),
            CacheWriteOutcome::SkippedDisabled
        );
    }

    #[tokio::test]
    async fn in_memory_cache_expires_entries_and_releases_touch_by_token() {
        let cache = InMemoryResolutionCache::default();
        let failure = FrameError::JavaScript(JsResolveErr::NoSourcemap("missing".to_string()));
        let ttl = Duration::from_secs(30);
        let frame_id = RawFrameId::new("frame".to_string(), 1);
        let symbol_set_id = Uuid::now_v7();

        assert_eq!(
            cache.set_frame(&frame_id, &[], ttl).await.unwrap(),
            CacheWriteOutcome::Stored
        );
        assert!(matches!(
            cache.get_frame(&frame_id).await.unwrap(),
            CacheReadOutcome::Hit(records) if records.is_empty()
        ));

        assert_eq!(
            cache
                .set_failure(1, "https://example.test/app.js", &failure, ttl)
                .await
                .unwrap(),
            CacheWriteOutcome::Stored
        );
        assert_eq!(
            cache
                .get_failure(1, "https://example.test/app.js")
                .await
                .unwrap(),
            CacheReadOutcome::Hit(failure.clone())
        );

        assert_eq!(
            cache
                .try_acquire_touch(symbol_set_id, "winner", ttl)
                .await
                .unwrap(),
            CacheGateOutcome::Acquired
        );
        assert_eq!(
            cache
                .try_acquire_touch(symbol_set_id, "loser", ttl)
                .await
                .unwrap(),
            CacheGateOutcome::Held
        );
        assert_eq!(
            cache.release_touch(symbol_set_id, "loser").await.unwrap(),
            CacheWriteOutcome::NotFound
        );
        assert_eq!(
            cache.release_touch(symbol_set_id, "winner").await.unwrap(),
            CacheWriteOutcome::Deleted
        );

        cache.advance(ttl + Duration::from_secs(1));
        assert!(matches!(
            cache.get_frame(&frame_id).await.unwrap(),
            CacheReadOutcome::Miss
        ));
        assert_eq!(
            cache
                .get_failure(1, "https://example.test/app.js")
                .await
                .unwrap(),
            CacheReadOutcome::Miss
        );
    }
}
