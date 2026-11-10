use std::collections::HashMap;
use std::time::{Duration, Instant};

use anyhow::{Context, Result};
use envconfig::Envconfig;
use personhog_property_store::{
    PropertyReader, PropertyStoreConfig, PropertyStoreError, StoredProperties,
};
use serde_json::json;

use crate::report::ConsistencyViolation;
use crate::state::{verify_properties, ExpectedPerson};

const CATCH_UP: Duration = Duration::from_secs(60);

/// A SlateDB leader loads a person only once the writer applied it, so only `served` is expected.
pub fn load_violations(leaders: &[(String, bool, String)]) -> Vec<ConsistencyViolation> {
    let mut violations = Vec::new();
    for (name, _, page) in leaders.iter().filter(|(_, slatedb, _)| *slatedb) {
        let loads = counters_by_outcome(page, "personhog_leader_property_store_reads_total");
        let unexpected: Vec<(&str, f64)> = loads
            .iter()
            .filter(|(outcome, count)| *outcome != "served" && **count > 0.0)
            .map(|(outcome, count)| (outcome.as_str(), *count))
            .collect();
        if !unexpected.is_empty() {
            violations.push(ConsistencyViolation {
                person_id: 0,
                key: format!("property_loads:{name}"),
                expected: json!({ "outcomes": ["served"] }),
                actual: json!(unexpected),
            });
        }
    }
    violations
}

fn counters_by_outcome(page: &str, metric: &str) -> std::collections::HashMap<String, f64> {
    page.lines()
        .filter_map(|line| {
            let rest = line.strip_prefix(metric)?.strip_prefix("{")?;
            let (labels, value) = rest.split_once("} ")?;
            let outcome = labels
                .split(',')
                .find_map(|label| label.strip_prefix("outcome=\""))?
                .trim_end_matches('"');
            Some((outcome.to_string(), value.trim().parse().ok()?))
        })
        .collect()
}

pub fn store_reader() -> Result<PropertyReader> {
    let config = PropertyStoreConfig::init_from_env().context("property store config")?;
    Ok(PropertyReader::new(
        &config,
        personhog_property_store::object_store(&config)?,
    ))
}

pub async fn verify_store_against_journal(
    reader: &PropertyReader,
    team_id: i64,
    journal: &HashMap<i64, ExpectedPerson>,
) -> Result<Vec<ConsistencyViolation>> {
    let deadline = Instant::now() + CATCH_UP;
    let mut violations = Vec::new();
    for (&person_id, expected) in journal {
        // The writer reaches Postgres before SlateDB and a retried write can journal properties
        // without raising the version, so a read is only final once it matches the journal.
        loop {
            let read = reader.get(team_id, person_id).await;
            let found = judge(person_id, expected, &read)?;
            if found.is_empty() {
                break;
            }
            if Instant::now() > deadline {
                violations.extend(found);
                break;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }
    Ok(violations)
}

/// What one read would report against the journal; nothing means the store has caught up.
fn judge(
    person_id: i64,
    expected: &ExpectedPerson,
    read: &std::result::Result<Option<StoredProperties>, PropertyStoreError>,
) -> Result<Vec<ConsistencyViolation>> {
    if let Ok(Some(stored)) = read {
        if stored.version >= expected.last_version && !stored.deleted {
            let properties: serde_json::Value =
                serde_json::from_slice(&stored.properties).context("parsing stored properties")?;
            return Ok(verify_properties(
                person_id,
                &expected.written_properties,
                &properties,
            ));
        }
    }
    Ok(vec![ConsistencyViolation {
        person_id,
        key: "slatedb".to_string(),
        expected: json!({ "version": format!(">= {}", expected.last_version), "deleted": false }),
        actual: match read {
            Ok(stored) => json!(stored
                .as_ref()
                .map(|s| json!({ "version": s.version, "deleted": s.deleted }))),
            Err(e) => json!({ "error": e.to_string() }),
        },
    }])
}

#[cfg(test)]
mod tests {
    use super::*;

    const PAGE: &str = "\
# TYPE personhog_leader_property_store_reads_total counter
personhog_leader_property_store_reads_total{outcome=\"served\"} 12
personhog_leader_property_store_reads_total{outcome=\"behind\"} 3
";

    #[test]
    fn only_a_slatedb_leaders_unserved_loads_are_violations() {
        for (name, slatedb, expected) in [("slatedb", true, 1), ("postgres", false, 0)] {
            let leaders = [("leader-0".to_string(), slatedb, PAGE.to_string())];
            assert_eq!(load_violations(&leaders).len(), expected, "{name}");
        }
    }

    #[test]
    fn a_read_is_judged_against_the_journal_and_an_error_is_kept() {
        let expected = ExpectedPerson {
            written_properties: HashMap::from([("a".to_string(), json!(1))]),
            last_version: 2,
        };
        let stored = |version, properties: &'static str| StoredProperties {
            version,
            deleted: false,
            created_at: 0,
            properties: personhog_property_store::bytes::Bytes::from_static(properties.as_bytes()),
        };

        assert!(judge(1, &expected, &Ok(Some(stored(2, r#"{"a":1}"#))))
            .unwrap()
            .is_empty());
        let behind = judge(1, &expected, &Ok(Some(stored(1, r#"{"a":1}"#)))).unwrap();
        assert_eq!(behind[0].actual["version"], 1);
        let missing = judge(1, &expected, &Ok(None)).unwrap();
        assert!(missing[0].actual.is_null());
        let wrong = judge(1, &expected, &Ok(Some(stored(2, r#"{"a":2}"#)))).unwrap();
        assert_eq!(wrong.len(), 1);
        let failed = judge(
            1,
            &expected,
            &Err(PropertyStoreError::Malformed {
                team_id: 7,
                person_id: 1,
                reason: "short".into(),
            }),
        )
        .unwrap();
        assert!(failed[0].actual["error"]
            .as_str()
            .unwrap()
            .contains("short"));
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn a_verification_waits_for_the_journalled_properties_not_only_the_version() {
        use std::sync::Arc;

        use personhog_property_store::bytes::Bytes;
        use personhog_property_store::object_store::local::LocalFileSystem;
        use personhog_property_store::object_store::ObjectStore;
        use personhog_property_store::{PartitionKey, PropertyRecord, PropertyWriter};

        let dir = tempfile::tempdir().unwrap();
        let store: Arc<dyn ObjectStore> =
            Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
        let config = PropertyStoreConfig {
            reader_poll_ms: 50,
            ..PropertyStoreConfig::local("props", 1)
        };
        let writer = Arc::new(PropertyWriter::new(&config, Arc::clone(&store)));
        let key = PartitionKey {
            topic: Arc::from("changelog"),
            partition: 0,
        };
        writer.assign(&key, 1, 1, || true).await.unwrap();
        let record = |version, properties: &'static str| PropertyRecord {
            team_id: 7,
            person_id: 1,
            version,
            deleted: false,
            created_at: 0,
            properties: Bytes::from_static(properties.as_bytes()),
        };
        writer
            .put(&key, 1, &[record(1, r#"{"a":1}"#)])
            .await
            .unwrap();
        // A retried write journalled `b` without raising the version; SlateDB gets it a moment later.
        let journal = HashMap::from([(
            1,
            ExpectedPerson {
                written_properties: HashMap::from([
                    ("a".to_string(), json!(1)),
                    ("b".to_string(), json!(2)),
                ]),
                last_version: 1,
            },
        )]);
        let (late, late_key) = (Arc::clone(&writer), key.clone());
        tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(300)).await;
            late.put(&late_key, 1, &[record(2, r#"{"a":1,"b":2}"#)])
                .await
                .unwrap();
        });
        let reader = PropertyReader::new(&config, store);

        let violations = verify_store_against_journal(&reader, 7, &journal)
            .await
            .unwrap();

        assert!(violations.is_empty(), "{} violations", violations.len());
        reader.close().await;
        writer.close().await;
    }
}
