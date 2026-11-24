//! Attach personless distinct ids to an existing person with plain mapping
//! inserts — the personless-source merge case, settled inline with no saga.

use std::collections::HashMap;

use sqlx::Row;

use crate::config::{IdentityTables, OutboxWrites};
use crate::pools::{IdentityPools, Lane};
use crate::storage::error::StorageResult;
use crate::storage::types::{AttachOutcome, PersonAttach};
use personhog_common::query_tag;

/// Fresh inserts get version 1, like a stub's extra distinct ids: with no
/// personless table there is no proof the id never sent events, and 1 is
/// safe either way. Tombstoned mappings revive (repoint + version bump);
/// live mappings are never repointed — that would be a silent merge.
/// Callers dedupe; sorted insert order keeps row locks deadlock-free.
///
/// Two guards keep a racing lifecycle op from acquiring a mapping it can
/// no longer sweep: the join rejects committed deletions, and the mark
/// check rejects persons held by a live op. The rare statement that slips
/// both leaves an orphaned mapping the next resolve treats as absent.
///
/// With outbox writes on, the same statement also queues one publish
/// outbox row per mapping it wrote, through a data-modifying CTE, so the
/// mapping and its row commit together without a transaction.
pub(super) async fn attach_distinct_ids(
    pools: &IdentityPools,
    tables: &IdentityTables,
    team_id: i64,
    person_id: i64,
    distinct_ids: &[String],
    outbox_writes: OutboxWrites,
) -> StorageResult<HashMap<String, AttachOutcome>> {
    if distinct_ids.is_empty() {
        return Ok(HashMap::new());
    }
    let mut sorted: Vec<String> = distinct_ids.to_vec();
    sorted.sort_unstable();

    let insert = format!(
        r#"
        INSERT INTO {pdi} (distinct_id, person_id, team_id, version)
        SELECT u.d, p.id, p.team_id, 1
        FROM unnest($1::text[]) AS u(d)
        JOIN {person} p
          ON p.team_id = $3 AND p.id = $2 AND p.is_deleted = false
        WHERE NOT EXISTS (
            SELECT 1 FROM {lop} m
            WHERE m.team_id = p.team_id AND m.person_id = p.id
              AND m.mark_active
        )
        ON CONFLICT (team_id, distinct_id) DO UPDATE SET
            person_id = EXCLUDED.person_id,
            version = COALESCE({pdi}.version, 0) + 1,
            is_deleted = false
            WHERE {pdi}.is_deleted = true
        RETURNING distinct_id, version
        "#,
        pdi = tables.person_distinct_id,
        person = tables.person,
        lop = tables.lifecycle_op_person,
    );
    let insert_sql = match outbox_writes {
        OutboxWrites::Enabled => format!(
            r#"
            WITH written AS ({insert}),
            queued AS (
                INSERT INTO {outbox} (team_id, kind, person_uuid, distinct_id, version)
                SELECT $3, 'attach', p.uuid, w.distinct_id, w.version
                FROM written w
                JOIN {person} p ON p.team_id = $3 AND p.id = $2
            )
            SELECT distinct_id, version FROM written
            "#,
            outbox = tables.person_publish_outbox,
            person = tables.person,
        ),
        OutboxWrites::Disabled => insert,
    };
    let mut conn = pools.acquire(Lane::Heavy).await?;
    // Tagged apart so the statement that also writes the outbox is
    // attributable on its own in query statistics.
    let tagged = match outbox_writes {
        OutboxWrites::Enabled => query_tag!("attach_mappings_with_outbox", insert_sql),
        OutboxWrites::Disabled => query_tag!("attach_mappings", insert_sql),
    };
    let written = sqlx::query(&tagged)
        .bind(&sorted)
        .bind(person_id)
        .bind(team_id as i32)
        .fetch_all(&mut *conn)
        .await?;

    let mut outcomes: HashMap<String, AttachOutcome> = HashMap::new();
    for row in written {
        let distinct_id: String = row.try_get("distinct_id")?;
        let version: i64 = row.try_get("version")?;
        outcomes.insert(distinct_id, AttachOutcome::Attached { version });
    }

    let losers: Vec<String> = sorted
        .iter()
        .filter(|d| !outcomes.contains_key(*d))
        .cloned()
        .collect();
    if losers.is_empty() {
        return Ok(outcomes);
    }
    // Fresh statement snapshot: the insert's snapshot may predate a
    // concurrent winner's commit.
    let losers_sql = format!(
        r#"
        SELECT distinct_id, person_id
        FROM {pdi}
        WHERE team_id = $1 AND distinct_id = ANY($2) AND is_deleted = false
        "#,
        pdi = tables.person_distinct_id,
    );
    let rows = sqlx::query(&query_tag!("attach_losers", losers_sql))
        .bind(team_id as i32)
        .bind(&losers)
        .fetch_all(&mut *conn)
        .await?;
    for row in rows {
        let distinct_id: String = row.try_get("distinct_id")?;
        let mapped_person_id: i64 = row.try_get("person_id")?;
        outcomes.insert(
            distinct_id,
            AttachOutcome::AlreadyMapped {
                person_id: mapped_person_id,
            },
        );
    }
    Ok(outcomes)
}

/// Bounds one lock wait and the whole statement. Every row's guards read the
/// statement's start snapshot, so a long wait lets a delete saga destroy
/// another call's person before its mapping is written. A batch that times
/// out reruns each call alone.
const SET_BATCH_TIMEOUTS: &str = "SELECT set_config('lock_timeout', '100ms', true), \
     set_config('statement_timeout', '250ms', true)";

/// [`attach_distinct_ids`] for several persons in one statement. A batch of
/// one takes the single-person statement, which plans faster.
pub(super) async fn attach_batch(
    pools: &IdentityPools,
    tables: &IdentityTables,
    attaches: &[PersonAttach],
    outbox_writes: OutboxWrites,
) -> StorageResult<Vec<HashMap<String, AttachOutcome>>> {
    if let [attach] = attaches {
        let outcomes = attach_distinct_ids(
            pools,
            tables,
            attach.team_id,
            attach.person_id,
            &attach.distinct_ids,
            outbox_writes,
        )
        .await?;
        return Ok(vec![outcomes]);
    }
    let mut team_ids: Vec<i32> = Vec::new();
    let mut person_ids: Vec<i64> = Vec::new();
    let mut distinct_ids: Vec<&str> = Vec::new();
    for attach in attaches {
        for distinct_id in &attach.distinct_ids {
            team_ids.push(attach.team_id as i32);
            person_ids.push(attach.person_id);
            distinct_ids.push(distinct_id);
        }
    }
    if distinct_ids.is_empty() {
        return Ok(vec![HashMap::new(); attaches.len()]);
    }

    // `p.team_id = ANY($1)` prunes person partitions to the batch's teams.
    // The `ANY` bounds on the mark check keep the planner's hash anti join to
    // the batch's persons instead of every active mark. The ORDER BY makes
    // concurrent statements lock mapping rows in one order; "C" is byte
    // order, as `attach_distinct_ids` sorts.
    let insert = format!(
        r#"
        INSERT INTO {pdi} (distinct_id, person_id, team_id, version)
        SELECT u.distinct_id, p.id, p.team_id, 1
        FROM unnest($1::int[], $2::bigint[], $3::text[]) AS u(team_id, person_id, distinct_id)
        JOIN {person} p
          ON p.team_id = u.team_id AND p.id = u.person_id
         AND p.team_id = ANY($1::int[]) AND p.is_deleted = false
        WHERE NOT EXISTS (
            SELECT 1 FROM {lop} m
            WHERE m.team_id = p.team_id AND m.person_id = p.id
              AND m.mark_active
              AND m.team_id = ANY($1::int[]) AND m.person_id = ANY($2::bigint[])
        )
        ORDER BY u.team_id, u.distinct_id COLLATE "C"
        ON CONFLICT (team_id, distinct_id) DO UPDATE SET
            person_id = EXCLUDED.person_id,
            version = COALESCE({pdi}.version, 0) + 1,
            is_deleted = false
            WHERE {pdi}.is_deleted = true
        RETURNING team_id, person_id, distinct_id, version
        "#,
        pdi = tables.person_distinct_id,
        person = tables.person,
        lop = tables.lifecycle_op_person,
    );
    let tagged = match outbox_writes {
        OutboxWrites::Enabled => {
            let with_outbox = format!(
                r#"
                WITH written AS ({insert}),
                queued AS (
                    INSERT INTO {outbox} (team_id, kind, person_uuid, distinct_id, version)
                    SELECT w.team_id, 'attach', p.uuid, w.distinct_id, w.version
                    FROM written w
                    JOIN {person} p
                      ON p.team_id = w.team_id AND p.id = w.person_id
                     AND p.team_id = ANY($1::int[])
                )
                SELECT team_id, person_id, distinct_id, version FROM written
                "#,
                outbox = tables.person_publish_outbox,
                person = tables.person,
            );
            query_tag!("attach_batch_mappings_with_outbox", with_outbox)
        }
        OutboxWrites::Disabled => query_tag!("attach_batch_mappings", insert),
    };
    let mut conn = pools.acquire(Lane::Heavy).await?;
    let mut tx = sqlx::Connection::begin(&mut *conn).await?;
    sqlx::query(&query_tag!("attach_batch_timeouts", SET_BATCH_TIMEOUTS))
        .execute(&mut *tx)
        .await?;
    let rows = sqlx::query(&tagged)
        .bind(&team_ids)
        .bind(&person_ids)
        .bind(&distinct_ids)
        .fetch_all(&mut *tx)
        .await?;
    tx.commit().await?;
    let mut written: HashMap<(i64, String), (i64, i64)> = HashMap::with_capacity(rows.len());
    for row in rows {
        let team_id: i32 = row.try_get("team_id")?;
        let distinct_id: String = row.try_get("distinct_id")?;
        let person_id: i64 = row.try_get("person_id")?;
        let version: i64 = row.try_get("version")?;
        written.insert((i64::from(team_id), distinct_id), (person_id, version));
    }

    let (loser_team_ids, loser_distinct_ids): (Vec<i32>, Vec<&str>) = team_ids
        .iter()
        .zip(&distinct_ids)
        .filter(|(team_id, distinct_id)| {
            !written.contains_key(&(i64::from(**team_id), distinct_id.to_string()))
        })
        .map(|(team_id, distinct_id)| (*team_id, *distinct_id))
        .unzip();
    let mut already_mapped: HashMap<(i64, String), i64> = HashMap::new();
    if !loser_distinct_ids.is_empty() {
        let losers_sql = format!(
            r#"
            SELECT k.team_id, k.distinct_id, pdi.person_id
            FROM unnest($1::int[], $2::text[]) AS k(team_id, distinct_id)
            JOIN {pdi} pdi
              ON pdi.team_id = k.team_id AND pdi.distinct_id = k.distinct_id
             AND pdi.is_deleted = false
            "#,
            pdi = tables.person_distinct_id,
        );
        let rows = sqlx::query(&query_tag!("attach_batch_losers", losers_sql))
            .bind(&loser_team_ids)
            .bind(&loser_distinct_ids)
            .fetch_all(&mut *conn)
            .await?;
        for row in rows {
            let team_id: i32 = row.try_get("team_id")?;
            let distinct_id: String = row.try_get("distinct_id")?;
            let person_id: i64 = row.try_get("person_id")?;
            already_mapped.insert((i64::from(team_id), distinct_id), person_id);
        }
    }

    // A written row counts as attached only for the person it names, so an
    // outcome can never reach another attach of the same key.
    Ok(attaches
        .iter()
        .map(|attach| {
            attach
                .distinct_ids
                .iter()
                .filter_map(|distinct_id| {
                    let key = (attach.team_id, distinct_id.clone());
                    let outcome = match (written.get(&key), already_mapped.get(&key)) {
                        (Some(&(person_id, version)), _) if person_id == attach.person_id => {
                            AttachOutcome::Attached { version }
                        }
                        (Some(&(person_id, _)), _) | (None, Some(&person_id)) => {
                            AttachOutcome::AlreadyMapped { person_id }
                        }
                        (None, None) => return None,
                    };
                    Some((distinct_id.clone(), outcome))
                })
                .collect()
        })
        .collect())
}
