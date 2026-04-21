use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;

use crate::report::ConsistencyViolation;

#[derive(Clone)]
pub struct PersonState {
    inner: Arc<RwLock<HashMap<i64, ExpectedPerson>>>,
}

struct ExpectedPerson {
    /// Only tracks keys that the cannon wrote — other properties are ignored during verification.
    written_properties: HashMap<String, serde_json::Value>,
    last_version: i64,
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
        if version >= entry.last_version {
            entry.last_version = version;
            for (k, v) in properties {
                entry.written_properties.insert(k, v);
            }
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

        let actual_map = actual_properties.as_object();
        let mut violations = Vec::new();

        for (key, expected_val) in &expected.written_properties {
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

    pub async fn person_ids(&self) -> Vec<i64> {
        self.inner.read().await.keys().copied().collect()
    }
}
