use std::{collections::HashMap, sync::Arc, time::Duration};

use moka::future::{Cache, CacheBuilder};
use serde_json::Value;
use sqlx::{Executor, Postgres};
use uuid::Uuid;

use crate::{
    error::UnhandledError,
    frames::releases::{mobile_release_hash_id, ReleaseRecord},
    metric_consts::{ANCILLARY_CACHE, EVENT_RELEASE_RESOLVER_OPERATOR},
    stages::{pipeline::HandledError, resolution::ResolutionStage},
    types::{
        exception_event::{ExceptionEvent, Parsed},
        operator::{OperatorResult, TeamId, ValueOperator},
    },
};

/// Per-worker cache for event-level release resolution. Both lookups run once per exception event
/// on the ingestion hot path, so without this a mobile app that never bound a release re-queries
/// Postgres on every event it sends (the common negative case). The CLI never mutates a release
/// after creating it, but the public API can update or delete one, so a positive hit can go stale;
/// the TTL bounds that staleness, and also how long a miss lingers after a later dSYM upload
/// creates the release. Caching the negative result too is what removes the per-event query.
///
/// The two lookups key on different things — a release-row id for web builds, a reconstructed
/// content hash for mobile builds — so they get separate caches. `try_get_with` coalesces
/// concurrent misses for the same key, so a cold cache under load issues one query per key rather
/// than one per event. moka caches are internally Arc'd, so cloning this into each per-batch
/// `ResolutionStage` is cheap.
///
/// An entry-count budget is a real memory bound here because every cached record is small:
/// `metadata` is clamped to `MAX_RELEASE_METADATA_BYTES` at fetch, and negative entries (`None`)
/// are near-empty.
#[derive(Clone)]
pub struct ReleaseCache {
    by_id: Cache<(TeamId, Uuid), Option<ReleaseRecord>>,
    by_hash: Cache<(TeamId, String), Option<ReleaseRecord>>,
}

impl ReleaseCache {
    /// `max_entries` bounds each of the two caches independently, so the pair can hold twice that.
    pub fn new(max_entries: u64, ttl: Duration) -> Self {
        Self {
            by_id: CacheBuilder::new(max_entries).time_to_live(ttl).build(),
            by_hash: CacheBuilder::new(max_entries).time_to_live(ttl).build(),
        }
    }

    async fn for_id<'c, E>(
        &self,
        e: E,
        id: Uuid,
        team_id: TeamId,
    ) -> Result<Option<ReleaseRecord>, UnhandledError>
    where
        E: Executor<'c, Database = Postgres>,
    {
        let mut cache_miss = false;
        let record = self
            .by_id
            .try_get_with((team_id, id), async {
                cache_miss = true;
                ReleaseRecord::for_id(e, id, team_id).await
            })
            .await
            .map_err(|e: Arc<sqlx::Error>| UnhandledError::Other(e.to_string()))?;

        record_cache_outcome("release_by_id", cache_miss);
        Ok(record)
    }

    async fn for_hash<'c, E>(
        &self,
        e: E,
        hash_id: &str,
        team_id: TeamId,
    ) -> Result<Option<ReleaseRecord>, UnhandledError>
    where
        E: Executor<'c, Database = Postgres>,
    {
        let mut cache_miss = false;
        let record = self
            .by_hash
            .try_get_with((team_id, hash_id.to_string()), async {
                cache_miss = true;
                ReleaseRecord::for_hash(e, hash_id, team_id).await
            })
            .await
            .map_err(|e: Arc<sqlx::Error>| UnhandledError::Other(e.to_string()))?;

        record_cache_outcome("release_by_hash", cache_miss);
        Ok(record)
    }
}

fn record_cache_outcome(cache_type: &'static str, cache_miss: bool) {
    let outcome = if cache_miss { "miss" } else { "hit" };
    metrics::counter!(ANCILLARY_CACHE, "type" => cache_type, "outcome" => outcome).increment(1);
}

/// Resolves the event-level release without going through the per-frame symbol-set join, so the
/// release is independent of which chunks resolved the stack. Runs inside `ResolutionStage` after
/// `resolve_batch`, so a future fallback for legacy events (which carry neither `$release_id` nor
/// app metadata) can read the resolved frames' symbol sets.
///
/// Two sources, in order of preference:
///   1. `$release_id` — web builds inject the release row's id, which the SDK emits verbatim. Direct
///      foreign-key lookup.
///   2. app metadata — mobile SDKs inject nothing, but every event already carries `$app_namespace`,
///      `$app_version`, and `$app_build`, which the CLI hashed into the release when it uploaded the
///      dSYMs. We reconstruct that hash and look the release up by it.
///
/// When neither resolves, the event release stays unset and `$exception_release` is omitted;
/// there is no per-frame fallback yet.
#[derive(Clone, Default)]
pub struct EventReleaseResolver;

impl ValueOperator for EventReleaseResolver {
    type Context = ResolutionStage;
    type Item = ExceptionEvent<Parsed>;
    type HandledError = HandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        EVENT_RELEASE_RESOLVER_OPERATOR
    }

    async fn execute_value(
        &self,
        mut evt: ExceptionEvent<Parsed>,
        ctx: ResolutionStage,
    ) -> OperatorResult<Self> {
        let release_id = evt
            .properties()
            .get("$release_id")
            .and_then(Value::as_str)
            .and_then(|id| Uuid::parse_str(id).ok());

        if let Some(release_id) = release_id {
            let record = ctx
                .release_cache
                .for_id(&ctx.posthog_pool, release_id, evt.team_id())
                .await?;
            evt.set_event_release(record);
        } else if let Some(hash_id) = mobile_release_hash_from_props(evt.properties()) {
            let record = ctx
                .release_cache
                .for_hash(&ctx.posthog_pool, &hash_id, evt.team_id())
                .await?;
            evt.set_event_release(record);
        }

        Ok(Ok(evt))
    }
}

/// Rebuild the release `hash_id` from a mobile event's app metadata. Returns `None` for events that
/// aren't from a mobile SDK (no `$app_namespace`) or lack any version info to key on.
///
/// `$app_build` arrives as a JSON number when the SDK parsed `CFBundleVersion` as an integer, so
/// accept a number or a string and render it the same way the CLI saw the raw plist value.
fn mobile_release_hash_from_props(props: &HashMap<String, Value>) -> Option<String> {
    let namespace = props.get("$app_namespace").and_then(Value::as_str)?;
    let version = props.get("$app_version").and_then(Value::as_str);
    let build = props.get("$app_build").and_then(scalar_to_string);
    mobile_release_hash_id(namespace, version, build.as_deref())
}

fn scalar_to_string(value: &Value) -> Option<String> {
    match value {
        Value::String(s) => Some(s.clone()),
        Value::Number(n) => Some(n.to_string()),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn props(value: Value) -> HashMap<String, Value> {
        value
            .as_object()
            .unwrap()
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect()
    }

    #[test]
    fn numeric_and_string_build_hash_identically() {
        // The iOS SDK parses a numeric CFBundleVersion into an Int, so `$app_build` arrives as a JSON
        // number. It must hash the same as its string form, since the CLI hashed the raw plist string.
        let from_number = mobile_release_hash_from_props(&props(json!({
            "$app_namespace": "com.app", "$app_version": "1.0", "$app_build": 1
        })));
        let from_string = mobile_release_hash_from_props(&props(json!({
            "$app_namespace": "com.app", "$app_version": "1.0", "$app_build": "1"
        })));
        assert!(from_number.is_some());
        assert_eq!(from_number, from_string);
    }

    #[test]
    fn non_mobile_event_yields_no_hash() {
        // No `$app_namespace` means it isn't a mobile SDK event, so there's nothing to resolve.
        assert_eq!(
            mobile_release_hash_from_props(&props(json!({"$app_version": "1.0"}))),
            None
        );
    }
}
