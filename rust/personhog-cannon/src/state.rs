use std::collections::HashMap;
use std::sync::Arc;

use tokio::sync::RwLock;

use crate::report::ConsistencyViolation;

/// Journal of acked writes. Every property write acked by the leader path is
/// recorded here; verification asserts each one is visible afterwards. Keys
/// are unique per write, so the final state must contain every acked key
/// regardless of the interleaving of concurrent writers.
#[derive(Clone)]
pub struct PersonState {
    inner: Arc<RwLock<Journal>>,
}

#[derive(Default)]
struct Journal {
    persons: HashMap<i64, ExpectedPerson>,
    /// Acks whose version regressed below an earlier ack for the same
    /// person. The leader serializes writes per person and bumps the
    /// version on every change, so an ack observing a lower version means
    /// the version chain went backwards (e.g. a zombie or a stale warm).
    regressions: Vec<ConsistencyViolation>,
}

pub struct ExpectedPerson {
    /// Only tracks keys the cannon wrote — other properties are ignored
    /// during verification.
    pub written_properties: HashMap<String, serde_json::Value>,
    /// Highest version the leader acked for this person.
    pub last_version: i64,
}

impl PersonState {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(RwLock::new(Journal::default())),
        }
    }

    pub async fn record_write(
        &self,
        person_id: i64,
        version: i64,
        properties: HashMap<String, serde_json::Value>,
    ) {
        let mut journal = self.inner.write().await;
        let entry = journal
            .persons
            .entry(person_id)
            .or_insert_with(|| ExpectedPerson {
                written_properties: HashMap::new(),
                last_version: 0,
            });
        if version < entry.last_version {
            let last_version = entry.last_version;
            journal.regressions.push(ConsistencyViolation {
                person_id,
                key: "__ack_version_regression".to_string(),
                expected: serde_json::json!(format!(">= {last_version}")),
                actual: serde_json::json!(version),
            });
        } else {
            entry.last_version = version;
        }
        let entry = journal
            .persons
            .get_mut(&person_id)
            .expect("entry inserted above");
        for (k, v) in properties {
            entry.written_properties.insert(k, v);
        }
    }

    /// Ack-version regressions observed while journaling.
    pub async fn take_regressions(&self) -> Vec<ConsistencyViolation> {
        std::mem::take(&mut self.inner.write().await.regressions)
    }

    /// Verify a strong read against the journal: every acked property must
    /// be present, and the observed version must not sit below the highest
    /// acked version.
    pub async fn verify(
        &self,
        person_id: i64,
        actual_properties: &serde_json::Value,
        observed_version: i64,
    ) -> Vec<ConsistencyViolation> {
        let journal = self.inner.read().await;
        let Some(expected) = journal.persons.get(&person_id) else {
            return vec![];
        };
        let mut violations =
            verify_properties(person_id, &expected.written_properties, actual_properties);
        if observed_version < expected.last_version {
            violations.push(ConsistencyViolation {
                person_id,
                key: "__strong_read_version".to_string(),
                expected: serde_json::json!(format!(">= {}", expected.last_version)),
                actual: serde_json::json!(observed_version),
            });
        }
        violations
    }

    pub async fn person_ids(&self) -> Vec<i64> {
        self.inner.read().await.persons.keys().copied().collect()
    }

    /// Drain the journal into a plain map for offline (Postgres) verification.
    pub async fn snapshot(&self) -> HashMap<i64, ExpectedPerson> {
        let mut journal = self.inner.write().await;
        std::mem::take(&mut journal.persons)
    }
}

pub fn verify_properties(
    person_id: i64,
    expected: &HashMap<String, serde_json::Value>,
    actual_properties: &serde_json::Value,
) -> Vec<ConsistencyViolation> {
    let actual_map = actual_properties.as_object();
    let mut violations = Vec::new();

    for (key, expected_val) in expected {
        let actual_val = actual_map.and_then(|m| m.get(key));
        match actual_val {
            Some(val) if val == expected_val => {}
            Some(val) => {
                violations.push(ConsistencyViolation {
                    person_id,
                    key: key.clone(),
                    expected: expected_val.clone(),
                    actual: val.clone(),
                });
            }
            None => {
                violations.push(ConsistencyViolation {
                    person_id,
                    key: key.clone(),
                    expected: expected_val.clone(),
                    actual: serde_json::Value::Null,
                });
            }
        }
    }

    violations
}
