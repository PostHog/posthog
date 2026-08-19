use std::{collections::HashMap, sync::Arc, time::Duration};

use moka::future::{Cache, CacheBuilder};
use serde_json::Value;
use sqlx::{Executor, PgPool, Postgres};
use uuid::Uuid;

use crate::{
    error::UnhandledError,
    frames::releases::{mobile_release_hash_id, unpack_version, ReleaseRecord},
    metric_consts::{ANCILLARY_CACHE, EVENT_RELEASE_RESOLUTION, EVENT_RELEASE_RESOLVER_OPERATOR},
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

/// Resolves the single release an event reports as `$exception_release`. Runs inside
/// `ResolutionStage` after `resolve_batch`, because its last source is what resolution found.
///
/// Three sources, in order of preference:
///   1. `$release_id` — web builds inject the release row's id, which the SDK emits verbatim. Direct
///      foreign-key lookup.
///   2. app metadata — mobile SDKs inject nothing, but every event already carries `$app_namespace`,
///      `$app_version`, and `$app_build`, which the CLI hashed into the release when it uploaded the
///      dSYMs. We reconstruct that hash and look the release up by it.
///   3. the releases bound to the symbol sets resolution used, which covers events that carry
///      neither. One id per exception comes back on the wire; the newest wins, so an event whose
///      stack mixes symbol sets from several releases reports the latest.
///
/// When none resolve, the event release stays unset and `$exception_release` is omitted.
///
/// Whatever release it lands on also backfills the event's app metadata, so an exception from
/// any technology reports the app the way a mobile SDK does.
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
        let record = select_release(
            &ctx.posthog_pool,
            &ctx.release_cache,
            evt.team_id(),
            evt.properties(),
            evt.symbol_set_release_ids(),
        )
        .await?;

        if let Some(record) = &record {
            backfill_app_properties(&mut evt, record);
        }
        evt.set_event_release(record);

        Ok(Ok(evt))
    }
}

async fn select_release(
    pool: &PgPool,
    cache: &ReleaseCache,
    team_id: TeamId,
    props: &HashMap<String, Value>,
    symbol_set_release_ids: &[Uuid],
) -> Result<Option<ReleaseRecord>, UnhandledError> {
    let release_id = props
        .get("$release_id")
        .and_then(Value::as_str)
        .and_then(|id| Uuid::parse_str(id).ok());

    let (record, source) = if let Some(release_id) = release_id {
        (cache.for_id(pool, release_id, team_id).await?, "release_id")
    } else if let Some(hash_id) = mobile_release_hash_from_props(props) {
        (
            cache.for_hash(pool, &hash_id, team_id).await?,
            "mobile_hash",
        )
    } else {
        (None, "none")
    };

    if let Some(record) = record {
        record_release_source(source);
        return Ok(Some(record));
    }

    // Reached when the event carries no release identifier, and also when the one it carries
    // points at a release that no longer exists.
    let mut candidates = Vec::new();
    for id in symbol_set_release_ids {
        candidates.extend(cache.for_id(pool, *id, team_id).await?);
    }
    let record = ReleaseRecord::latest(candidates);
    record_release_source(if record.is_some() {
        "symbol_set"
    } else {
        "none"
    });
    Ok(record)
}

fn record_release_source(source: &'static str) {
    metrics::counter!(EVENT_RELEASE_RESOLUTION, "source" => source).increment(1);
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

/// The app a release describes, in the properties mobile SDKs already report on every event:
/// the release's project is the app namespace it was created under, and its version is the app
/// version with the build number packed in.
///
/// Mobile SDKs are the only ones that send these, so copying them off the release is what gives an
/// exception from any other technology the same app metadata, and lets a filter or a grouping rule
/// on app version mean the same thing whichever SDK sent the event.
fn backfill_app_properties(evt: &mut ExceptionEvent<Parsed>, release: &ReleaseRecord) {
    let (version, build) = unpack_version(&release.version);
    evt.set_property_if_absent("$app_namespace", Value::String(release.project.clone()));
    evt.set_property_if_absent("$app_version", Value::String(version.to_string()));
    if let Some(build) = build {
        evt.set_property_if_absent("$app_build", Value::String(build.to_string()));
    }
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

    fn release(project: &str, version: &str) -> ReleaseRecord {
        ReleaseRecord {
            id: Uuid::now_v7(),
            team_id: 1,
            hash_id: "hash".to_string(),
            created_at: chrono::Utc::now(),
            version: version.to_string(),
            project: project.to_string(),
            metadata: None,
        }
    }

    fn parsed_event(properties: Value) -> ExceptionEvent<Parsed> {
        let mut properties = properties;
        properties["$exception_list"] = json!([{"type": "Error", "value": "boom"}]);
        crate::types::event::AnyEvent {
            uuid: Uuid::now_v7(),
            event: "$exception".to_string(),
            team_id: 1,
            timestamp: String::new(),
            properties,
            others: HashMap::new(),
        }
        .try_into()
        .expect("valid exception properties")
    }

    #[test]
    fn the_release_fills_app_metadata_the_sdk_did_not_send() {
        let mut web = parsed_event(json!({}));
        backfill_app_properties(&mut web, &release("my-app", "1.2.3+42"));
        assert_eq!(web.properties()["$app_namespace"], json!("my-app"));
        assert_eq!(web.properties()["$app_version"], json!("1.2.3"));
        assert_eq!(web.properties()["$app_build"], json!("42"));

        // A mobile SDK read these off the running app, and its release may have been created under
        // a name that is not the bundle identifier, so nothing it sent is replaced.
        let mut mobile = parsed_event(json!({
            "$app_namespace": "com.example.app", "$app_version": "1.0", "$app_build": 7
        }));
        backfill_app_properties(&mut mobile, &release("my-app", "1.2.3+42"));
        assert_eq!(
            mobile.properties()["$app_namespace"],
            json!("com.example.app")
        );
        assert_eq!(mobile.properties()["$app_version"], json!("1.0"));
        assert_eq!(mobile.properties()["$app_build"], json!(7));

        // The React Native SDK spreads its app properties into every event whether or not the
        // platform supplied them, so an Expo app that cannot read its own version sends explicit
        // nulls. A null is not a value the SDK observed, so it does not block the backfill.
        let mut expo = parsed_event(json!({
            "$app_namespace": null, "$app_version": null, "$app_build": null
        }));
        backfill_app_properties(&mut expo, &release("my-app", "1.2.3+42"));
        assert_eq!(expo.properties()["$app_namespace"], json!("my-app"));
        assert_eq!(expo.properties()["$app_version"], json!("1.2.3"));
        assert_eq!(expo.properties()["$app_build"], json!("42"));
    }

    const TEAM_ID: TeamId = 1;

    async fn insert_release(pool: &PgPool, hash_id: &str, created_secs: i64) -> Uuid {
        let id = Uuid::now_v7();
        sqlx::query(
            r#"
            INSERT INTO posthog_errortrackingrelease (id, team_id, hash_id, created_at, version, project)
            VALUES ($1, $2, $3, $4, $5, $6)
            "#,
        )
        .bind(id)
        .bind(TEAM_ID)
        .bind(hash_id)
        .bind(chrono::DateTime::from_timestamp(created_secs, 0).unwrap())
        .bind(format!("1.0.{created_secs}"))
        .bind("my-app")
        .execute(pool)
        .await
        .unwrap();
        id
    }

    async fn select(
        pool: &PgPool,
        properties: Value,
        symbol_set_release_ids: &[Uuid],
    ) -> Option<ReleaseRecord> {
        // A fresh cache per call: these cases assert selection, not cache behavior.
        let cache = ReleaseCache::new(64, Duration::from_secs(60));
        select_release(
            pool,
            &cache,
            TEAM_ID,
            &props(properties),
            symbol_set_release_ids,
        )
        .await
        .unwrap()
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn symbol_set_releases_only_fill_the_gap_left_by_the_event_level_sources(pool: PgPool) {
        let event_release = insert_release(&pool, "event-hash", 100).await;
        let older = insert_release(&pool, "older-hash", 200).await;
        let newer = insert_release(&pool, "newer-hash", 5_000).await;
        let symbol_set_ids = [newer, older];

        let selected = select(
            &pool,
            json!({ "$release_id": event_release.to_string() }),
            &symbol_set_ids,
        )
        .await;
        assert_eq!(
            selected.map(|r| r.id),
            Some(event_release),
            "the event's own release outranks the symbol sets', even when theirs is newer"
        );

        let selected = select(&pool, json!({}), &symbol_set_ids).await;
        assert_eq!(
            selected.map(|r| r.id),
            Some(newer),
            "with no event-level release, the newest symbol-set release wins regardless of order"
        );

        // A `$release_id` for a release that has since been deleted resolves to nothing, so the
        // fallback still applies.
        let selected = select(
            &pool,
            json!({ "$release_id": Uuid::now_v7().to_string() }),
            &[older],
        )
        .await;
        assert_eq!(selected.map(|r| r.id), Some(older));

        assert!(select(&pool, json!({}), &[]).await.is_none());
    }
}
