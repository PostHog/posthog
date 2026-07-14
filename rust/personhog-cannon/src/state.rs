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
    inner: Arc<RwLock<HashMap<i64, ExpectedPerson>>>,
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
            inner: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    pub async fn record_write(
        &self,
        person_id: i64,
        version: i64,
        properties: HashMap<String, serde_json::Value>,
    ) {
        let mut state = self.inner.write().await;
        let entry = state.entry(person_id).or_insert_with(|| ExpectedPerson {
            written_properties: HashMap::new(),
            last_version: 0,
        });
        entry.last_version = entry.last_version.max(version);
        for (k, v) in properties {
            entry.written_properties.insert(k, v);
        }
    }

    pub async fn verify(
        &self,
        person_id: i64,
        actual_properties: &serde_json::Value,
    ) -> Vec<ConsistencyViolation> {
        let state = self.inner.read().await;
        let Some(expected) = state.get(&person_id) else {
            return vec![];
        };
        verify_properties(person_id, &expected.written_properties, actual_properties)
    }

    pub async fn person_ids(&self) -> Vec<i64> {
        self.inner.read().await.keys().copied().collect()
    }

    /// Drain the journal into a plain map for offline (Postgres) verification.
    pub async fn snapshot(&self) -> HashMap<i64, ExpectedPerson> {
        let mut state = self.inner.write().await;
        std::mem::take(&mut *state)
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
