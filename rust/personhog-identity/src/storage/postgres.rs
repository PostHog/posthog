use std::collections::{HashMap, HashSet};

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use sqlx::postgres::PgPool;
use uuid::Uuid;

use personhog_common::grpc::{current_client_name, current_method_name};
use personhog_common::persons::person_uuid;

use crate::storage::error::StorageResult;
use crate::storage::types::{Person, PersonStub, StubOutcome};
use crate::storage::{IdentityStorage, DB_QUERY_DURATION};

const POOL_LABEL: &str = "primary";

pub struct PostgresIdentityStorage {
    pub primary_pool: PgPool,
}

impl PostgresIdentityStorage {
    pub fn new(primary_pool: PgPool) -> Self {
        Self { primary_pool }
    }

    fn query_labels(operation: &str) -> [(String, String); 4] {
        [
            ("operation".to_string(), operation.to_string()),
            ("pool".to_string(), POOL_LABEL.to_string()),
            ("client".to_string(), current_client_name().to_string()),
            ("method".to_string(), current_method_name().to_string()),
        ]
    }
}

#[async_trait]
impl IdentityStorage for PostgresIdentityStorage {
    async fn resolve_distinct_ids(
        &self,
        keys: &[(i64, String)],
    ) -> StorageResult<HashMap<(i64, String), Person>> {
        if keys.is_empty() {
            return Ok(HashMap::new());
        }

        let labels = Self::query_labels("resolve_distinct_ids");
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let team_ids: Vec<i32> = keys.iter().map(|(t, _)| *t as i32).collect();
        let distinct_ids: Vec<String> = keys.iter().map(|(_, d)| d.clone()).collect();

        let rows = sqlx::query!(
            r#"
            SELECT k.team_id as "key_team_id!", k.distinct_id as "key_distinct_id!",
                   p.id as "id!", p.uuid as "uuid!", p.team_id::bigint as "team_id!",
                   p.properties::text as "properties?",
                   p.properties_last_updated_at::text as "properties_last_updated_at?",
                   p.properties_last_operation::text as "properties_last_operation?",
                   p.created_at as "created_at!", p.version, p.is_identified as "is_identified!",
                   CASE WHEN p.is_user_id IS NULL THEN NULL ELSE (p.is_user_id != 0) END as is_user_id,
                   p.last_seen_at
            FROM unnest($1::int[], $2::text[]) AS k(team_id, distinct_id)
            JOIN posthog_persondistinctid pdi
              ON pdi.team_id = k.team_id AND pdi.distinct_id = k.distinct_id
            JOIN posthog_person p
              ON p.team_id = pdi.team_id AND p.id = pdi.person_id
            "#,
            &team_ids,
            &distinct_ids
        )
        .fetch_all(&self.primary_pool)
        .await?;

        let mut resolved = HashMap::with_capacity(rows.len());
        for row in rows {
            resolved.insert(
                (i64::from(row.key_team_id), row.key_distinct_id),
                Person {
                    id: row.id,
                    uuid: row.uuid,
                    team_id: row.team_id,
                    properties: row.properties,
                    properties_last_updated_at: row.properties_last_updated_at,
                    properties_last_operation: row.properties_last_operation,
                    created_at: row.created_at,
                    version: row.version,
                    is_identified: row.is_identified,
                    is_user_id: row.is_user_id,
                    last_seen_at: row.last_seen_at,
                },
            );
        }
        Ok(resolved)
    }

    async fn create_person_stubs(&self, stubs: &[PersonStub]) -> StorageResult<Vec<StubOutcome>> {
        if stubs.is_empty() {
            return Ok(Vec::new());
        }

        let labels = Self::query_labels("create_person_stubs");
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let uuids: Vec<Uuid> = stubs
            .iter()
            .map(|s| person_uuid(s.team_id, &s.distinct_id))
            .collect();
        let team_ids: Vec<i32> = stubs.iter().map(|s| s.team_id as i32).collect();
        let created_ats: Vec<DateTime<Utc>> = stubs.iter().map(|s| s.created_at).collect();
        let is_identified: Vec<bool> = stubs.iter().map(|s| s.is_identified).collect();

        let mut tx = self.primary_pool.begin().await?;

        // 1. Multi-row stub insert. Concurrent creates for one distinct id
        // derive the same uuid, so exactly one insert wins per key; losers
        // fetch the committed winner in a fresh statement snapshot below.
        let inserted = sqlx::query_as!(
            Person,
            r#"
            INSERT INTO posthog_person
                (created_at, properties, properties_last_updated_at, properties_last_operation,
                 team_id, is_identified, uuid, version, last_seen_at)
            SELECT u.created_at, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                   u.team_id, u.is_identified, u.uuid, 0, date_trunc('hour', u.created_at)
            FROM unnest($1::timestamptz[], $2::int[], $3::bool[], $4::uuid[])
                AS u(created_at, team_id, is_identified, uuid)
            ON CONFLICT (team_id, uuid) DO NOTHING
            RETURNING id, uuid, team_id::bigint as "team_id!", properties::text as "properties?",
                      properties_last_updated_at::text as "properties_last_updated_at?",
                      properties_last_operation::text as "properties_last_operation?",
                      created_at, version, is_identified,
                      CASE WHEN is_user_id IS NULL THEN NULL ELSE (is_user_id != 0) END as is_user_id,
                      last_seen_at
            "#,
            &created_ats,
            &team_ids,
            &is_identified,
            &uuids
        )
        .fetch_all(&mut *tx)
        .await?;

        // (team_id, uuid) → (person, created-by-us)
        let mut persons: HashMap<(i64, Uuid), (Person, bool)> = inserted
            .into_iter()
            .map(|p| ((p.team_id, p.uuid), (p, true)))
            .collect();

        // 2. Batch-fetch the committed winners for conflicted keys. This must
        // be a separate statement: the insert's snapshot predates a concurrent
        // winner's commit, a fresh statement snapshot sees it.
        let conflicted: Vec<usize> = (0..stubs.len())
            .filter(|&i| !persons.contains_key(&(stubs[i].team_id, uuids[i])))
            .collect();
        if !conflicted.is_empty() {
            let conflicted_teams: Vec<i32> = conflicted.iter().map(|&i| team_ids[i]).collect();
            let conflicted_uuids: Vec<Uuid> = conflicted.iter().map(|&i| uuids[i]).collect();
            let winners = sqlx::query_as!(
                Person,
                r#"
                SELECT p.id as "id!", p.uuid as "uuid!", p.team_id::bigint as "team_id!",
                       p.properties::text as "properties?",
                       p.properties_last_updated_at::text as "properties_last_updated_at?",
                       p.properties_last_operation::text as "properties_last_operation?",
                       p.created_at as "created_at!", p.version, p.is_identified as "is_identified!",
                       CASE WHEN p.is_user_id IS NULL THEN NULL ELSE (p.is_user_id != 0) END as is_user_id,
                       p.last_seen_at
                FROM posthog_person p
                JOIN unnest($1::int[], $2::uuid[]) AS k(team_id, uuid)
                  ON p.team_id = k.team_id AND p.uuid = k.uuid
                "#,
                &conflicted_teams,
                &conflicted_uuids
            )
            .fetch_all(&mut *tx)
            .await?;
            for winner in winners {
                persons.insert((winner.team_id, winner.uuid), (winner, false));
            }
        }

        // 3. Extra distinct ids carry personless history forward: a distinct
        // id already used personless needs its row at version 1 so ClickHouse
        // emits an override re-pointing those events. The upsert also marks
        // the personless row merged so concurrent personless events re-resolve.
        // Deduped across stubs — DO UPDATE errors on same-command duplicates.
        let mut personless_seen: HashSet<(i64, &str)> = HashSet::new();
        let mut personless_teams: Vec<i32> = Vec::new();
        let mut personless_dids: Vec<String> = Vec::new();
        for stub in stubs {
            for extra in &stub.extra_distinct_ids {
                if personless_seen.insert((stub.team_id, extra.as_str())) {
                    personless_teams.push(stub.team_id as i32);
                    personless_dids.push(extra.clone());
                }
            }
        }
        let mut personless_fresh: HashMap<(i64, String), bool> = HashMap::new();
        if !personless_dids.is_empty() {
            let rows = sqlx::query!(
                r#"
                INSERT INTO posthog_personlessdistinctid (distinct_id, is_merged, created_at, team_id)
                SELECT d, true, now(), t FROM unnest($1::int[], $2::text[]) AS u(t, d)
                ON CONFLICT (team_id, distinct_id) DO UPDATE SET is_merged = true
                RETURNING team_id::bigint as "team_id!", distinct_id, (xmax = 0) as "inserted!"
                "#,
                &personless_teams,
                &personless_dids
            )
            .fetch_all(&mut *tx)
            .await?;
            for row in rows {
                personless_fresh.insert((row.team_id, row.distinct_id), row.inserted);
            }
        }

        // 4. Multi-row distinct id insert. The primary distinct id derives the
        // person uuid, so personless events already used the same uuid —
        // always version 0. Conflicts keep the existing mapping (per-row).
        let mut pdi_dids: Vec<String> = Vec::new();
        let mut pdi_person_ids: Vec<i64> = Vec::new();
        let mut pdi_teams: Vec<i32> = Vec::new();
        let mut pdi_versions: Vec<i64> = Vec::new();
        for (i, stub) in stubs.iter().enumerate() {
            let Some((person, _)) = persons.get(&(stub.team_id, uuids[i])) else {
                continue; // winner vanished; resolved to LostRace below
            };
            pdi_dids.push(stub.distinct_id.clone());
            pdi_person_ids.push(person.id);
            pdi_teams.push(stub.team_id as i32);
            pdi_versions.push(0);
            for extra in &stub.extra_distinct_ids {
                let fresh = personless_fresh
                    .get(&(stub.team_id, extra.clone()))
                    .copied()
                    .unwrap_or(true);
                pdi_dids.push(extra.clone());
                pdi_person_ids.push(person.id);
                pdi_teams.push(stub.team_id as i32);
                pdi_versions.push(if fresh { 0 } else { 1 });
            }
        }
        let mut mapped: HashMap<(i64, String), i64> = HashMap::new();
        if !pdi_dids.is_empty() {
            let rows = sqlx::query!(
                r#"
                INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
                SELECT d, p, t, v FROM unnest($1::text[], $2::bigint[], $3::int[], $4::bigint[])
                    AS u(d, p, t, v)
                ON CONFLICT (team_id, distinct_id) DO NOTHING
                RETURNING team_id::bigint as "team_id!", distinct_id, person_id
                "#,
                &pdi_dids,
                &pdi_person_ids,
                &pdi_teams,
                &pdi_versions
            )
            .fetch_all(&mut *tx)
            .await?;
            for row in rows {
                mapped.insert((row.team_id, row.distinct_id), row.person_id);
            }
        }

        // 5. Per-stub outcomes. A stub whose primary mapping went elsewhere is
        // a lost race: undo its rows (created this transaction, so nothing can
        // reference them) so the stub doesn't linger orphaned.
        let mut outcomes = Vec::with_capacity(stubs.len());
        for (i, stub) in stubs.iter().enumerate() {
            let Some((person, created)) = persons.get(&(stub.team_id, uuids[i])) else {
                outcomes.push(StubOutcome::LostRace);
                continue;
            };
            let primary_key = (stub.team_id, stub.distinct_id.clone());
            if mapped.get(&primary_key) == Some(&person.id) {
                outcomes.push(StubOutcome::Committed {
                    person: person.clone(),
                    created: *created,
                });
                continue;
            }
            if *created {
                sqlx::query!(
                    "DELETE FROM posthog_persondistinctid WHERE team_id = $1 AND person_id = $2",
                    stub.team_id as i32,
                    person.id
                )
                .execute(&mut *tx)
                .await?;
                sqlx::query!(
                    "DELETE FROM posthog_person WHERE team_id = $1 AND id = $2",
                    stub.team_id as i32,
                    person.id
                )
                .execute(&mut *tx)
                .await?;
                outcomes.push(StubOutcome::LostRace);
                continue;
            }
            // The person pre-existed and its primary mapping wasn't inserted by
            // us — verify the existing mapping points at this person.
            let existing = sqlx::query_scalar!(
                "SELECT person_id FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2",
                stub.team_id as i32,
                &stub.distinct_id
            )
            .fetch_optional(&mut *tx)
            .await?;
            if existing == Some(person.id) {
                outcomes.push(StubOutcome::Committed {
                    person: person.clone(),
                    created: false,
                });
            } else {
                outcomes.push(StubOutcome::LostRace);
            }
        }

        tx.commit().await?;
        Ok(outcomes)
    }
}
