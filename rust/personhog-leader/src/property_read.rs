use std::sync::Arc;
use std::time::Instant;

use metrics::{counter, histogram};
use personhog_property_store::{
    PropertyReader, PropertyStoreError, StoredProperties, STUB_VERSION,
};
use sqlx::PgPool;

use crate::cache::{CachedPerson, PersonCacheKey};
use crate::pg::load_person_stub_from_pg;

#[derive(Clone)]
pub struct PropertyRead {
    pub reader: Arc<PropertyReader>,
}

#[derive(Debug, PartialEq)]
enum Resolved {
    Served(Vec<u8>),
    Unserved(&'static str),
}

#[derive(Debug, thiserror::Error)]
pub enum LoadError {
    #[error(transparent)]
    Pg(#[from] sqlx::Error),
    #[error("properties unavailable: {0}")]
    Unavailable(&'static str),
    #[error("properties inconsistent: {0}")]
    Inconsistent(&'static str),
}

pub async fn load_person(
    pool: &PgPool,
    table: &str,
    read: &PropertyRead,
    key: &PersonCacheKey,
) -> Result<Option<CachedPerson>, LoadError> {
    // The load holds the person's lock and the person has no dirty mark, so both reads see the
    // same version and their order does not matter.
    let first_read = async {
        let started = Instant::now();
        let first = read.reader.get(key.team_id, key.person_id).await;
        (first, started.elapsed())
    };
    let (stub, (first, first_elapsed)) =
        tokio::join!(load_person_stub_from_pg(pool, table, key), first_read);
    let Some(mut person) = stub? else {
        return Ok(None);
    };
    let started = Instant::now();
    let outcome = match resolve(read, &person, first).await {
        Resolved::Served(properties) => {
            person.properties = properties;
            "served"
        }
        Resolved::Unserved(reason) => reason,
    };
    histogram!("personhog_leader_property_store_read_ms")
        .record((first_elapsed + started.elapsed()).as_secs_f64() * 1000.0);
    counter!("personhog_leader_property_store_reads_total", "outcome" => outcome).increment(1);
    load_outcome(outcome).map(|()| Some(person))
}

/// With no dirty mark, the writer applied every record to both stores, so a store ahead is inconsistent.
fn load_outcome(outcome: &'static str) -> Result<(), LoadError> {
    match outcome {
        "served" => Ok(()),
        "ahead" | "deleted_at_live_version" => Err(LoadError::Inconsistent(outcome)),
        _ => Err(LoadError::Unavailable(outcome)),
    }
}

enum Read {
    Settled(Resolved),
    Unsettled(Resolved),
}

fn judge(read: Result<Option<StoredProperties>, PropertyStoreError>, stub: &CachedPerson) -> Read {
    let unsettled = |reason| Read::Unsettled(Resolved::Unserved(reason));
    match read {
        Ok(Some(stored)) if stored.version == stub.version && stored.deleted => {
            Read::Settled(Resolved::Unserved("deleted_at_live_version"))
        }
        Ok(Some(stored)) if stored.version == stub.version => {
            Read::Settled(Resolved::Served(stored.properties.to_vec()))
        }
        Ok(Some(stored)) if stored.version > stub.version => {
            Read::Settled(Resolved::Unserved("ahead"))
        }
        Ok(Some(_)) => unsettled("behind"),
        Ok(None) if stub.version == STUB_VERSION => Read::Settled(Resolved::Served(b"{}".to_vec())),
        Ok(None) => unsettled("missing"),
        Err(PropertyStoreError::Timeout) => unsettled("timeout"),
        Err(e) => {
            let class = e.class();
            if class == "data" {
                tracing::error!(team_id = stub.team_id, person_id = stub.id, error = %e, "property store read failed");
            } else {
                tracing::debug!(team_id = stub.team_id, person_id = stub.id, error = %e, "property store read failed");
            }
            unsettled(class)
        }
    }
}

async fn resolve(
    read: &PropertyRead,
    stub: &CachedPerson,
    first: Result<Option<StoredProperties>, PropertyStoreError>,
) -> Resolved {
    if let Read::Settled(resolved) = judge(first, stub) {
        return resolved;
    }
    let fresh = read.reader.get_fresh(stub.team_id, stub.id).await;
    if let Ok(Some(stored)) = &fresh {
        if stored.is_revival(stub.version) {
            return Resolved::Served(b"{}".to_vec());
        }
    }
    match judge(fresh, stub) {
        Read::Settled(resolved) | Read::Unsettled(resolved) => resolved,
    }
}

#[cfg(test)]
mod tests {
    use personhog_property_store::bytes::Bytes;
    use personhog_property_store::object_store::local::LocalFileSystem;
    use personhog_property_store::object_store::ObjectStore;
    use personhog_property_store::{
        PartitionKey, PropertyRecord, PropertyStoreConfig, PropertyWriter,
    };

    use std::time::Duration;

    use super::*;

    fn config() -> PropertyStoreConfig {
        PropertyStoreConfig {
            reader_poll_ms: 20,
            ..PropertyStoreConfig::local("props", 1)
        }
    }

    fn stub(version: i64) -> CachedPerson {
        CachedPerson {
            id: 1,
            uuid: String::new(),
            team_id: 7,
            properties: b"{}".to_vec(),
            created_at: 0,
            version,
            is_identified: false,
            is_deleted: false,
            last_seen_at: None,
        }
    }

    async fn resolve_against(stored: Option<(i64, bool)>, stub_version: i64) -> Resolved {
        let dir = tempfile::tempdir().unwrap();
        let store: Arc<dyn ObjectStore> =
            Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
        let writer = PropertyWriter::new(&config(), Arc::clone(&store));
        let partition = PartitionKey {
            topic: Arc::from("changelog"),
            partition: 0,
        };
        writer.assign(&partition, 1, 1, || true).await.unwrap();
        let reader = Arc::new(PropertyReader::new(&config(), store));
        if let Some((version, deleted)) = stored {
            writer
                .put(
                    &partition,
                    1,
                    &[PropertyRecord {
                        team_id: 7,
                        person_id: 1,
                        version,
                        deleted,
                        created_at: 0,
                        properties: Bytes::from_static(br#"{"plan":"paid"}"#),
                    }],
                )
                .await
                .unwrap();
            let deadline = Instant::now() + Duration::from_secs(10);
            while reader.get(7, 1).await.unwrap().is_none() && Instant::now() < deadline {
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
        }
        let first = reader.get(7, 1).await;
        let read = PropertyRead { reader };
        let resolved = resolve(&read, &stub(stub_version), first).await;
        writer.close().await;
        resolved
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn serves_only_the_version_postgres_holds() {
        assert_eq!(
            resolve_against(Some((4, false)), 4).await,
            Resolved::Served(br#"{"plan":"paid"}"#.to_vec())
        );
        assert_eq!(
            resolve_against(Some((3, false)), 4).await,
            Resolved::Unserved("behind")
        );
        assert_eq!(
            resolve_against(Some((5, false)), 4).await,
            Resolved::Unserved("ahead")
        );
        assert_eq!(
            resolve_against(Some((4, true)), 4).await,
            Resolved::Unserved("deleted_at_live_version")
        );
        assert_eq!(
            resolve_against(None, 4).await,
            Resolved::Unserved("missing")
        );
    }

    #[test]
    fn a_failed_read_tells_bad_data_from_an_outage() {
        let malformed = PropertyStoreError::Malformed {
            team_id: 7,
            person_id: 1,
            reason: "short".to_string(),
        };
        let outage = PropertyStoreError::ShardUnavailable {
            shard: 0,
            reason: "down".to_string(),
        };
        assert!(matches!(
            judge(Err(malformed), &stub(4)),
            Read::Unsettled(Resolved::Unserved("data"))
        ));
        assert!(matches!(
            judge(Err(outage), &stub(4)),
            Read::Unsettled(Resolved::Unserved("unavailable"))
        ));
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn serves_a_person_revived_outside_the_changelog_as_empty() {
        assert_eq!(
            resolve_against(Some((3, true)), 4).await,
            Resolved::Served(b"{}".to_vec())
        );
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn serves_an_untouched_identity_stub_as_empty() {
        assert_eq!(
            resolve_against(None, 0).await,
            Resolved::Served(b"{}".to_vec())
        );
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn a_fresh_read_finds_what_a_trailing_reader_has_not_seen() {
        for earlier in [None, Some(3)] {
            let dir = tempfile::tempdir().unwrap();
            let store: Arc<dyn ObjectStore> =
                Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
            let writer = PropertyWriter::new(&config(), Arc::clone(&store));
            let partition = PartitionKey {
                topic: Arc::from("changelog"),
                partition: 0,
            };
            writer.assign(&partition, 1, 1, || true).await.unwrap();
            let record = |person_id, version, deleted| PropertyRecord {
                team_id: 7,
                person_id,
                version,
                deleted,
                created_at: 0,
                properties: Bytes::from_static(br#"{"plan":"paid"}"#),
            };
            let mut first = vec![record(2, 1, false)];
            if let Some(version) = earlier {
                first.push(record(1, version, true));
            }
            writer.put(&partition, 1, &first).await.unwrap();
            // A reader whose polls never land, as when they keep failing.
            let reader = Arc::new(PropertyReader::new(
                &PropertyStoreConfig {
                    reader_poll_ms: 3_600_000,
                    ..config()
                },
                store,
            ));
            assert!(reader.get(7, 2).await.unwrap().is_some());
            tokio::time::sleep(Duration::from_millis(200)).await;
            writer
                .put(&partition, 1, &[record(1, 4, false)])
                .await
                .unwrap();
            let read = PropertyRead {
                reader: Arc::clone(&reader),
            };

            let resolved = resolve(&read, &stub(4), reader.get(7, 1).await).await;

            assert_eq!(
                resolved,
                Resolved::Served(br#"{"plan":"paid"}"#.to_vec()),
                "earlier {earlier:?}"
            );
            assert_eq!(
                reader.get(7, 1).await.unwrap().map(|s| s.version),
                Some(4),
                "the trailing reader is replaced, earlier {earlier:?}"
            );
            writer.close().await;
        }
    }

    #[test]
    fn a_load_reports_a_store_ahead_of_postgres_as_inconsistent() {
        for outcome in ["ahead", "deleted_at_live_version"] {
            assert!(matches!(
                load_outcome(outcome),
                Err(LoadError::Inconsistent(_))
            ));
        }
        for outcome in ["behind", "missing", "timeout", "error"] {
            assert!(matches!(
                load_outcome(outcome),
                Err(LoadError::Unavailable(_))
            ));
        }
        assert!(load_outcome("served").is_ok());
    }
}
