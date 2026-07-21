use std::collections::{HashMap, HashSet};
use std::mem;
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
    /// Acks that broke an invariant at journaling time. The leader
    /// serializes writes per person and bumps the version on every change,
    /// so each version of a person is assigned to at most one acked write;
    /// a duplicate means two writes were served from the same base state
    /// (a stale warm, a stale fallback, or a zombie leader). Arrival order
    /// is deliberately not checked: concurrent writers' acks are recorded
    /// in whatever order the responses land, so a lower version arriving
    /// after a higher one is normal.
    anomalies: Vec<ConsistencyViolation>,
}

pub struct ExpectedPerson {
    /// Only tracks keys the harness wrote — other properties are ignored
    /// during verification.
    pub written_properties: HashMap<String, serde_json::Value>,
    /// Highest version the leader acked for this person.
    pub last_version: i64,
    /// Every version the leader acked for this person, for duplicate
    /// detection.
    acked_versions: HashSet<i64>,
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
                acked_versions: HashSet::new(),
            });
        let duplicate = !entry.acked_versions.insert(version);
        entry.last_version = entry.last_version.max(version);
        for (k, v) in properties {
            entry.written_properties.insert(k, v);
        }
        if duplicate {
            journal.anomalies.push(ConsistencyViolation {
                person_id,
                key: "__ack_version_duplicate".to_string(),
                expected: serde_json::json!("each version acked at most once"),
                actual: serde_json::json!(version),
            });
        }
    }

    /// Journal an ack whose response carried no person body. The write is
    /// acked, so its keys must still be verified like any other — but the
    /// response contract (updates return the updated person) broke, which
    /// is itself flagged as a violation. With no version in the response,
    /// the person's version high-water mark is left untouched.
    pub async fn record_ack_anomaly(
        &self,
        person_id: i64,
        properties: HashMap<String, serde_json::Value>,
    ) {
        let mut journal = self.inner.write().await;
        journal.anomalies.push(ConsistencyViolation {
            person_id,
            key: "__ack_missing_person".to_string(),
            expected: serde_json::json!("update response carries the person"),
            actual: serde_json::Value::Null,
        });
        let entry = journal
            .persons
            .entry(person_id)
            .or_insert_with(|| ExpectedPerson {
                written_properties: HashMap::new(),
                last_version: 0,
                acked_versions: HashSet::new(),
            });
        for (k, v) in properties {
            entry.written_properties.insert(k, v);
        }
    }

    /// Duplicate-version and response anomalies observed while journaling.
    pub async fn take_anomalies(&self) -> Vec<ConsistencyViolation> {
        mem::take(&mut self.inner.write().await.anomalies)
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
        mem::take(&mut journal.persons)
    }
}

/// A false positive here fails good runs; a false negative passes runs
/// that lost data. The e2e gate exercises this on every run but can only
/// reveal false positives — a verifier that misses violations looks
/// identical to a healthy stack — so the decision table is unit-tested.
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

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    fn violation_keys(mut violations: Vec<ConsistencyViolation>) -> Vec<String> {
        violations.sort_by(|a, b| a.key.cmp(&b.key));
        violations.into_iter().map(|v| v.key).collect()
    }

    fn props(entries: &[(&str, &str)]) -> HashMap<String, serde_json::Value> {
        entries
            .iter()
            .map(|(k, v)| (k.to_string(), json!(v)))
            .collect()
    }

    #[test]
    fn verify_properties_flags_exactly_the_missing_and_mismatched_keys() {
        let expected = props(&[("a", "1"), ("b", "2")]);
        let cases: &[(serde_json::Value, &[&str])] = &[
            // Everything acked is present; unrelated keys are ignored.
            (json!({"a": "1", "b": "2", "other": true}), &[]),
            // Present but wrong value.
            (json!({"a": "1", "b": "wrong"}), &["b"]),
            // Acked key absent entirely.
            (json!({"a": "1"}), &["b"]),
            // Non-object properties lose every acked key.
            (json!(null), &["a", "b"]),
        ];
        for (actual, expected_keys) in cases {
            let got = violation_keys(verify_properties(1, &expected, actual));
            assert_eq!(got, *expected_keys, "actual={actual}");
        }
    }

    #[tokio::test]
    async fn journal_merges_keys_and_keeps_the_max_acked_version() {
        let state = PersonState::new();
        state.record_write(1, 1, props(&[("k1", "v1")])).await;
        state.record_write(1, 2, props(&[("k2", "v2")])).await;

        assert!(state.take_anomalies().await.is_empty());
        let snapshot = state.snapshot().await;
        let person = &snapshot[&1];
        assert_eq!(person.last_version, 2);
        assert_eq!(person.written_properties.len(), 2);
    }

    #[tokio::test]
    async fn out_of_order_acks_are_benign_and_max_is_kept() {
        let state = PersonState::new();
        state.record_write(1, 5, props(&[("k1", "v1")])).await;
        state.record_write(1, 3, props(&[("k2", "v2")])).await;

        // Concurrent writers' acks land in arbitrary order; distinct
        // versions arriving out of order are not an anomaly.
        assert!(state.take_anomalies().await.is_empty());
        let snapshot = state.snapshot().await;
        let person = &snapshot[&1];
        assert_eq!(person.last_version, 5);
        assert!(person.written_properties.contains_key("k2"));
    }

    #[tokio::test]
    async fn duplicate_acked_version_is_flagged_and_both_keys_journaled() {
        let state = PersonState::new();
        state.record_write(1, 5, props(&[("k1", "v1")])).await;
        state.record_write(1, 5, props(&[("k2", "v2")])).await;

        assert_eq!(
            violation_keys(state.take_anomalies().await),
            vec!["__ack_version_duplicate"]
        );
        // Drained on take, and both acked writes' keys stay journaled for
        // end-of-run verification.
        assert!(state.take_anomalies().await.is_empty());
        let snapshot = state.snapshot().await;
        let person = &snapshot[&1];
        assert_eq!(person.last_version, 5);
        assert!(person.written_properties.contains_key("k1"));
        assert!(person.written_properties.contains_key("k2"));
    }

    #[tokio::test]
    async fn ack_without_person_is_flagged_and_its_keys_still_journaled() {
        let state = PersonState::new();
        state.record_write(1, 5, props(&[("k1", "v1")])).await;
        state.record_ack_anomaly(1, props(&[("k2", "v2")])).await;

        assert_eq!(
            violation_keys(state.take_anomalies().await),
            vec!["__ack_missing_person"]
        );
        let snapshot = state.snapshot().await;
        let person = &snapshot[&1];
        assert_eq!(person.last_version, 5, "anomaly must not move the version");
        assert!(person.written_properties.contains_key("k2"));
    }

    #[tokio::test]
    async fn strong_read_below_max_acked_version_is_a_violation() {
        let state = PersonState::new();
        state.record_write(1, 5, props(&[("k", "v")])).await;
        let actual = json!({"k": "v"});

        assert!(state.verify(1, &actual, 5).await.is_empty());
        assert!(state.verify(1, &actual, 6).await.is_empty());
        assert_eq!(
            violation_keys(state.verify(1, &actual, 4).await),
            vec!["__strong_read_version"]
        );
        // Unjournaled persons have nothing to verify against.
        assert!(state.verify(2, &actual, 0).await.is_empty());
    }
}
