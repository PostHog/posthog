//! Attach personless distinct ids to an existing person with plain mapping
//! inserts — the personless-source merge case, settled inline with no saga.

use std::collections::HashMap;

use sqlx::postgres::PgPool;
use sqlx::Row;

use crate::config::IdentityTables;
use crate::storage::error::StorageResult;
use crate::storage::types::AttachOutcome;

/// Fresh inserts get version 1, like a stub's extra distinct ids: with no
/// personless table there is no proof the id never sent events, and 1 is
/// safe either way. Tombstoned mappings revive (repoint + version bump);
/// live mappings are never repointed — that would be a silent merge.
/// Callers dedupe; sorted insert order keeps row locks deadlock-free.
///
/// Two guards keep a racing lifecycle op from acquiring a mapping it can
/// no longer sweep: the join on a live person row rejects committed
/// deletions, and the mark check rejects persons held by a live op, whose
/// destructive transaction sweeps distinct ids before it tombstones. The
/// one statement that can slip both (a snapshot predating the mark's
/// commit whose insert lands after the sweep) leaves an orphaned mapping
/// naming a tombstoned person, which the next resolve treats as absent.
pub(super) async fn attach_distinct_ids(
    pool: &PgPool,
    tables: &IdentityTables,
    team_id: i64,
    person_id: i64,
    distinct_ids: &[String],
) -> StorageResult<HashMap<String, AttachOutcome>> {
    if distinct_ids.is_empty() {
        return Ok(HashMap::new());
    }
    let mut sorted: Vec<String> = distinct_ids.to_vec();
    sorted.sort_unstable();

    let insert_sql = format!(
        r#"
        INSERT INTO {pdi} (distinct_id, person_id, team_id, version)
        SELECT u.d, p.id, p.team_id, 1
        FROM unnest($1::text[]) AS u(d)
        JOIN {person} p
          ON p.team_id = $3 AND p.id = $2 AND p.is_deleted = false
        WHERE NOT EXISTS (
            SELECT 1 FROM lifecycle_op_person m
            WHERE m.team_id = p.team_id AND m.person_id = p.id
              AND m.status IN ('marked', 'sealed')
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
    );
    let written = sqlx::query(&insert_sql)
        .bind(&sorted)
        .bind(person_id)
        .bind(team_id as i32)
        .fetch_all(pool)
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
    let rows = sqlx::query(&losers_sql)
        .bind(team_id as i32)
        .bind(&losers)
        .fetch_all(pool)
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
