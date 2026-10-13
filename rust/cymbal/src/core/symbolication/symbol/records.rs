use chrono::{DateTime, Duration, Utc};
use common_types::error_tracking::{FrameId, RawFrameId};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sqlx::Executor;
use uuid::Uuid;

use crate::core::write_attribution::FrameWriteOutcome;
use crate::error::UnhandledError;
use crate::frames::{Context, Frame};

const FRAME_TTL_JITTER_PERCENT: u32 = 10;

#[derive(Debug, Clone, Copy)]
pub struct FrameResultTtlPolicy {
    resolved_ttl: Duration,
    unresolved_ttl: Duration,
}

impl FrameResultTtlPolicy {
    pub fn new(resolved_ttl: Duration, unresolved_ttl: Duration) -> Self {
        Self {
            resolved_ttl,
            unresolved_ttl,
        }
    }

    pub fn ttl_for_records(
        &self,
        id: &RawFrameId,
        records: &[ErrorTrackingStackFrame],
    ) -> Duration {
        self.ttl_for_resolved_status(id, records.iter().all(|record| record.resolved))
    }

    pub fn ttl_for_resolved_status(&self, id: &RawFrameId, all_resolved: bool) -> Duration {
        let base_ttl = if all_resolved {
            self.resolved_ttl
        } else {
            self.unresolved_ttl
        };

        base_ttl + self.jitter_for(id, base_ttl)
    }

    // Age past which an unchanged snapshot must still write, so created_at keeps the
    // rows inside the freshness window `load_snapshot` checks. Half the TTL leaves a
    // full half-window of slack before a skipped write could turn the rows stale. The
    // TTL carries the per-frame jitter from `stable_jitter_hash`, so refresh
    // boundaries do not synchronize across frames.
    pub(crate) fn refresh_age(
        &self,
        id: &RawFrameId,
        records: &[ErrorTrackingStackFrame],
    ) -> Duration {
        self.ttl_for_records(id, records) / 2
    }

    fn jitter_for(&self, id: &RawFrameId, base_ttl: Duration) -> Duration {
        if base_ttl <= Duration::zero() {
            return Duration::zero();
        }

        let base_millis = base_ttl.num_milliseconds() as u64;
        let max_jitter_millis = base_millis * u64::from(FRAME_TTL_JITTER_PERCENT) / 100;
        if max_jitter_millis == 0 {
            return Duration::zero();
        }

        Duration::milliseconds((stable_jitter_hash(id) % (max_jitter_millis + 1)) as i64)
    }
}

fn stable_jitter_hash(id: &RawFrameId) -> u64 {
    let mut hash = 0xcbf29ce484222325_u64;
    for byte in id
        .hash_id
        .as_bytes()
        .iter()
        .chain(id.team_id.to_le_bytes().iter())
    {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ErrorTrackingStackFrame {
    pub id: FrameId,
    pub created_at: DateTime<Utc>,
    pub symbol_set_id: Option<Uuid>,
    pub contents: Frame,
    pub resolved: bool,
    pub context: Option<Context>,
}

#[derive(Debug)]
pub(crate) struct StoredFrameSnapshot {
    pub records: Vec<ErrorTrackingStackFrame>,
    pub fresh: bool,
}

// Decides whether an unchanged snapshot still needs a created_at refresh. Any row
// past the refresh age must write: a row whose created_at never refreshes goes
// permanently stale, and cymbal then re-resolves that frame on every cache miss
// forever, which costs far more than the write it saved.
pub(crate) fn unchanged_snapshot_needs_refresh(
    policy: &FrameResultTtlPolicy,
    id: &RawFrameId,
    records: &[ErrorTrackingStackFrame],
    now: DateTime<Utc>,
) -> bool {
    let refresh_age = policy.refresh_age(id, records);
    records
        .iter()
        .any(|record| record.created_at <= now - refresh_age)
}

pub(crate) fn classify_frame_snapshot(
    existing: &[ErrorTrackingStackFrame],
    current: &[ErrorTrackingStackFrame],
) -> FrameWriteOutcome {
    if existing.is_empty() {
        return FrameWriteOutcome::Insert;
    }

    if existing.len() == current.len()
        && existing.iter().zip(current).all(|(existing, current)| {
            existing.id == current.id
                && existing.symbol_set_id == current.symbol_set_id
                && existing.contents == current.contents
                && existing.resolved == current.resolved
                && existing.context == current.context
        })
    {
        FrameWriteOutcome::Unchanged
    } else {
        FrameWriteOutcome::Changed
    }
}

impl ErrorTrackingStackFrame {
    pub fn new(
        id: FrameId,
        symbol_set_id: Option<Uuid>,
        contents: Frame,
        resolved: bool,
        context: Option<Context>,
    ) -> Self {
        Self {
            id,
            symbol_set_id,
            contents,
            resolved,
            created_at: Utc::now(),
            context,
        }
    }

    pub async fn save<'c, E>(&self, e: E) -> Result<u64, UnhandledError>
    where
        E: Executor<'c, Database = sqlx::Postgres>,
    {
        self.save_with_refresh_guard(e, None).await
    }

    // Racing writers load the same stale snapshot and would each rewrite identical
    // content. With a threshold, the conflict update becomes a server-side no-op
    // (no new tuple version, rows_affected 0) unless the row's content differs or
    // its created_at is older than the threshold. `None` keeps the update
    // unconditional.
    pub(crate) async fn save_with_refresh_guard<'c, E>(
        &self,
        e: E,
        refresh_if_older_than: Option<DateTime<Utc>>,
    ) -> Result<u64, UnhandledError>
    where
        E: Executor<'c, Database = sqlx::Postgres>,
    {
        let context = if let Some(context) = &self.context {
            Some(serde_json::to_value(context)?)
        } else {
            None
        };
        let result = sqlx::query!(
            r#"
            INSERT INTO posthog_errortrackingstackframe (raw_id, part, team_id, created_at, symbol_set_id, contents, resolved, id, context)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (raw_id, team_id, part) DO UPDATE SET
                created_at = $4,
                symbol_set_id = $5,
                contents = $6,
                resolved = $7,
                context = $9
            WHERE posthog_errortrackingstackframe.symbol_set_id IS DISTINCT FROM $5
                OR posthog_errortrackingstackframe.contents IS DISTINCT FROM $6
                OR posthog_errortrackingstackframe.resolved IS DISTINCT FROM $7
                OR posthog_errortrackingstackframe.context IS DISTINCT FROM $9
                OR posthog_errortrackingstackframe.created_at < COALESCE($10, 'infinity'::timestamptz)
            "#,
            self.id.hash_id,
            self.id.part,
            self.id.team_id,
            self.created_at,
            self.symbol_set_id,
            serde_json::to_value(&self.contents)?,
            self.resolved,
            Uuid::now_v7(),
            context,
            refresh_if_older_than,
        )
        .execute(e)
        .await?;
        Ok(result.rows_affected())
    }

    // Bumps created_at on every part of a raw frame without rewriting the row
    // contents, so an unchanged re-resolution refreshes freshness without the fat
    // JSON rewrite (a smaller tuple WAL record and no re-TOAST of `contents`).
    // Returns the number of rows updated; a count below the loaded part count means
    // the rows changed under us (for example symbol-set cleanup deleted them) and
    // the caller must fall back to the full upsert.
    pub(crate) async fn refresh_created_at<'c, E>(
        e: E,
        id: &RawFrameId,
        created_at: DateTime<Utc>,
    ) -> Result<u64, UnhandledError>
    where
        E: Executor<'c, Database = sqlx::Postgres>,
    {
        let result = sqlx::query!(
            r#"
            UPDATE posthog_errortrackingstackframe
            SET created_at = $3
            WHERE raw_id = $1 AND team_id = $2
            "#,
            id.hash_id,
            id.team_id,
            created_at,
        )
        .execute(e)
        .await?;
        Ok(result.rows_affected())
    }

    pub async fn load_all<'c, E>(
        e: E,
        id: &RawFrameId,
        ttl_policy: FrameResultTtlPolicy,
    ) -> Result<Vec<Self>, UnhandledError>
    where
        E: Executor<'c, Database = sqlx::Postgres>,
    {
        let snapshot = Self::load_snapshot(e, id, ttl_policy).await?;
        if snapshot.fresh {
            Ok(snapshot.records)
        } else {
            Ok(Vec::new())
        }
    }

    pub(crate) async fn load_snapshot<'c, E>(
        e: E,
        id: &RawFrameId,
        ttl_policy: FrameResultTtlPolicy,
    ) -> Result<StoredFrameSnapshot, UnhandledError>
    where
        E: Executor<'c, Database = sqlx::Postgres>,
    {
        struct Returned {
            raw_id: String,
            part: i32,
            team_id: i32,
            created_at: DateTime<Utc>,
            symbol_set_id: Option<Uuid>,
            contents: Value,
            resolved: bool,
            context: Option<Value>,
        }
        let res = sqlx::query_as!(
            Returned,
            r#"
            SELECT raw_id, part, team_id, created_at, symbol_set_id, contents, resolved, context
            FROM posthog_errortrackingstackframe
            WHERE raw_id = $1 AND team_id = $2
            ORDER BY part
            "#,
            id.hash_id,
            id.team_id
        )
        .fetch_all(e)
        .await?;

        let result_ttl = ttl_policy.ttl_for_resolved_status(id, res.iter().all(|f| f.resolved));
        let fresh = !res.is_empty() && res.iter().all(|f| f.created_at >= Utc::now() - result_ttl);

        let mut results = Vec::new();
        for found in res {
            // Frame ID's lose team_id when they're serialized, so we fix that up here when loading them
            let frame_id = FrameId::new(found.raw_id, found.team_id, found.part);
            // We don't serialise frame contexts on the Frame itself, but save it on the frame record,
            // and so when we load a frame record we need to patch back up the context onto the frame,
            // since we dropped it when we serialised the frame during saving.
            let mut frame: Frame = serde_json::from_value(found.contents)?;
            frame.frame_id = frame_id;

            let context = if let Some(context) = found.context {
                // We serialise the frame context as a json string, but it's a structure we have to manually
                // deserialise back into the frame.
                serde_json::from_value(context)?
            } else {
                None
            };

            frame.context = context.clone();

            results.push(Self {
                id: frame.frame_id.clone(),
                created_at: found.created_at,
                symbol_set_id: found.symbol_set_id,
                contents: frame,
                resolved: found.resolved,
                context,
            })
        }

        Ok(StoredFrameSnapshot {
            records: results,
            fresh,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frame_with_part(id: FrameId, part: i32) -> Frame {
        Frame {
            frame_id: id,
            mangled_name: format!("fn_{part}"),
            line: None,
            column: None,
            source: None,
            module: None,
            in_app: true,
            resolved_name: None,
            lang: "go".to_string(),
            resolved: true,
            resolve_failure: None,
            synthetic: false,
            suspicious: false,
            junk_drawer: None,
            code_variables: None,
            context: None,
        }
    }

    // Multi-part records are one raw frame's inline expansion — part order is
    // stack order, so a cache hit must return the sequence the resolver saved,
    // not storage order. The inserts are reversed and index scans disabled so
    // a plain heap scan surfaces the unordered rows.
    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn load_all_returns_parts_in_order(pool: sqlx::PgPool) {
        for statement in ["SET enable_indexscan = off", "SET enable_bitmapscan = off"] {
            sqlx::query(statement).execute(&pool).await.unwrap();
        }

        let raw_id = RawFrameId::new("raw-frame-id".to_string(), 0);
        for part in (0..8).rev() {
            let id = FrameId::new(raw_id.hash_id.clone(), raw_id.team_id, part);
            let frame = frame_with_part(id.clone(), part);
            ErrorTrackingStackFrame::new(id, None, frame, true, None)
                .save(&pool)
                .await
                .unwrap();
        }

        let policy = FrameResultTtlPolicy::new(Duration::minutes(30), Duration::minutes(5));
        let loaded = ErrorTrackingStackFrame::load_all(&pool, &raw_id, policy)
            .await
            .unwrap();

        let parts: Vec<i32> = loaded.iter().map(|record| record.id.part).collect();
        assert_eq!(parts, (0..8).collect::<Vec<i32>>());
    }

    // A refresh that misses a part, or fails to move created_at, leaves the snapshot
    // permanently stale and cymbal re-resolves the frame on every cache miss forever.
    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn refresh_created_at_restores_freshness_without_rewriting_contents(pool: sqlx::PgPool) {
        let raw_id = RawFrameId::new("raw-frame-id".to_string(), 0);
        let policy = FrameResultTtlPolicy::new(Duration::minutes(30), Duration::minutes(30));
        for part in 0..2 {
            let id = FrameId::new(raw_id.hash_id.clone(), raw_id.team_id, part);
            let frame = frame_with_part(id.clone(), part);
            let mut record = ErrorTrackingStackFrame::new(id, None, frame, true, None);
            record.created_at = Utc::now() - Duration::hours(2);
            record.save(&pool).await.unwrap();
        }

        let stale = ErrorTrackingStackFrame::load_snapshot(&pool, &raw_id, policy)
            .await
            .unwrap();
        assert!(!stale.fresh);

        let rows = ErrorTrackingStackFrame::refresh_created_at(&pool, &raw_id, Utc::now())
            .await
            .unwrap();
        assert_eq!(rows, 2);

        let refreshed = ErrorTrackingStackFrame::load_snapshot(&pool, &raw_id, policy)
            .await
            .unwrap();
        assert!(refreshed.fresh);
        assert_eq!(
            classify_frame_snapshot(&stale.records, &refreshed.records),
            FrameWriteOutcome::Unchanged
        );
    }

    // Without the guard, every racing writer that loaded the same stale snapshot
    // rewrites an identical row, creating a dead tuple and index churn per race.
    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn guarded_save_suppresses_noop_conflict_rewrites(pool: sqlx::PgPool) {
        let id = FrameId::new("raw-frame-id".to_string(), 0, 0);
        let frame = frame_with_part(id.clone(), 0);
        let record = ErrorTrackingStackFrame::new(id, None, frame, true, None);
        assert_eq!(record.save(&pool).await.unwrap(), 1);

        let threshold = Some(Utc::now() - Duration::minutes(10));

        let mut duplicate = record.clone();
        duplicate.created_at = Utc::now();
        assert_eq!(
            duplicate
                .save_with_refresh_guard(&pool, threshold)
                .await
                .unwrap(),
            0,
            "identical content on a fresh row is a server-side no-op"
        );

        assert_eq!(
            duplicate
                .save_with_refresh_guard(&pool, Some(Utc::now() + Duration::seconds(1)))
                .await
                .unwrap(),
            1,
            "identical content still refreshes a row older than the threshold"
        );

        let mut changed = record.clone();
        changed.resolved = false;
        assert_eq!(
            changed
                .save_with_refresh_guard(&pool, threshold)
                .await
                .unwrap(),
            1,
            "changed content always writes"
        );

        assert_eq!(
            record.save(&pool).await.unwrap(),
            1,
            "an unguarded save keeps the unconditional update"
        );
    }

    #[test]
    fn unchanged_snapshot_refreshes_only_past_half_ttl() {
        let policy = FrameResultTtlPolicy::new(Duration::seconds(1000), Duration::seconds(1000));
        let id = FrameId::new("raw-frame-id".to_string(), 1, 0);
        let frame = frame_with_part(id.clone(), 0);
        let mut record = ErrorTrackingStackFrame::new(id.clone(), None, frame, true, None);
        let raw_id = RawFrameId::new(id.hash_id.clone(), id.team_id);
        let now = Utc::now();

        // The jittered TTL falls in [1000s, 1100s], so the refresh boundary falls in
        // [500s, 550s]. Ages on either side of that band decide the same way for any
        // jitter value.
        record.created_at = now - Duration::seconds(499);
        assert!(!unchanged_snapshot_needs_refresh(
            &policy,
            &raw_id,
            std::slice::from_ref(&record),
            now,
        ));

        record.created_at = now - Duration::seconds(551);
        assert!(unchanged_snapshot_needs_refresh(
            &policy,
            &raw_id,
            std::slice::from_ref(&record),
            now,
        ));
    }

    #[test]
    fn durable_snapshot_classification_covers_every_persisted_field() {
        use crate::core::write_attribution::FrameWriteOutcome;

        let id = FrameId::new("raw-frame-id".to_string(), 1, 0);
        let frame = frame_with_part(id.clone(), 0);
        let existing = ErrorTrackingStackFrame::new(id, None, frame, true, None);
        let current = existing.clone();

        assert_eq!(
            classify_frame_snapshot(&[], std::slice::from_ref(&current)),
            FrameWriteOutcome::Insert
        );
        assert_eq!(
            classify_frame_snapshot(
                std::slice::from_ref(&existing),
                std::slice::from_ref(&current),
            ),
            FrameWriteOutcome::Unchanged
        );

        let mut changed_created_at = current.clone();
        changed_created_at.created_at += Duration::hours(1);
        assert_eq!(
            classify_frame_snapshot(
                std::slice::from_ref(&existing),
                std::slice::from_ref(&changed_created_at),
            ),
            FrameWriteOutcome::Unchanged,
            "created_at is an observation timestamp, not durable content"
        );

        let mut variants = Vec::new();

        let mut changed_contents = current.clone();
        changed_contents.contents.mangled_name = "different".to_string();
        variants.push(("contents", changed_contents));

        let mut changed_context = current.clone();
        changed_context.context = Some(Context {
            before: Vec::new(),
            line: crate::frames::ContextLine {
                number: 1,
                line: "changed".to_string(),
            },
            after: Vec::new(),
        });
        variants.push(("context", changed_context));

        let mut changed_resolved = current.clone();
        changed_resolved.resolved = false;
        variants.push(("resolved", changed_resolved));

        let mut changed_symbol_set = current.clone();
        changed_symbol_set.symbol_set_id = Some(Uuid::now_v7());
        variants.push(("symbol_set_id", changed_symbol_set));

        let mut changed_part = current;
        changed_part.id.part = 1;
        changed_part.contents.frame_id.part = 1;
        variants.push(("ordered parts", changed_part));

        for (field, changed) in variants {
            assert_eq!(
                classify_frame_snapshot(std::slice::from_ref(&existing), &[changed]),
                FrameWriteOutcome::Changed,
                "{field}"
            );
        }
    }

    #[test]
    fn ttl_policy_applies_expected_ttl_with_deterministic_jitter() {
        for (name, resolved_ttl, unresolved_ttl, all_resolved, min_ttl, max_ttl) in [
            (
                "resolved",
                Duration::seconds(1800),
                Duration::seconds(300),
                true,
                Duration::seconds(1800),
                Duration::seconds(1980),
            ),
            (
                "unresolved",
                Duration::seconds(1800),
                Duration::seconds(300),
                false,
                Duration::seconds(300),
                Duration::seconds(330),
            ),
            (
                "deterministic jitter",
                Duration::seconds(100),
                Duration::seconds(100),
                true,
                Duration::seconds(100),
                Duration::seconds(110),
            ),
        ] {
            let policy = FrameResultTtlPolicy::new(resolved_ttl, unresolved_ttl);
            let id = RawFrameId::new("frame".to_string(), 1);

            let ttl = policy.ttl_for_resolved_status(&id, all_resolved);

            assert_eq!(
                ttl,
                policy.ttl_for_resolved_status(&id, all_resolved),
                "{name}"
            );
            assert!(ttl >= min_ttl, "{name}");
            assert!(ttl <= max_ttl, "{name}");
        }
    }
}
