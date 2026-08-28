//! The stub-creation transaction: one transaction, four steps, each a
//! function below, called in order by [`create_person_stubs`]:
//!
//! 1. [`insert_or_revive_persons`] — multi-row person insert; a conflict
//!    with a tombstoned row revives it, a conflict with a live row is left
//!    for step 2.
//! 2. [`fetch_conflict_winners`] — fresh-snapshot fetch of the committed
//!    rows behind live conflicts (concurrent winners).
//! 3. [`insert_distinct_id_mappings`] — multi-row distinct id insert;
//!    tombstoned mappings revive, live conflicts keep the existing row.
//! 4. [`resolve_stub_outcomes`] — decide Committed/LostRace per stub and
//!    undo the rows of stubs that lost their primary mapping.
//!
//! Cross-cutting invariants:
//! - Every multi-row statement binds arrays sorted by its conflict key —
//!   row locks are taken in array order, so concurrent batches touching the
//!   same keys in different orders would otherwise deadlock — and deduped by
//!   that key, because ON CONFLICT DO UPDATE raises "cannot affect row a
//!   second time" on same-command duplicates (the cardinality check fires
//!   before the WHERE qual).
//! - Rows created in this transaction are invisible outside it until commit,
//!   so step 5 can delete them without anything referencing them.
//! - Revived tombstones predate the transaction and must survive an undo:
//!   they are re-tombstoned with another version bump, never deleted.

use std::collections::{HashMap, HashSet};

use chrono::{DateTime, Utc};
use sqlx::postgres::PgPool;
use sqlx::Row;
use uuid::Uuid;

use personhog_common::persons::person_uuid;

use crate::config::IdentityTables;
use crate::storage::error::StorageResult;
use crate::storage::postgres::{person_columns, person_from_row};
use crate::storage::types::{Person, PersonStub, StubOutcome};

type Tx<'a> = sqlx::Transaction<'a, sqlx::Postgres>;

/// A person resolved for one (team_id, uuid) conflict key during stub
/// creation, plus how this transaction obtained it — that determines the
/// stub's reported `created` flag and how an undo must treat the row.
struct ResolvedPerson {
    person: Person,
    /// Inserted (or revived) by this transaction, as opposed to fetched as a
    /// concurrent winner's committed row.
    created_by_us: bool,
    /// The insert revived a tombstoned row rather than creating a fresh one.
    /// An undo must re-tombstone it, never hard-delete it.
    revived_tombstone: bool,
}

/// Persons keyed by their (team_id, uuid) conflict key.
type PersonsByKey = HashMap<(i64, Uuid), ResolvedPerson>;

/// What the multi-row distinct id insert actually wrote.
struct MappingOutcome {
    /// (team_id, distinct_id) → person_id for each mapping this transaction
    /// inserted or revived. Keys that conflicted with a live mapping are
    /// absent — the existing mapping stands.
    written: HashMap<(i64, String), i64>,
    /// The subset of `written` that revived a tombstoned mapping; an undo
    /// must re-tombstone these instead of deleting them.
    revived: HashSet<(i64, String)>,
}

pub(super) async fn create_person_stubs(
    pool: &PgPool,
    tables: &IdentityTables,
    stubs: &[PersonStub],
) -> StorageResult<Vec<StubOutcome>> {
    if stubs.is_empty() {
        return Ok(Vec::new());
    }

    // The primary distinct id derives the person uuid, so concurrent creates
    // for one distinct id target the same (team_id, uuid) row.
    let uuids: Vec<Uuid> = stubs
        .iter()
        .map(|s| person_uuid(s.team_id, &s.distinct_id))
        .collect();
    let team_ids: Vec<i32> = stubs.iter().map(|s| s.team_id as i32).collect();

    let mut tx = pool.begin().await?;

    let mut persons =
        insert_or_revive_persons(&mut tx, &tables.person, stubs, &team_ids, &uuids).await?;
    fetch_conflict_winners(
        &mut tx,
        &tables.person,
        stubs,
        &team_ids,
        &uuids,
        &mut persons,
    )
    .await?;
    let mapping =
        insert_distinct_id_mappings(&mut tx, &tables.person_distinct_id, stubs, &uuids, &persons)
            .await?;
    let outcomes =
        resolve_stub_outcomes(&mut tx, tables, stubs, &uuids, &persons, &mapping).await?;

    tx.commit().await?;
    Ok(outcomes)
}

/// Step 1: multi-row stub insert. Concurrent creates for one distinct id
/// derive the same uuid, so exactly one insert wins per key; losers fetch
/// the committed winner in a fresh statement snapshot (step 2).
///
/// A conflict with a tombstoned row (same uuidv5 key, previously deleted) is
/// a revival: flip is_deleted, bump the version above the tombstone so
/// ClickHouse collapses toward the new incarnation, and reset properties.
/// Conflicts with live rows fail the WHERE qual and return nothing here.
///
/// A returned version of 0 means fresh insert, anything else means revival
/// (xmax can't be read back from a partitioned table).
async fn insert_or_revive_persons(
    tx: &mut Tx<'_>,
    person_table: &str,
    stubs: &[PersonStub],
    team_ids: &[i32],
    uuids: &[Uuid],
) -> StorageResult<PersonsByKey> {
    // Sorted and deduped by the (team_id, uuid) conflict key — see the
    // module invariants.
    let mut order: Vec<usize> = (0..stubs.len()).collect();
    order.sort_by_key(|&i| (team_ids[i], uuids[i]));
    order.dedup_by_key(|&mut i| (team_ids[i], uuids[i]));
    let sorted_created_ats: Vec<DateTime<Utc>> =
        order.iter().map(|&i| stubs[i].created_at).collect();
    let sorted_team_ids: Vec<i32> = order.iter().map(|&i| team_ids[i]).collect();
    let sorted_is_identified: Vec<bool> = order.iter().map(|&i| stubs[i].is_identified).collect();
    let sorted_uuids: Vec<Uuid> = order.iter().map(|&i| uuids[i]).collect();

    let sql = format!(
        r#"
        INSERT INTO {person_table}
            (created_at, properties, properties_last_updated_at, properties_last_operation,
             team_id, is_identified, uuid, version, last_seen_at)
        SELECT u.created_at, '{{}}'::jsonb, '{{}}'::jsonb, '{{}}'::jsonb,
               u.team_id, u.is_identified, u.uuid, 0, date_trunc('hour', u.created_at)
        FROM unnest($1::timestamptz[], $2::int[], $3::bool[], $4::uuid[])
            AS u(created_at, team_id, is_identified, uuid)
        ON CONFLICT (team_id, uuid) DO UPDATE SET
            is_deleted = false,
            version = COALESCE({person_table}.version, 0) + 1,
            properties = '{{}}'::jsonb,
            properties_last_updated_at = '{{}}'::jsonb,
            properties_last_operation = '{{}}'::jsonb,
            created_at = EXCLUDED.created_at,
            is_identified = EXCLUDED.is_identified,
            last_seen_at = EXCLUDED.last_seen_at
            WHERE {person_table}.is_deleted = true
        RETURNING {person_cols}
        "#,
        person_cols = person_columns(person_table),
    );
    let inserted = sqlx::query(&sql)
        .bind(&sorted_created_ats)
        .bind(&sorted_team_ids)
        .bind(&sorted_is_identified)
        .bind(&sorted_uuids)
        .fetch_all(&mut **tx)
        .await?;

    let mut persons = PersonsByKey::with_capacity(inserted.len());
    for row in inserted {
        let person = person_from_row(&row)?;
        let revived_tombstone = person.version != Some(0);
        persons.insert(
            (person.team_id, person.uuid),
            ResolvedPerson {
                person,
                created_by_us: true,
                revived_tombstone,
            },
        );
    }
    Ok(persons)
}

/// Step 2: batch-fetch the committed winners for conflicted keys. This must
/// be a separate statement: the insert's snapshot predates a concurrent
/// winner's commit, a fresh statement snapshot sees it.
async fn fetch_conflict_winners(
    tx: &mut Tx<'_>,
    person_table: &str,
    stubs: &[PersonStub],
    team_ids: &[i32],
    uuids: &[Uuid],
    persons: &mut PersonsByKey,
) -> StorageResult<()> {
    let conflicted: Vec<usize> = (0..stubs.len())
        .filter(|&i| !persons.contains_key(&(stubs[i].team_id, uuids[i])))
        .collect();
    if conflicted.is_empty() {
        return Ok(());
    }

    let conflicted_teams: Vec<i32> = conflicted.iter().map(|&i| team_ids[i]).collect();
    let conflicted_uuids: Vec<Uuid> = conflicted.iter().map(|&i| uuids[i]).collect();
    let sql = format!(
        r#"
        SELECT {person_cols}
        FROM {person_table} p
        JOIN unnest($1::int[], $2::uuid[]) AS k(team_id, uuid)
          ON p.team_id = k.team_id AND p.uuid = k.uuid
        WHERE p.is_deleted = false
        "#,
        person_cols = person_columns("p"),
    );
    let winners = sqlx::query(&sql)
        .bind(&conflicted_teams)
        .bind(&conflicted_uuids)
        .fetch_all(&mut **tx)
        .await?;
    for row in winners {
        let winner = person_from_row(&row)?;
        persons.insert(
            (winner.team_id, winner.uuid),
            ResolvedPerson {
                person: winner,
                created_by_us: false,
                revived_tombstone: false,
            },
        );
    }
    Ok(())
}

/// Step 3: multi-row distinct id insert. The primary distinct id derives the
/// person uuid, so any events it sent before the person existed already used
/// the same uuid — always version 0. Extras always get version 1: without
/// the personless table there is no proof the distinct id never sent events,
/// and version 1 is safe either way (the override it emits is a transient
/// no-op when no events exist).
///
/// A conflict with a tombstoned mapping is a revival: repoint it at the new
/// person and bump the version above the tombstone. Conflicts with live
/// mappings keep the existing row (per-row): an extra that raced into
/// another person's hands is a merge scenario, which is the pipeline's job —
/// never re-pointed here, and not an error (a retry could never succeed).
async fn insert_distinct_id_mappings(
    tx: &mut Tx<'_>,
    pdi_table: &str,
    stubs: &[PersonStub],
    uuids: &[Uuid],
    persons: &PersonsByKey,
) -> StorageResult<MappingOutcome> {
    // (team_id, distinct_id, person_id, version)
    let mut pdi_rows: Vec<(i32, String, i64, i64)> = Vec::new();
    for (i, stub) in stubs.iter().enumerate() {
        let Some(resolved) = persons.get(&(stub.team_id, uuids[i])) else {
            continue; // winner vanished; resolved to LostRace in step 4
        };
        pdi_rows.push((
            stub.team_id as i32,
            stub.distinct_id.clone(),
            resolved.person.id,
            0,
        ));
        for extra in &stub.extra_distinct_ids {
            pdi_rows.push((stub.team_id as i32, extra.clone(), resolved.person.id, 1));
        }
    }
    // Stable sort + dedup: batch order picks the winner among duplicate keys
    // (an extra shared between stubs), and the dedup keeps ON CONFLICT DO
    // UPDATE from affecting one row twice in the same command.
    pdi_rows.sort_by(|a, b| (a.0, &a.1).cmp(&(b.0, &b.1)));
    pdi_rows.dedup_by(|a, b| (a.0, &a.1) == (b.0, &b.1));
    let pdi_teams: Vec<i32> = pdi_rows.iter().map(|r| r.0).collect();
    let pdi_dids: Vec<String> = pdi_rows.iter().map(|r| r.1.clone()).collect();
    let pdi_person_ids: Vec<i64> = pdi_rows.iter().map(|r| r.2).collect();
    let pdi_versions: Vec<i64> = pdi_rows.iter().map(|r| r.3).collect();

    let mut mapping = MappingOutcome {
        written: HashMap::new(),
        revived: HashSet::new(),
    };
    if pdi_dids.is_empty() {
        return Ok(mapping);
    }

    let sql = format!(
        r#"
        INSERT INTO {pdi_table} (distinct_id, person_id, team_id, version)
        SELECT d, p, t, v FROM unnest($1::text[], $2::bigint[], $3::int[], $4::bigint[])
            AS u(d, p, t, v)
        ON CONFLICT (team_id, distinct_id) DO UPDATE SET
            person_id = EXCLUDED.person_id,
            version = COALESCE({pdi_table}.version, 0) + 1,
            is_deleted = false
            WHERE {pdi_table}.is_deleted = true
        RETURNING team_id::bigint AS team_id, distinct_id, person_id,
                  (xmax = 0) AS inserted
        "#
    );
    let rows = sqlx::query(&sql)
        .bind(&pdi_dids)
        .bind(&pdi_person_ids)
        .bind(&pdi_teams)
        .bind(&pdi_versions)
        .fetch_all(&mut **tx)
        .await?;
    for row in rows {
        let team_id: i64 = row.try_get("team_id")?;
        let distinct_id: String = row.try_get("distinct_id")?;
        let person_id: i64 = row.try_get("person_id")?;
        let inserted: bool = row.try_get("inserted")?;
        if !inserted {
            mapping.revived.insert((team_id, distinct_id.clone()));
        }
        mapping.written.insert((team_id, distinct_id), person_id);
    }
    Ok(mapping)
}

/// Step 4: per-stub outcomes. A stub is Committed when its primary distinct
/// id maps to its person; a stub whose primary mapping went elsewhere is a
/// lost race, and if this transaction created its person, the rows are
/// undone (created this transaction, so nothing can reference them) so the
/// stub doesn't linger orphaned.
async fn resolve_stub_outcomes(
    tx: &mut Tx<'_>,
    tables: &IdentityTables,
    stubs: &[PersonStub],
    uuids: &[Uuid],
    persons: &PersonsByKey,
    mapping: &MappingOutcome,
) -> StorageResult<Vec<StubOutcome>> {
    let mut outcomes = Vec::with_capacity(stubs.len());
    for (i, stub) in stubs.iter().enumerate() {
        let Some(resolved) = persons.get(&(stub.team_id, uuids[i])) else {
            outcomes.push(StubOutcome::LostRace);
            continue;
        };
        let primary_key = (stub.team_id, stub.distinct_id.clone());
        if mapping.written.get(&primary_key) == Some(&resolved.person.id) {
            outcomes.push(StubOutcome::Committed {
                person: resolved.person.clone(),
                created: resolved.created_by_us,
            });
            continue;
        }
        if resolved.created_by_us {
            undo_created_person(tx, tables, stub.team_id, resolved, mapping).await?;
            outcomes.push(StubOutcome::LostRace);
            continue;
        }
        // The person pre-existed and its primary mapping wasn't inserted by
        // us — verify the existing mapping points at this person.
        let existing_sql = format!(
            "SELECT person_id FROM {} WHERE team_id = $1 AND distinct_id = $2 AND is_deleted = false",
            tables.person_distinct_id
        );
        let existing: Option<i64> = sqlx::query_scalar(&existing_sql)
            .bind(stub.team_id as i32)
            .bind(&stub.distinct_id)
            .fetch_optional(&mut **tx)
            .await?;
        if existing == Some(resolved.person.id) {
            outcomes.push(StubOutcome::Committed {
                person: resolved.person.clone(),
                created: false,
            });
        } else {
            outcomes.push(StubOutcome::LostRace);
        }
    }
    Ok(outcomes)
}

/// Undo one lost-race stub's rows: its distinct id mappings, then its person
/// row. Rows that revived a tombstone must be re-tombstoned (the tombstone
/// predates this transaction and must survive it), never hard-deleted; the
/// version bumps again so it stays monotonic. Re-tombstoning first lets the
/// fresh-row sweep distinguish them by is_deleted.
async fn undo_created_person(
    tx: &mut Tx<'_>,
    tables: &IdentityTables,
    team_id: i64,
    resolved: &ResolvedPerson,
    mapping: &MappingOutcome,
) -> StorageResult<()> {
    let person_table = &tables.person;
    let pdi_table = &tables.person_distinct_id;
    let revived_dids: Vec<String> = mapping
        .written
        .iter()
        .filter(|((t, d), pid)| {
            *t == team_id
                && **pid == resolved.person.id
                && mapping.revived.contains(&(*t, d.clone()))
        })
        .map(|((_, d), _)| d.clone())
        .collect();
    if !revived_dids.is_empty() {
        let retombstone_sql = format!(
            r#"
            UPDATE {pdi_table}
            SET is_deleted = true, version = COALESCE(version, 0) + 1
            WHERE team_id = $1 AND distinct_id = ANY($2)
            "#
        );
        sqlx::query(&retombstone_sql)
            .bind(team_id as i32)
            .bind(&revived_dids)
            .execute(&mut **tx)
            .await?;
    }
    let delete_mappings_sql = format!(
        "DELETE FROM {pdi_table} WHERE team_id = $1 AND person_id = $2 AND is_deleted = false"
    );
    sqlx::query(&delete_mappings_sql)
        .bind(team_id as i32)
        .bind(resolved.person.id)
        .execute(&mut **tx)
        .await?;
    if resolved.revived_tombstone {
        let sql = format!(
            r#"
            UPDATE {person_table}
            SET is_deleted = true, version = COALESCE(version, 0) + 1,
                properties = '{{}}'::jsonb
            WHERE team_id = $1 AND id = $2
            "#
        );
        sqlx::query(&sql)
            .bind(team_id as i32)
            .bind(resolved.person.id)
            .execute(&mut **tx)
            .await?;
    } else {
        let sql = format!("DELETE FROM {person_table} WHERE team_id = $1 AND id = $2");
        sqlx::query(&sql)
            .bind(team_id as i32)
            .bind(resolved.person.id)
            .execute(&mut **tx)
            .await?;
    }
    Ok(())
}
