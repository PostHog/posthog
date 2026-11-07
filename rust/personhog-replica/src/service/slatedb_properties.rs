use std::time::Instant;

use futures::future::join_all;
use personhog_property_store::reader::PropertyReader;
use personhog_property_store::{PropertyStoreError, StoredProperties};
use tonic::Status;

use crate::storage::types::Person;

const READS_TOTAL: &str = "personhog_replica_slatedb_property_reads_total";
const READ_MS: &str = "personhog_replica_slatedb_property_read_ms";

#[derive(Debug, PartialEq)]
pub(crate) enum Resolved {
    Served(String),
    /// SlateDB has the delete; the replica's row has not caught up with it.
    Gone,
    Unavailable,
}

/// Eventual reads serve SlateDB's record whatever its version. A person who should
/// have a record but has none fails closed, so a gap never reads as empty properties.
pub(crate) fn resolve(
    read: Result<Option<StoredProperties>, PropertyStoreError>,
    row_version: i64,
) -> (Resolved, &'static str) {
    match read {
        // A delete marker below the live version is an identity revival, which has empty properties.
        Ok(Some(stored)) if stored.deleted && stored.version < row_version => {
            (Resolved::Served("{}".to_string()), "revived")
        }
        Ok(Some(stored)) if stored.deleted => (Resolved::Gone, "deleted"),
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
        // Identity creates stubs at version 0 without a changelog record.
        Ok(None) if row_version == 0 => (Resolved::Served("{}".to_string()), "stub"),
        Ok(None) => (Resolved::Unavailable, "missing"),
        Err(PropertyStoreError::Timeout) => (Resolved::Unavailable, "timeout"),
        Err(e) => {
            tracing::warn!(error = %e, "slatedb property read failed");
            (Resolved::Unavailable, "error")
        }
    }
}

pub(crate) async fn with_properties(
    reader: &PropertyReader,
    mut person: Person,
) -> Result<Option<Person>, Status> {
    let started = Instant::now();
    let read = reader.get(person.team_id, person.id).await;
    common_metrics::histogram(READ_MS, &[], started.elapsed().as_secs_f64() * 1000.0);
    let (resolved, outcome) = resolve(read, person.version.unwrap_or(0));
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
    reader: &PropertyReader,
    persons: Vec<Person>,
) -> Result<Vec<Person>, Status> {
    let read = join_all(
        persons
            .into_iter()
            .map(|person| with_properties(reader, person)),
    )
    .await;
    Ok(read
        .into_iter()
        .collect::<Result<Vec<_>, _>>()?
        .into_iter()
        .flatten()
        .collect())
}

pub(crate) async fn keyed_with_properties<K>(
    reader: &PropertyReader,
    rows: Vec<(K, Option<Person>)>,
) -> Result<Vec<(K, Option<Person>)>, Status> {
    let read = join_all(rows.into_iter().map(|(key, person)| async move {
        let person = match person {
            Some(person) => with_properties(reader, person).await?,
            None => None,
        };
        Ok::<_, Status>((key, person))
    }))
    .await;
    read.into_iter().collect()
}

#[cfg(test)]
mod tests {
    use personhog_property_store::bytes::Bytes;
    use rstest::rstest;

    use super::*;

    fn stored(version: i64, deleted: bool) -> StoredProperties {
        StoredProperties {
            version,
            deleted,
            properties: Bytes::from_static(br#"{"plan":"paid"}"#),
        }
    }

    #[rstest]
    #[case::at_the_row_version(Some(stored(4, false)), 4, Resolved::Served(r#"{"plan":"paid"}"#.into()), "served")]
    #[case::behind_the_row(Some(stored(3, false)), 4, Resolved::Served(r#"{"plan":"paid"}"#.into()), "behind")]
    #[case::ahead_of_the_row(Some(stored(5, false)), 4, Resolved::Served(r#"{"plan":"paid"}"#.into()), "served")]
    #[case::deleted_at_the_row_version(Some(stored(4, true)), 4, Resolved::Gone, "deleted")]
    #[case::deleted_ahead_of_the_row(Some(stored(5, true)), 4, Resolved::Gone, "deleted")]
    #[case::revived_over_a_delete(Some(stored(3, true)), 4, Resolved::Served("{}".into()), "revived")]
    #[case::untouched_stub(None, 0, Resolved::Served("{}".into()), "stub")]
    #[case::missing_record(None, 4, Resolved::Unavailable, "missing")]
    fn serves_what_slatedb_holds(
        #[case] read: Option<StoredProperties>,
        #[case] row_version: i64,
        #[case] expected: Resolved,
        #[case] outcome: &str,
    ) {
        assert_eq!(resolve(Ok(read), row_version), (expected, outcome));
    }

    #[test]
    fn a_timed_out_read_is_unavailable() {
        assert_eq!(
            resolve(Err(PropertyStoreError::Timeout), 4),
            (Resolved::Unavailable, "timeout")
        );
    }
}
