//! The publish plane of the gate: what `personhog-publisher` put on Kafka,
//! read back and held against Postgres and the journal. The distinct id
//! topic is compared as a final state, the highest version per distinct
//! id, and the merge events topic as a set of (old, new) pairs, because a
//! replay after a crash legitimately repeats rows and the consumers of
//! both topics absorb that.

use std::collections::{HashMap, HashSet};
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};
pub use personhog_common::cdc_parity::Mapping as PublishedMapping;
use personhog_common::cdc_parity::{
    DistinctIdRow, FeedState, MappingConflict, MergeConflict, MergeEvent,
};
use serde_json::{json, Value};
use sqlx::postgres::PgPool;
use sqlx::Row;
use uuid::Uuid;

use crate::report::ConsistencyViolation;
use crate::stack::kafka::read_to_end;
use crate::state::MergedSource;

/// How long the outbox may take to drain once traffic has stopped. The
/// publishers poll every 50 ms under a small row budget, so a run's rows
/// drain in seconds; the margin covers a crash-restart mid-drain.
pub const DRAIN_DEADLINE: Duration = Duration::from_secs(60);
const READ_DEADLINE: Duration = Duration::from_secs(30);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExpectedMapping {
    pub person_id: i64,
    pub person_uuid: Uuid,
    pub is_deleted: bool,
    pub version: i64,
}

pub struct PublishedMappings {
    pub rows: HashMap<String, PublishedMapping>,
    /// Two rows that differ at the same version, one violation each. A
    /// ReplacingMergeTree keeps whichever arrived last, so the final state
    /// would depend on produce order.
    pub conflicts: Vec<ConsistencyViolation>,
    /// Rows of other teams, which the shared outbox also drains.
    pub foreign_rows: usize,
}

pub struct PublishedMerges {
    pub pairs: HashSet<(Uuid, Uuid)>,
    /// Resolved to violations where the person ids are known.
    pub conflicts: Vec<MergeConflict>,
    /// Events read, duplicates included. More events than pairs is a
    /// replay or a conflict.
    pub events: usize,
    pub foreign_events: usize,
}

pub struct ExpectedMerges {
    /// Old person uuid to the survivor's uuid.
    pub pairs: HashMap<Uuid, Uuid>,
    /// Sources whose op never settled. Those are violations already, and an
    /// event for one is neither owed nor wrong.
    pub uncertain: HashSet<Uuid>,
    pub ids: HashMap<Uuid, i64>,
}

/// Pending outbox rows the stack's publishers would claim: every team's,
/// because the claim is not scoped, minus `except_team` when a run owns
/// one. Publishers started over someone else's rows drain them onto the
/// run's own topics and delete them with the teardown.
pub async fn pending_outbox_rows(
    pool: &PgPool,
    outbox_table: &str,
    except_team: Option<i32>,
) -> Result<i64> {
    let count = match except_team {
        Some(team) => {
            sqlx::query_scalar(&format!(
                "SELECT count(*) FROM {outbox_table} WHERE given_up_at IS NULL AND team_id <> $1"
            ))
            .bind(team)
            .fetch_one(pool)
            .await
        }
        None => {
            sqlx::query_scalar(&format!(
                "SELECT count(*) FROM {outbox_table} WHERE given_up_at IS NULL"
            ))
            .fetch_one(pool)
            .await
        }
    };
    count.context("counting pending outbox rows")
}

/// Poll until no row of the team is pending in the outbox, or the deadline
/// passes. A parked row (`given_up_at`) is a violation: only an operator
/// sets it, so a spawned stack must have none. A row the publisher could
/// not read stays pending with its `last_error`, so a deadline miss lists
/// those rows next to the pending count. Returns the drain time.
pub async fn wait_outbox_drained(
    pool: &PgPool,
    outbox_table: &str,
    team_id: i64,
    deadline: Duration,
) -> Result<(Duration, Vec<ConsistencyViolation>)> {
    let team: i32 = team_id.try_into().context("team_id out of i32 range")?;
    let counts = format!(
        "SELECT count(*) FILTER (WHERE given_up_at IS NULL) AS pending, \
                count(*) FILTER (WHERE given_up_at IS NOT NULL) AS parked \
         FROM {outbox_table} WHERE team_id = $1"
    );
    let parked_rows = format!(
        "SELECT id, kind, last_error FROM {outbox_table} \
         WHERE team_id = $1 AND given_up_at IS NOT NULL ORDER BY id"
    );
    let deferred_rows = format!(
        "SELECT id, kind, last_error FROM {outbox_table} \
         WHERE team_id = $1 AND given_up_at IS NULL AND last_error IS NOT NULL \
         ORDER BY id LIMIT 20"
    );
    let row_violations = |rows: Vec<sqlx::postgres::PgRow>, key: &str| {
        rows.into_iter()
            .map(|row| {
                let id: i64 = row.get("id");
                let kind: String = row.get("kind");
                let last_error: Option<String> = row.get("last_error");
                ConsistencyViolation {
                    person_id: 0,
                    key: format!("{key}:{kind}:{id}"),
                    expected: json!("published"),
                    actual: json!(last_error),
                }
            })
            .collect::<Vec<_>>()
    };
    let start = Instant::now();
    loop {
        let row = sqlx::query(&counts)
            .bind(team)
            .fetch_one(pool)
            .await
            .context("counting outbox rows")?;
        let pending: i64 = row.get("pending");
        let parked: i64 = row.get("parked");
        if pending == 0 {
            let mut violations = Vec::new();
            if parked > 0 {
                let rows = sqlx::query(&parked_rows)
                    .bind(team)
                    .fetch_all(pool)
                    .await
                    .context("reading parked outbox rows")?;
                violations.extend(row_violations(rows, "__publish_outbox_parked"));
            }
            return Ok((start.elapsed(), violations));
        }
        if start.elapsed() > deadline {
            let mut violations = vec![ConsistencyViolation {
                person_id: 0,
                key: "__publish_outbox_pending".to_string(),
                expected: json!("0 rows pending"),
                actual: json!(pending),
            }];
            let rows = sqlx::query(&deferred_rows)
                .bind(team)
                .fetch_all(pool)
                .await
                .context("reading deferred outbox rows")?;
            violations.extend(row_violations(rows, "__publish_outbox_deferred"));
            return Ok((start.elapsed(), violations));
        }
        tokio::time::sleep(Duration::from_millis(250)).await;
    }
}

/// Every mapping of the team in Postgres, live or tombstoned, as the row
/// the topic must end on. A mapping without a person row is a Postgres
/// integrity failure, not a publish result, and fails the read outright.
pub async fn expected_mappings(
    pool: &PgPool,
    person_table: &str,
    team_id: i64,
) -> Result<HashMap<String, ExpectedMapping>> {
    let team: i32 = team_id.try_into().context("team_id out of i32 range")?;
    let pdi_table = crate::seed::distinct_id_tables_for(person_table)
        .first()
        .context("no distinct id table for the person table")?;
    let query = format!(
        "SELECT d.distinct_id, d.person_id, d.is_deleted, COALESCE(d.version, 0) AS version, \
                p.uuid \
         FROM {pdi_table} d \
         LEFT JOIN {person_table} p ON p.team_id = d.team_id AND p.id = d.person_id \
         WHERE d.team_id = $1"
    );
    let mut expected = HashMap::new();
    for row in sqlx::query(&query)
        .bind(team)
        .fetch_all(pool)
        .await
        .context("reading the distinct id mappings from Postgres")?
    {
        let distinct_id: String = row.get("distinct_id");
        let person_id: i64 = row.get("person_id");
        let person_uuid: Option<Uuid> = row.get("uuid");
        let Some(person_uuid) = person_uuid else {
            bail!("distinct id {distinct_id} maps to person {person_id}, which has no row");
        };
        expected.insert(
            distinct_id,
            ExpectedMapping {
                person_id,
                person_uuid,
                is_deleted: row.get("is_deleted"),
                version: row.get("version"),
            },
        );
    }
    Ok(expected)
}

/// The delete leg's effect on the mappings: every mapping that was live
/// before it is now a tombstone under the same uuid. Without this, the
/// topic comparison after the deletes could pass against mappings the
/// deletes never touched.
pub fn verify_tombstoned_in_postgres(
    before: &HashMap<String, ExpectedMapping>,
    after: &HashMap<String, ExpectedMapping>,
) -> Vec<ConsistencyViolation> {
    let mut violations = Vec::new();
    let mut distinct_ids: Vec<&String> = before.keys().collect();
    distinct_ids.sort();
    for distinct_id in distinct_ids {
        let was = &before[distinct_id];
        let Some(now) = after.get(distinct_id) else {
            violations.push(ConsistencyViolation {
                person_id: was.person_id,
                key: format!("__mapping_gone_after_delete:{distinct_id}"),
                expected: json!("a tombstoned mapping row"),
                actual: Value::Null,
            });
            continue;
        };
        if !now.is_deleted {
            violations.push(ConsistencyViolation {
                person_id: was.person_id,
                key: format!("__mapping_live_after_delete:{distinct_id}"),
                expected: json!("is_deleted"),
                actual: json!(false),
            });
        }
        if now.person_uuid != was.person_uuid {
            violations.push(ConsistencyViolation {
                person_id: was.person_id,
                key: format!("__mapping_owner_changed_by_delete:{distinct_id}"),
                expected: json!(was.person_uuid),
                actual: json!(now.person_uuid),
            });
        }
    }
    violations
}

pub async fn read_published_mappings(
    kafka_hosts: &str,
    topic: &str,
    team_id: i64,
) -> Result<PublishedMappings> {
    let records = read_to_end(kafka_hosts, topic, READ_DEADLINE).await?;
    fold_published_mappings(records.iter().map(|r| r.payload.as_slice()), team_id)
}

/// A row that does not decode is a publisher bug and fails the read.
pub fn fold_published_mappings<'a>(
    payloads: impl IntoIterator<Item = &'a [u8]>,
    team_id: i64,
) -> Result<PublishedMappings> {
    let mut feed = FeedState::new();
    let mut conflicts = Vec::new();
    let mut foreign_rows = 0;
    for payload in payloads {
        let row = DistinctIdRow::decode(payload)?;
        if row.team_id != team_id {
            foreign_rows += 1;
            continue;
        }
        if let Some(conflict) = feed.observe_mapping(&row) {
            conflicts.push(mapping_conflict_violation(conflict));
        }
    }
    let rows = feed
        .mappings()
        .map(|(key, mapping)| (key.distinct_id.clone(), mapping.clone()))
        .collect();
    Ok(PublishedMappings {
        rows,
        conflicts,
        foreign_rows,
    })
}

fn mapping_conflict_violation(conflict: MappingConflict) -> ConsistencyViolation {
    ConsistencyViolation {
        person_id: 0,
        key: format!("__published_mapping_conflict:{}", conflict.key.distinct_id),
        expected: json!(format!("one row at version {}", conflict.version)),
        actual: json!([
            mapping_json(&conflict.first),
            mapping_json(&conflict.second)
        ]),
    }
}

fn mapping_json(row: &PublishedMapping) -> Value {
    json!({
        "person_uuid": row.person_uuid,
        "is_deleted": row.is_deleted,
        "version": row.version,
    })
}

pub fn verify_published_mappings(
    expected: &HashMap<String, ExpectedMapping>,
    published: &HashMap<String, PublishedMapping>,
) -> Vec<ConsistencyViolation> {
    let mut violations = Vec::new();
    let mut distinct_ids: Vec<&String> = expected.keys().collect();
    distinct_ids.sort();
    for distinct_id in distinct_ids {
        let want = &expected[distinct_id];
        let Some(got) = published.get(distinct_id) else {
            violations.push(ConsistencyViolation {
                person_id: want.person_id,
                key: format!("__published_mapping_missing:{distinct_id}"),
                expected: json!("a row on the topic"),
                actual: Value::Null,
            });
            continue;
        };
        if got.person_uuid != want.person_uuid {
            violations.push(ConsistencyViolation {
                person_id: want.person_id,
                key: format!("__published_mapping_person:{distinct_id}"),
                expected: json!(want.person_uuid),
                actual: json!(got.person_uuid),
            });
        }
        if got.is_deleted != want.is_deleted {
            violations.push(ConsistencyViolation {
                person_id: want.person_id,
                key: format!("__published_mapping_tombstone:{distinct_id}"),
                expected: json!(want.is_deleted),
                actual: json!(got.is_deleted),
            });
        }
        if got.version != want.version {
            violations.push(ConsistencyViolation {
                person_id: want.person_id,
                key: format!("__published_mapping_version:{distinct_id}"),
                expected: json!(want.version),
                actual: json!(got.version),
            });
        }
    }
    let mut unexpected: Vec<&String> = published
        .keys()
        .filter(|distinct_id| !expected.contains_key(*distinct_id))
        .collect();
    unexpected.sort();
    for distinct_id in unexpected {
        violations.push(ConsistencyViolation {
            person_id: 0,
            key: format!("__published_mapping_unexpected:{distinct_id}"),
            expected: json!("no row: Postgres holds no such mapping"),
            actual: mapping_json(&published[distinct_id]),
        });
    }
    violations
}

/// The merged sources the journal holds, resolved to uuids. The sagas
/// tombstone person rows in place, so every id still has one.
pub async fn expected_merges(
    pool: &PgPool,
    person_table: &str,
    team_id: i64,
    merged: &HashMap<i64, MergedSource>,
    uncertain_ids: &[i64],
) -> Result<ExpectedMerges> {
    let team: i32 = team_id.try_into().context("team_id out of i32 range")?;
    let mut person_ids: Vec<i64> = merged
        .iter()
        .flat_map(|(source, edge)| [*source, edge.survivor])
        .chain(uncertain_ids.iter().copied())
        .collect();
    person_ids.sort_unstable();
    person_ids.dedup();
    let query = format!("SELECT id, uuid FROM {person_table} WHERE team_id = $1 AND id = ANY($2)");
    let mut uuids: HashMap<i64, Uuid> = HashMap::new();
    for row in sqlx::query(&query)
        .bind(team)
        .bind(&person_ids)
        .fetch_all(pool)
        .await
        .context("reading person uuids for the merge events")?
    {
        let id: i64 = row.get("id");
        let uuid: Uuid = row.get("uuid");
        uuids.insert(id, uuid);
    }
    let uuid_of = |id: i64| {
        uuids
            .get(&id)
            .copied()
            .with_context(|| format!("person {id} has no row; cannot resolve its merge event"))
    };
    let mut pairs = HashMap::new();
    for (source, edge) in merged {
        pairs.insert(uuid_of(*source)?, uuid_of(edge.survivor)?);
    }
    let mut uncertain = HashSet::new();
    for id in uncertain_ids {
        uncertain.insert(uuid_of(*id)?);
    }
    let ids = uuids.into_iter().map(|(id, uuid)| (uuid, id)).collect();
    Ok(ExpectedMerges {
        pairs,
        uncertain,
        ids,
    })
}

pub async fn read_published_merges(
    kafka_hosts: &str,
    topic: &str,
    team_id: i64,
) -> Result<PublishedMerges> {
    let records = read_to_end(kafka_hosts, topic, READ_DEADLINE).await?;
    fold_published_merges(
        records
            .iter()
            .map(|r| (r.key.as_deref(), r.payload.as_slice())),
        team_id,
    )
}

/// An event without the wire shape or the key the cohort stream processor
/// depends on is a publisher bug and fails the read.
pub fn fold_published_merges<'a>(
    records: impl IntoIterator<Item = (Option<&'a [u8]>, &'a [u8])>,
    team_id: i64,
) -> Result<PublishedMerges> {
    let mut feed = FeedState::new();
    let mut conflicts = Vec::new();
    let mut events = 0;
    let mut foreign_events = 0;
    for (key, payload) in records {
        let event = MergeEvent::decode(key, payload)?;
        if event.team_id != team_id {
            foreign_events += 1;
            continue;
        }
        events += 1;
        if let Some(conflict) = feed.observe_merge(&event) {
            conflicts.push(conflict);
        }
    }
    let pairs = feed
        .merges()
        .map(|(old, new)| (old.person_uuid, new))
        .collect();
    Ok(PublishedMerges {
        pairs,
        conflicts,
        events,
        foreign_events,
    })
}

pub fn verify_published_merges(
    expected: &ExpectedMerges,
    published: &PublishedMerges,
) -> Vec<ConsistencyViolation> {
    let mut violations = Vec::new();
    for conflict in &published.conflicts {
        violations.push(ConsistencyViolation {
            person_id: expected
                .ids
                .get(&conflict.old.person_uuid)
                .copied()
                .unwrap_or_default(),
            key: "__published_merge_conflict".to_string(),
            expected: json!(format!("one merge target for {}", conflict.old.person_uuid)),
            actual: json!([conflict.first, conflict.second]),
        });
    }
    let published = &published.pairs;
    let mut pairs: Vec<(&Uuid, &Uuid)> = expected.pairs.iter().collect();
    pairs.sort();
    for (old, new) in pairs {
        if expected.uncertain.contains(old) || published.contains(&(*old, *new)) {
            continue;
        }
        violations.push(ConsistencyViolation {
            person_id: expected.ids.get(old).copied().unwrap_or_default(),
            key: "__published_merge_missing".to_string(),
            expected: json!(format!("merge event {old} -> {new}")),
            actual: Value::Null,
        });
    }
    let mut extra: Vec<&(Uuid, Uuid)> = published
        .iter()
        .filter(|(old, new)| {
            !expected.uncertain.contains(old) && expected.pairs.get(old) != Some(new)
        })
        .collect();
    extra.sort();
    for (old, new) in extra {
        violations.push(ConsistencyViolation {
            person_id: expected.ids.get(old).copied().unwrap_or_default(),
            key: "__published_merge_unexpected".to_string(),
            expected: json!("no merge event: the journal holds no such merge"),
            actual: json!(format!("{old} -> {new}")),
        });
    }
    violations
}

#[cfg(test)]
mod tests {
    use personhog_common::cdc_parity::PersonKey;

    use super::*;

    fn keys(violations: Vec<ConsistencyViolation>) -> Vec<String> {
        violations.into_iter().map(|v| v.key).collect()
    }

    fn uuid(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    fn mapping(
        person_id: i64,
        person_uuid: Uuid,
        is_deleted: bool,
        version: i64,
    ) -> ExpectedMapping {
        ExpectedMapping {
            person_id,
            person_uuid,
            is_deleted,
            version,
        }
    }

    fn published(person_uuid: Uuid, is_deleted: bool, version: i64) -> PublishedMapping {
        PublishedMapping {
            person_uuid,
            is_deleted,
            version,
        }
    }

    // A verifier that passes on a missing or stale row looks exactly like
    // a healthy publisher, so every disagreement has its own row here.
    #[test]
    fn published_mapping_decision_table() {
        let expected = HashMap::from([("d".to_string(), mapping(7, uuid(1), false, 3))]);
        let check = |row: Option<PublishedMapping>| {
            let topic: HashMap<String, PublishedMapping> =
                row.into_iter().map(|r| ("d".to_string(), r)).collect();
            keys(verify_published_mappings(&expected, &topic))
        };
        assert!(check(Some(published(uuid(1), false, 3))).is_empty());
        assert_eq!(check(None), vec!["__published_mapping_missing:d"]);
        assert_eq!(
            check(Some(published(uuid(1), false, 2))),
            vec!["__published_mapping_version:d"]
        );
        assert_eq!(
            check(Some(published(uuid(1), false, 4))),
            vec!["__published_mapping_version:d"]
        );
        assert_eq!(
            check(Some(published(uuid(2), false, 3))),
            vec!["__published_mapping_person:d"]
        );
        assert_eq!(
            check(Some(published(uuid(1), true, 3))),
            vec!["__published_mapping_tombstone:d"]
        );

        let topic = HashMap::from([
            ("d".to_string(), published(uuid(1), false, 3)),
            ("ghost".to_string(), published(uuid(9), false, 0)),
        ]);
        assert_eq!(
            keys(verify_published_mappings(&expected, &topic)),
            vec!["__published_mapping_unexpected:ghost"]
        );
    }

    // The delete leg must leave every mapping tombstoned in Postgres before
    // the topic is compared again, or the second comparison proves nothing.
    #[test]
    fn tombstoned_in_postgres_decision_table() {
        let before = HashMap::from([("d".to_string(), mapping(7, uuid(1), false, 3))]);
        let check = |after: Option<ExpectedMapping>| {
            let after: HashMap<String, ExpectedMapping> =
                after.into_iter().map(|m| ("d".to_string(), m)).collect();
            keys(verify_tombstoned_in_postgres(&before, &after))
        };
        assert!(check(Some(mapping(7, uuid(1), true, 4))).is_empty());
        assert_eq!(check(None), vec!["__mapping_gone_after_delete:d"]);
        assert_eq!(
            check(Some(mapping(7, uuid(1), false, 3))),
            vec!["__mapping_live_after_delete:d"]
        );
        assert_eq!(
            check(Some(mapping(7, uuid(2), true, 4))),
            vec!["__mapping_owner_changed_by_delete:d"]
        );
    }

    // The fold rules live in personhog-common; this covers the gate's own
    // mapping of its findings to violations and the foreign-row count.
    #[test]
    fn fold_findings_become_violations() {
        let row = |uuid: u128, version: i64| {
            format!(
                r#"{{"person_id":"{}","team_id":5,"distinct_id":"d","version":{version},"is_deleted":0}}"#,
                Uuid::from_u128(uuid)
            )
        };
        let other_team = r#"{"person_id":"00000000-0000-0000-0000-000000000002","team_id":6,"distinct_id":"d","version":9,"is_deleted":0}"#.to_string();
        let payloads = [row(1, 2), row(2, 2), row(1, 3), other_team];
        let folded =
            fold_published_mappings(payloads.iter().map(|p| p.as_bytes()), 5).expect("decodes");
        assert_eq!(
            keys(folded.conflicts),
            vec!["__published_mapping_conflict:d"]
        );
        assert_eq!(
            folded.rows,
            HashMap::from([("d".to_string(), published(uuid(1), false, 3))])
        );
        assert_eq!(folded.foreign_rows, 1);

        let event = |new: u128| {
            format!(
                r#"{{"team_id":5,"old_person_uuid":"{}","new_person_uuid":"{}","merged_at_ms":10,"schema_version":1}}"#,
                uuid(1),
                uuid(new)
            )
        };
        let key = format!("5:{}", uuid(1)).into_bytes();
        let records = [event(2), event(2), event(3)];
        let folded = fold_published_merges(
            records.iter().map(|p| (Some(key.as_slice()), p.as_bytes())),
            5,
        )
        .expect("decodes");
        assert_eq!(
            folded.conflicts,
            vec![MergeConflict {
                old: PersonKey::new(5, uuid(1)),
                first: uuid(2),
                second: uuid(3),
            }]
        );
        assert_eq!(folded.pairs, HashSet::from([(uuid(1), uuid(2))]));
        assert_eq!(folded.events, 3);

        // Skipping an unreadable payload would pass a gate over a publisher that corrupts rows.
        assert!(
            fold_published_mappings([br#"{"team_id":5,"distinct_id":"d"}"#.as_slice()], 5).is_err()
        );
        assert!(fold_published_merges([(None, event(2).as_bytes())], 5).is_err());
    }

    #[test]
    fn merge_pair_decision_table() {
        let expected = ExpectedMerges {
            pairs: HashMap::from([(uuid(1), uuid(2))]),
            uncertain: HashSet::from([uuid(3)]),
            ids: HashMap::from([(uuid(1), 1), (uuid(2), 2), (uuid(3), 3)]),
        };
        let read = |pairs: &[(Uuid, Uuid)], conflicts: Vec<MergeConflict>| PublishedMerges {
            pairs: pairs.iter().copied().collect(),
            conflicts,
            events: pairs.len(),
            foreign_events: 0,
        };
        let check = |pairs: &[(Uuid, Uuid)]| {
            keys(verify_published_merges(&expected, &read(pairs, Vec::new())))
        };
        assert!(check(&[(uuid(1), uuid(2))]).is_empty());
        // A second target is reported against the journal's id of the person.
        let conflicted = verify_published_merges(
            &expected,
            &read(
                &[(uuid(1), uuid(2))],
                vec![MergeConflict {
                    old: PersonKey::new(5, uuid(1)),
                    first: uuid(2),
                    second: uuid(5),
                }],
            ),
        );
        assert_eq!(conflicted[0].person_id, 1);
        assert_eq!(keys(conflicted), vec!["__published_merge_conflict"]);
        assert_eq!(check(&[]), vec!["__published_merge_missing"]);
        assert_eq!(
            check(&[(uuid(1), uuid(2)), (uuid(4), uuid(5))]),
            vec!["__published_merge_unexpected"]
        );
        assert_eq!(
            check(&[(uuid(1), uuid(5))]),
            vec!["__published_merge_missing", "__published_merge_unexpected"]
        );
        // An uncertain source may or may not have merged.
        assert!(check(&[(uuid(1), uuid(2)), (uuid(3), uuid(2))]).is_empty());
    }
}
