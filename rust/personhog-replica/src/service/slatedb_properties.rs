use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use futures::future::join_all;
use personhog_property_store::reader::PropertyReader;
use personhog_property_store::{PropertyStoreError, StoredProperties, STUB_VERSION};
use tokio::sync::Semaphore;
use tonic::Status;

use crate::storage::types::Person;

const READS_TOTAL: &str = "personhog_replica_slatedb_property_reads_total";
const READ_MS: &str = "personhog_replica_slatedb_property_read_ms";

pub(crate) struct SlatedbProperties {
    pub(crate) reader: Arc<PropertyReader>,
    /// Bounds the SlateDB reads in flight across requests; a batch starts one read per person.
    permits: Semaphore,
}

impl SlatedbProperties {
    pub(crate) fn new(reader: Arc<PropertyReader>, read_concurrency: usize) -> Self {
        Self {
            reader,
            permits: Semaphore::new(read_concurrency.max(1)),
        }
    }
}

#[derive(Debug, PartialEq)]
pub(crate) enum Resolved {
    Served(String),
    /// SlateDB has the delete; the replica's row has not caught up with it.
    Gone,
    Unavailable,
}

/// Eventual reads serve SlateDB's record whatever its version. A person who should have a
/// record but has none fails closed, so a gap never reads as empty properties. A record behind
/// the row that predates the row's `created_at` belongs to a previous incarnation: a revival
/// resets `created_at` and starts the person empty, and its delete marker may not have arrived.
/// A record behind a row whose `created_at` went down predates a merge, which may follow a
/// revival; it cannot be tied to the live incarnation, so it fails closed.
pub(crate) fn resolve(
    read: Result<Option<StoredProperties>, PropertyStoreError>,
    row_version: i64,
    row_created_at: i64,
) -> (Resolved, &'static str) {
    match read {
        Ok(Some(stored)) if stored.is_revival(row_version) => {
            (Resolved::Served("{}".to_string()), "revived")
        }
        Ok(Some(stored)) if stored.deleted => (Resolved::Gone, "deleted"),
        Ok(Some(stored)) if stored.version < row_version && stored.created_at < row_created_at => {
            (Resolved::Served("{}".to_string()), "previous_incarnation")
        }
        Ok(Some(stored)) if stored.version < row_version && stored.created_at > row_created_at => {
            (Resolved::Unavailable, "merged_since")
        }
        Ok(Some(stored)) => {
            let outcome = if stored.version < row_version {
                "behind"
            } else {
                "served"
            };
            match String::from_utf8(stored.properties.to_vec()) {
                Ok(properties) => (Resolved::Served(properties), outcome),
                Err(_) => (Resolved::Unavailable, "undecodable"),
            }
        }
        Ok(None) if row_version == STUB_VERSION => (Resolved::Served("{}".to_string()), "stub"),
        Ok(None) => (Resolved::Unavailable, "missing"),
        Err(PropertyStoreError::Timeout) => (Resolved::Unavailable, "timeout"),
        Err(e) => {
            let class = e.class();
            if class == "data" {
                tracing::error!(error = %e, "slatedb property read failed");
            } else {
                tracing::debug!(error = %e, "slatedb property read failed");
            }
            (Resolved::Unavailable, class)
        }
    }
}

pub(crate) async fn with_properties(
    slatedb: &SlatedbProperties,
    mut person: Person,
) -> Result<Option<Person>, Status> {
    let started = Instant::now();
    let read = {
        let _permit = slatedb.permits.acquire().await;
        slatedb.reader.get(person.team_id, person.id).await
    };
    common_metrics::histogram(READ_MS, &[], started.elapsed().as_secs_f64() * 1000.0);
    let (resolved, outcome) = resolve(
        read,
        person.version.unwrap_or(0),
        person.created_at.timestamp_millis(),
    );
    common_metrics::inc(
        READS_TOTAL,
        &[("outcome".to_string(), outcome.to_string())],
        1,
    );
    match resolved {
        Resolved::Served(properties) => {
            person.properties = Some(properties);
            Ok(Some(person))
        }
        Resolved::Gone => Ok(None),
        Resolved::Unavailable => Err(Status::unavailable(format!(
            "person properties not readable yet: {outcome}"
        ))),
    }
}

pub(crate) async fn all_with_properties(
    slatedb: &SlatedbProperties,
    persons: Vec<Person>,
) -> Result<Vec<Person>, Status> {
    let read = join_all(
        persons
            .into_iter()
            .map(|person| with_properties(slatedb, person)),
    )
    .await;
    Ok(read
        .into_iter()
        .collect::<Result<Vec<_>, _>>()?
        .into_iter()
        .flatten()
        .collect())
}

/// One read per person, however many keys resolve to it.
pub(crate) async fn keyed_with_properties<K>(
    slatedb: &SlatedbProperties,
    rows: Vec<(K, Option<Person>)>,
) -> Result<Vec<(K, Option<Person>)>, Status> {
    let (persons, slots) = dedupe(rows, |person| (person.team_id, person.id));
    let read = join_all(
        persons
            .into_iter()
            .map(|person| with_properties(slatedb, person)),
    )
    .await;
    let read: Vec<Option<Person>> = read.into_iter().collect::<Result<_, _>>()?;
    Ok(slots
        .into_iter()
        .map(|(key, slot)| (key, slot.and_then(|index| read[index].clone())))
        .collect())
}

/// The distinct persons of a keyed batch, and each row's index into them.
fn dedupe<K, P>(
    rows: Vec<(K, Option<P>)>,
    person_key: impl Fn(&P) -> (i64, i64),
) -> (Vec<P>, Vec<(K, Option<usize>)>) {
    let mut persons: Vec<P> = Vec::new();
    let mut index: HashMap<(i64, i64), usize> = HashMap::new();
    let slots = rows
        .into_iter()
        .map(|(key, person)| {
            let slot = person.map(|person| {
                *index.entry(person_key(&person)).or_insert_with(|| {
                    persons.push(person);
                    persons.len() - 1
                })
            });
            (key, slot)
        })
        .collect();
    (persons, slots)
}

#[cfg(test)]
mod tests {
    use personhog_property_store::bytes::Bytes;
    use rstest::rstest;

    use super::*;

    fn stored(version: i64, deleted: bool, created_at: i64) -> StoredProperties {
        StoredProperties {
            version,
            deleted,
            created_at,
            properties: Bytes::from_static(br#"{"plan":"paid"}"#),
        }
    }

    #[rstest]
    #[case::at_the_row_version(Some(stored(4, false, 1000)), 4, 1000, Resolved::Served(r#"{"plan":"paid"}"#.into()), "served")]
    #[case::behind_the_row(Some(stored(3, false, 1000)), 4, 1000, Resolved::Served(r#"{"plan":"paid"}"#.into()), "behind")]
    #[case::behind_after_a_merge_lowered_created_at(
        Some(stored(3, false, 2000)),
        4,
        1000,
        Resolved::Unavailable,
        "merged_since"
    )]
    #[case::behind_from_a_previous_incarnation(
        Some(stored(3, false, 1000)),
        5,
        2000,
        Resolved::Served("{}".into()),
        "previous_incarnation"
    )]
    #[case::at_the_version_of_a_new_incarnation(Some(stored(5, false, 2000)), 5, 2000, Resolved::Served(r#"{"plan":"paid"}"#.into()), "served")]
    #[case::ahead_of_the_row(Some(stored(5, false, 1000)), 4, 1000, Resolved::Served(r#"{"plan":"paid"}"#.into()), "served")]
    #[case::deleted_at_the_row_version(
        Some(stored(4, true, 1000)),
        4,
        1000,
        Resolved::Gone,
        "deleted"
    )]
    #[case::deleted_ahead_of_the_row(
        Some(stored(5, true, 1000)),
        4,
        1000,
        Resolved::Gone,
        "deleted"
    )]
    #[case::revived_over_a_delete(Some(stored(3, true, 1000)), 4, 2000, Resolved::Served("{}".into()), "revived")]
    #[case::untouched_stub(None, 0, 1000, Resolved::Served("{}".into()), "stub")]
    #[case::missing_record(None, 4, 1000, Resolved::Unavailable, "missing")]
    fn serves_what_slatedb_holds(
        #[case] read: Option<StoredProperties>,
        #[case] row_version: i64,
        #[case] row_created_at: i64,
        #[case] expected: Resolved,
        #[case] outcome: &str,
    ) {
        assert_eq!(
            resolve(Ok(read), row_version, row_created_at),
            (expected, outcome)
        );
    }

    #[rstest]
    #[case::timed_out(PropertyStoreError::Timeout, "timeout")]
    #[case::bad_data(PropertyStoreError::Malformed { team_id: 7, person_id: 1, reason: "short".into() }, "data")]
    #[case::store_down(PropertyStoreError::ShardUnavailable { shard: 0, reason: "down".into() }, "unavailable")]
    fn a_failed_read_is_unavailable_by_cause(
        #[case] error: PropertyStoreError,
        #[case] outcome: &str,
    ) {
        assert_eq!(
            resolve(Err(error), 4, 1000),
            (Resolved::Unavailable, outcome)
        );
    }

    #[test]
    fn keys_that_resolve_to_one_person_share_one_read() {
        let rows = vec![
            ("a", Some((7, 1))),
            ("b", Some((7, 2))),
            ("c", None),
            ("d", Some((7, 1))),
        ];

        let (persons, slots) = dedupe(rows, |person| *person);

        assert_eq!(persons, vec![(7, 1), (7, 2)]);
        assert_eq!(
            slots,
            vec![("a", Some(0)), ("b", Some(1)), ("c", None), ("d", Some(0))]
        );
    }
}
