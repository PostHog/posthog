use std::collections::{HashMap, HashSet};
use std::mem;
use std::sync::Arc;

use tokio::sync::RwLock;

use crate::report::ConsistencyViolation;

/// Journal of acked writes. Every property write acked by the leader path is
/// recorded here; verification asserts each one is visible afterwards.
///
/// Keys are reused, so the journal is only authoritative because each key
/// belongs to one worker and workers write sequentially. A write whose
/// outcome is unknown breaks that and drops its key — see
/// [`PersonState::record_write_uncertain`].
///
/// Merges make the journal a tree. Each person keeps the keys its own
/// acks set. A merged source hangs off the survivor its ack named. A
/// live person's expected document is folded from that tree, so a late
/// ack for a merged person only updates that person's own keys.
#[derive(Clone)]
pub struct PersonState {
    inner: Arc<RwLock<Journal>>,
}

#[derive(Default)]
struct Journal {
    /// Every journaled person, alive or merged. A merged person keeps
    /// its node because its keys fold into the survivor.
    persons: HashMap<i64, PersonNode>,
    /// Persons currently frozen by a lifecycle fence, mapped to their
    /// sealed version. While a person is here, no write above the sealed
    /// version may be acked — the fence's whole guarantee. Writes acked at
    /// or below the sealed version are pre-fence acks whose responses
    /// landed late, not violations.
    fenced: HashMap<i64, i64>,
    /// Acks that broke an invariant at journaling time. The leader
    /// serializes writes per person and bumps the version on every change,
    /// so each version of a person is assigned to at most one acked write;
    /// a duplicate means two writes were served from the same base state
    /// (a stale warm, a stale fallback, or a zombie leader). Arrival order
    /// is deliberately not checked: concurrent writers' acks are recorded
    /// in whatever order the responses land, so a lower version arriving
    /// after a higher one is normal.
    anomalies: Vec<ConsistencyViolation>,
    /// The tree's edges, keyed by the merged source. An edge points at
    /// the survivor the ack named, even when that survivor is merged
    /// already, because the fold happened into that person's document
    /// at that person's version.
    merged: HashMap<i64, MergeEdge>,
    /// The reverse of `merged`: the sources folded into each person.
    children: HashMap<i64, Vec<i64>>,
    /// Sources with a merge call in flight. A read that cannot find one
    /// of these is the saga at work, not lost data.
    merge_pending: HashSet<i64>,
}

struct MergeEdge {
    survivor: i64,
    /// The survivor version the fold produced. Folds into one survivor
    /// fill keys in this order.
    fold_version: i64,
    /// Position among the sources of one call. The leader fills from
    /// them in request order.
    ordinal: usize,
}

/// What the journal keeps about a person after a merge destroyed it.
pub struct MergedSource {
    /// The person the source folded into, as answered by the merge ack.
    /// A later merge can destroy it too.
    pub survivor: i64,
    /// Highest version the leader acked for the source, before or after
    /// the merge was journaled. The fence seals the source at its
    /// current version, so every ack must sit at or below the sealed
    /// version the saga recorded. An ack above the seal means the fence
    /// failed open.
    pub max_acked_version: i64,
}

impl MergedSource {
    #[cfg(test)]
    pub fn for_test(survivor: i64, max_acked_version: i64) -> Self {
        Self {
            survivor,
            max_acked_version,
        }
    }
}

/// A MergePersons ack: the sources it merged, in request order, and the
/// survivor's version. `set` overrides on the survivor after the fold.
/// `set_once` fills only keys still absent after that.
pub struct MergeAck {
    pub survivor: i64,
    pub survivor_version: i64,
    pub sources: Vec<i64>,
    pub set: HashMap<String, serde_json::Value>,
    pub set_once: HashMap<String, serde_json::Value>,
}

/// A live person's expected document, for verification.
#[derive(Clone)]
pub struct ExpectedPerson {
    /// Only tracks keys the harness wrote — other properties are ignored
    /// during verification.
    pub written_properties: HashMap<String, serde_json::Value>,
    /// Highest version the leader acked for this person.
    pub last_version: i64,
}

/// The keys a person's own acks set.
struct PersonNode {
    own: HashMap<String, serde_json::Value>,
    last_version: i64,
    /// Every version the leader acked for this person, for duplicate
    /// detection.
    acked_versions: HashSet<i64>,
    /// Keys whose last write errored. Such a write can still apply, so
    /// the person can hold a value the journal does not know. A merge
    /// fold must not assert a source's value for such a key, because
    /// the target wins every key it actually has, known to the journal
    /// or not. The next ack for the key clears it.
    uncertain_keys: HashSet<String>,
    /// The ack version that last set each key. Diagnostics only.
    own_origins: HashMap<String, i64>,
}

impl PersonNode {
    fn empty() -> Self {
        Self {
            own: HashMap::new(),
            last_version: 0,
            acked_versions: HashSet::new(),
            uncertain_keys: HashSet::new(),
            own_origins: HashMap::new(),
        }
    }

    fn insert_acked(&mut self, properties: HashMap<String, serde_json::Value>) {
        self.insert_acked_at(properties, None);
    }

    fn insert_acked_at(
        &mut self,
        properties: HashMap<String, serde_json::Value>,
        version: Option<i64>,
    ) {
        for (k, v) in properties {
            self.uncertain_keys.remove(&k);
            match version {
                Some(version) => {
                    self.own_origins.insert(k.clone(), version);
                }
                None => {
                    self.own_origins.remove(&k);
                }
            }
            self.own.insert(k, v);
        }
    }

    /// Claim `version`. False when an earlier ack already claimed it.
    fn claim_version(&mut self, version: i64) -> bool {
        self.last_version = self.last_version.max(version);
        self.acked_versions.insert(version)
    }
}

/// How the journal came by its expectation for a key.
enum Origin {
    Own(Option<i64>),
    Fold { source: i64, fold_version: i64 },
}

/// A person's document as the fold builds it: own keys first, then each
/// merged source in fold order, filling only absent keys.
#[derive(Default)]
struct Folded {
    properties: HashMap<String, serde_json::Value>,
    /// Keys the person can hold from an errored write. Neither asserted
    /// nor filled from a source.
    uncertain: HashSet<String>,
    origins: HashMap<String, Origin>,
}

impl Journal {
    /// Follow the merge chain to the person that holds `person_id`'s
    /// document now.
    fn resolve(&self, mut person_id: i64) -> i64 {
        let mut hops = 0;
        while let Some(edge) = self.merged.get(&person_id) {
            person_id = edge.survivor;
            hops += 1;
            if hops > self.merged.len() {
                unreachable!("merge chain cycles: a person cannot survive its own merge");
            }
        }
        person_id
    }

    fn node(&mut self, person_id: i64) -> &mut PersonNode {
        self.persons
            .entry(person_id)
            .or_insert_with(PersonNode::empty)
    }

    fn is_live(&self, person_id: i64) -> bool {
        !self.merged.contains_key(&person_id)
    }

    /// The leader's fold rule: a person wins every key its own acks set,
    /// and merged sources fill the rest in fold order. A source is
    /// folded the same way first, because that is the document its seal
    /// carried.
    fn fold(&self, person_id: i64) -> Folded {
        let mut doc = Folded::default();
        if let Some(node) = self.persons.get(&person_id) {
            for (k, v) in &node.own {
                doc.origins
                    .insert(k.clone(), Origin::Own(node.own_origins.get(k).copied()));
                doc.properties.insert(k.clone(), v.clone());
            }
            doc.uncertain = node.uncertain_keys.clone();
        }
        let mut sources: Vec<(i64, usize, i64)> = self
            .children
            .get(&person_id)
            .map(|children| {
                children
                    .iter()
                    .map(|&source| {
                        let edge = &self.merged[&source];
                        (edge.fold_version, edge.ordinal, source)
                    })
                    .collect()
            })
            .unwrap_or_default();
        sources.sort_unstable();
        for (fold_version, _, source) in sources {
            let folded = self.fold(source);
            for (k, v) in folded.properties {
                if doc.properties.contains_key(&k) || doc.uncertain.contains(&k) {
                    continue;
                }
                doc.origins.insert(
                    k.clone(),
                    Origin::Fold {
                        source,
                        fold_version,
                    },
                );
                doc.properties.insert(k, v);
            }
            for k in folded.uncertain {
                if !doc.properties.contains_key(&k) {
                    doc.uncertain.insert(k);
                }
            }
        }
        doc
    }
}

impl PersonState {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(RwLock::new(Journal::default())),
        }
    }

    /// Journal an ack that applied a change. Only these acks claim their
    /// version: the leader assigns each applied update a fresh version
    /// under the per-person lock, so two applied acks sharing one version
    /// means two writes served from the same base state — the split-brain
    /// signature the duplicate check exists to catch. An ack for a merged
    /// person is a pre-seal write whose response landed late. It joins
    /// that person's own keys and raises the version its tombstone must
    /// sit above.
    pub async fn record_write(
        &self,
        person_id: i64,
        version: i64,
        properties: HashMap<String, serde_json::Value>,
    ) {
        let mut journal = self.inner.write().await;
        let entry = journal.node(person_id);
        let duplicate = !entry.claim_version(version);
        entry.insert_acked_at(properties, Some(version));
        if duplicate {
            journal.anomalies.push(ConsistencyViolation {
                person_id,
                key: "__ack_version_duplicate".to_string(),
                expected: serde_json::json!("each version acked at most once"),
                actual: serde_json::json!(version),
            });
        }
        if let Some(&sealed) = journal.fenced.get(&person_id) {
            // A fenced person must reject writes; an ack above the sealed
            // version means the fence failed open (leader amnesia, a
            // fail-open check, a lost fence record). Acks at or below the
            // seal raced the fence and were processed before it.
            if version > sealed {
                journal.anomalies.push(ConsistencyViolation {
                    person_id,
                    key: "__acked_write_while_fenced".to_string(),
                    expected: serde_json::json!(format!("no acked version above seal {sealed}")),
                    actual: serde_json::json!(version),
                });
            }
        }
    }

    /// Open a fence window: from now until `close_fence`, any write acked
    /// above `sealed_version` is a violation. Call after the fence ack (the
    /// sealed version is only known then).
    pub async fn open_fence(&self, person_id: i64, sealed_version: i64) {
        self.inner
            .write()
            .await
            .fenced
            .insert(person_id, sealed_version);
    }

    /// Close a fence window. Call *before* issuing the release so a write
    /// racing the release's ack cannot be flagged as a phantom violation;
    /// the coverage lost is only the release call's own duration.
    pub async fn close_fence(&self, person_id: i64) {
        self.inner.write().await.fenced.remove(&person_id);
    }

    /// Journal an ack whose response reported no change applied. The data
    /// is durable — the keys were already present, so they verify like any
    /// other write — but the echoed version belongs to whichever earlier
    /// write set it, not to this one, so no version is claimed. This is
    /// the at-least-once replay shape: a redelivered write whose first
    /// application succeeded echoes the person's current version, which a
    /// concurrent writer may legitimately own.
    pub async fn record_write_no_change(
        &self,
        person_id: i64,
        properties: HashMap<String, serde_json::Value>,
    ) {
        self.inner
            .write()
            .await
            .node(person_id)
            .insert_acked(properties);
    }

    /// Drop a key whose write errored: the write can still apply, so the
    /// journalled value could be superseded and asserting it would fail
    /// a correct stack. The next ack for the key restores coverage. For
    /// a merged source the taint folds into the survivor, because the
    /// write can have landed before the seal.
    pub async fn record_write_uncertain(&self, person_id: i64, key: &str) {
        let mut journal = self.inner.write().await;
        if let Some(entry) = journal.persons.get_mut(&person_id) {
            entry.own.remove(key);
            entry.uncertain_keys.insert(key.to_string());
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
        journal.node(person_id).insert_acked(properties);
    }

    /// Reserve a source for an in-flight merge call. Until
    /// [`PersonState::record_merge`] or [`PersonState::clear_merge_pending`],
    /// a read that cannot find the person is the saga's doing.
    pub async fn mark_merge_pending(&self, source_id: i64) {
        self.inner.write().await.merge_pending.insert(source_id);
    }

    /// The merge call settled without destroying the source.
    pub async fn clear_merge_pending(&self, source_id: i64) {
        self.inner.write().await.merge_pending.remove(&source_id);
    }

    /// Whether a not-found for this person is expected: a merge is in
    /// flight for it, or one already destroyed it.
    pub async fn is_merge_pending_or_merged(&self, person_id: i64) -> bool {
        let journal = self.inner.read().await;
        journal.merge_pending.contains(&person_id) || journal.merged.contains_key(&person_id)
    }

    /// Journal a merge ack. Each source hangs off the named survivor from
    /// here, so the survivor's document folds the sources' keys: the
    /// survivor wins every key it has, and the sources fill the rest in
    /// request order. Then `set` overrides and `set_once` fills the keys
    /// still absent. The folded version is claimed on the named
    /// survivor, even when a later merge's ack already merged that
    /// person. From here every source must be gone.
    pub async fn record_merge(&self, ack: MergeAck) {
        let mut journal = self.inner.write().await;
        let mut ordinal = 0;
        for source in ack.sources {
            journal.merge_pending.remove(&source);
            let survives_itself = source == ack.survivor || journal.resolve(ack.survivor) == source;
            if journal.merged.contains_key(&source) || survives_itself {
                journal.anomalies.push(ConsistencyViolation {
                    person_id: source,
                    key: "__merged_twice".to_string(),
                    expected: serde_json::json!("a person is destroyed by at most one merge"),
                    actual: serde_json::json!(ack.survivor),
                });
                continue;
            }
            journal.node(source);
            journal.merged.insert(
                source,
                MergeEdge {
                    survivor: ack.survivor,
                    fold_version: ack.survivor_version,
                    ordinal,
                },
            );
            journal
                .children
                .entry(ack.survivor)
                .or_default()
                .push(source);
            ordinal += 1;
        }
        // The fold must include the sources attached above before
        // `set_once` is checked.
        let folded = journal.fold(ack.survivor);
        let entry = journal.node(ack.survivor);
        entry.insert_acked_at(ack.set, Some(ack.survivor_version));
        for (key, value) in ack.set_once {
            let present = entry.own.contains_key(&key)
                || folded.properties.contains_key(&key)
                || folded.uncertain.contains(&key);
            if present {
                continue;
            }
            entry.insert_acked_at(HashMap::from([(key, value)]), Some(ack.survivor_version));
        }
        if !entry.claim_version(ack.survivor_version) {
            journal.anomalies.push(ConsistencyViolation {
                person_id: ack.survivor,
                key: "__ack_version_duplicate".to_string(),
                expected: serde_json::json!("each version acked at most once"),
                actual: serde_json::json!(ack.survivor_version),
            });
        }
    }

    /// A merge call for `source_id` lost every response. The saga can
    /// still destroy the person. The person stays reserved until the op
    /// record settles it: `record_merge` when the merge ran,
    /// `clear_merge_pending` when it did not.
    pub async fn record_merge_uncertain(&self, source_id: i64) {
        self.inner.write().await.merge_pending.insert(source_id);
    }

    /// Persons whose merge call never answered.
    pub async fn merge_uncertain_ids(&self) -> Vec<i64> {
        self.inner
            .read()
            .await
            .merge_pending
            .iter()
            .copied()
            .collect()
    }

    /// Persons destroyed by a journaled merge.
    pub async fn merged_source_ids(&self) -> Vec<i64> {
        self.inner.read().await.merged.keys().copied().collect()
    }

    /// The merged-source records for offline (Postgres) verification.
    pub async fn snapshot_merged(&self) -> HashMap<i64, MergedSource> {
        let journal = self.inner.read().await;
        journal
            .merged
            .iter()
            .map(|(id, edge)| {
                (
                    *id,
                    MergedSource {
                        survivor: edge.survivor,
                        max_acked_version: journal
                            .persons
                            .get(id)
                            .map(|node| node.last_version)
                            .unwrap_or_default(),
                    },
                )
            })
            .collect()
    }

    /// Duplicate-version and response anomalies observed while journaling.
    pub async fn take_anomalies(&self) -> Vec<ConsistencyViolation> {
        mem::take(&mut self.inner.write().await.anomalies)
    }

    /// Verify a strong read against the journal: every acked property must
    /// be present, and the observed version must not sit below the highest
    /// acked version. A merged person has nothing to verify: its document
    /// lives on in the survivor.
    pub async fn verify(
        &self,
        person_id: i64,
        actual_properties: &serde_json::Value,
        observed_version: i64,
    ) -> Vec<ConsistencyViolation> {
        let journal = self.inner.read().await;
        if !journal.is_live(person_id) {
            return vec![];
        }
        let Some(node) = journal.persons.get(&person_id) else {
            return vec![];
        };
        let folded = journal.fold(person_id);
        let mut violations = verify_properties(person_id, &folded.properties, actual_properties);
        if observed_version < node.last_version {
            violations.push(ConsistencyViolation {
                person_id,
                key: "__strong_read_version".to_string(),
                expected: serde_json::json!(format!(">= {}", node.last_version)),
                actual: serde_json::json!(observed_version),
            });
        }
        violations
    }

    /// A diagnostic account of a person's journal: its versions, the
    /// merges that fed it, and where each of `keys` came from.
    pub async fn describe(&self, person_id: i64, keys: &[String]) -> String {
        let journal = self.inner.read().await;
        let mut lines = Vec::new();
        let mut sources: Vec<String> = journal
            .merged
            .iter()
            .filter(|(_, edge)| journal.resolve(edge.survivor) == person_id)
            .map(|(source, edge)| {
                let max_acked = journal
                    .persons
                    .get(source)
                    .map(|node| node.last_version)
                    .unwrap_or_default();
                format!(
                    "{source} (into {} at v{}, max acked v{max_acked})",
                    edge.survivor, edge.fold_version
                )
            })
            .collect();
        sources.sort();
        match journal.persons.get(&person_id) {
            Some(node) => {
                let folded = journal.fold(person_id);
                lines.push(format!(
                    "person {person_id}: last acked v{}, {} keys, merged sources: [{}]",
                    node.last_version,
                    folded.properties.len(),
                    sources.join(", ")
                ));
                for key in keys {
                    let origin = match folded.origins.get(key) {
                        Some(Origin::Own(Some(version))) => format!("own ack v{version}"),
                        Some(Origin::Own(None)) => "own no-change ack".to_string(),
                        Some(Origin::Fold {
                            source,
                            fold_version,
                        }) => format!("fold from person {source} at v{fold_version}"),
                        None if folded.uncertain.contains(key) => {
                            "uncertain: the last write errored".to_string()
                        }
                        None => "not journaled".to_string(),
                    };
                    lines.push(format!("  {key}: {origin}"));
                }
            }
            None => lines.push(format!("person {person_id}: not in the journal")),
        }
        lines.join("\n")
    }

    /// The journaled persons that no merge destroyed.
    pub async fn person_ids(&self) -> Vec<i64> {
        let journal = self.inner.read().await;
        journal
            .persons
            .keys()
            .copied()
            .filter(|&id| journal.is_live(id))
            .collect()
    }

    /// The live persons' expected documents, for offline (Postgres)
    /// verification.
    pub async fn snapshot(&self) -> HashMap<i64, ExpectedPerson> {
        let journal = self.inner.read().await;
        journal
            .persons
            .iter()
            .filter(|(&id, _)| journal.is_live(id))
            .map(|(&id, node)| {
                (
                    id,
                    ExpectedPerson {
                        written_properties: journal.fold(id).properties,
                        last_version: node.last_version,
                    },
                )
            })
            .collect()
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

    /// A single-source merge with a `$set` and no `$set_once`.
    fn merge(source: i64, survivor: i64, survivor_version: i64, set: &[(&str, &str)]) -> MergeAck {
        MergeAck {
            survivor,
            survivor_version,
            sources: vec![source],
            set: props(set),
            set_once: HashMap::new(),
        }
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

    /// A no-change ack (an at-least-once replay echo) must journal its
    /// keys without claiming the echoed version — otherwise a replay
    /// racing a concurrent writer manufactures a false duplicate-version
    /// violation. A real duplicate (two applied acks, one version) must
    /// still be flagged.
    #[tokio::test]
    async fn no_change_acks_journal_keys_without_claiming_versions() {
        let state = PersonState::new();
        state.record_write(1, 41, props(&[("k1", "v1")])).await;
        // The replay echo: version 41 is current, but this ack applied
        // nothing. No violation, keys merged.
        state
            .record_write_no_change(1, props(&[("k2", "v2")]))
            .await;
        assert!(state.take_anomalies().await.is_empty());
        let snapshot = state.snapshot().await;
        let entry = &snapshot[&1];
        assert_eq!(entry.written_properties.len(), 2);
        assert_eq!(entry.last_version, 41);

        // Two applied acks sharing a version stay a violation.
        let state = PersonState::new();
        state.record_write(2, 41, props(&[("a", "1")])).await;
        state.record_write(2, 41, props(&[("b", "2")])).await;
        let anomalies = state.take_anomalies().await;
        assert_eq!(anomalies.len(), 1);
        assert_eq!(anomalies[0].key, "__ack_version_duplicate");
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
    async fn acked_writes_above_the_seal_are_violations_only_while_fenced() {
        let state = PersonState::new();

        // Pre-fence ack: no window open, nothing flagged.
        state.record_write(1, 4, props(&[("k1", "v1")])).await;

        state.open_fence(1, 5).await;
        // An ack at or below the seal raced the fence (processed before it).
        state.record_write(1, 5, props(&[("k2", "v2")])).await;
        assert!(state.take_anomalies().await.is_empty());
        // An ack above the seal means the fence failed open.
        state.record_write(1, 6, props(&[("k3", "v3")])).await;
        assert_eq!(
            violation_keys(state.take_anomalies().await),
            vec!["__acked_write_while_fenced"]
        );
        // Another person is unaffected by this person's fence.
        state.record_write(2, 100, props(&[("k", "v")])).await;
        assert!(state.take_anomalies().await.is_empty());

        state.close_fence(1).await;
        // Post-release writes above the old seal are normal life again.
        state.record_write(1, 7, props(&[("k4", "v4")])).await;
        assert!(state.take_anomalies().await.is_empty());

        // The flagged write stays journaled: it was acked, so end-of-run
        // verification must still hold it visible.
        let snapshot = state.snapshot().await;
        assert!(snapshot[&1].written_properties.contains_key("k3"));
    }

    /// With keys reused, a write that errored but still applied would
    /// overwrite a journalled value and manufacture a violation against a
    /// correct stack. Dropping the key is what makes reuse safe, and the
    /// next ack has to bring it back or coverage decays over a run.
    #[tokio::test]
    async fn an_uncertain_write_drops_its_key_until_the_next_ack() {
        let state = PersonState::new();
        state
            .record_write(1, 1, props(&[("k1", "v1"), ("k2", "v2")]))
            .await;

        state.record_write_uncertain(1, "k1").await;
        // k1 can no longer be asserted; k2 is untouched.
        assert!(state
            .verify(1, &json!({"k1": "raced", "k2": "v2"}), 1)
            .await
            .is_empty());
        assert_eq!(
            violation_keys(state.verify(1, &json!({"k1": "raced"}), 1).await),
            vec!["k2"]
        );

        // A later ack restores the key, and it verifies again.
        state.record_write(1, 2, props(&[("k1", "v3")])).await;
        assert_eq!(
            violation_keys(
                state
                    .verify(1, &json!({"k1": "stale", "k2": "v2"}), 2)
                    .await
            ),
            vec!["k1"]
        );
        assert!(state.take_anomalies().await.is_empty());
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

    /// The fold rule the survivor's journal must mirror: the survivor
    /// keeps every key it has, the source fills the rest, the merge
    /// event's own $set overrides, and the folded version is claimed. A
    /// journal that let the source overwrite the survivor's keys would
    /// flag a correct stack. One that dropped the source's keys would
    /// pass a fold that lost them.
    #[tokio::test]
    async fn a_merge_folds_the_source_into_the_survivor_target_wins() {
        let state = PersonState::new();
        state
            .record_write(1, 3, props(&[("shared", "target"), ("t_only", "t")]))
            .await;
        state
            .record_write(2, 7, props(&[("shared", "source"), ("s_only", "s")]))
            .await;

        state.mark_merge_pending(2).await;
        assert!(state.is_merge_pending_or_merged(2).await);
        state
            .record_merge(merge(2, 1, 8, &[("harness_merge", "op")]))
            .await;
        assert!(state.take_anomalies().await.is_empty());
        assert!(state.is_merge_pending_or_merged(2).await);

        // The source no longer verifies as a live person. The survivor
        // holds the folded document.
        assert_eq!(state.person_ids().await, vec![1]);
        assert_eq!(state.merged_source_ids().await, vec![2]);
        let folded = json!({
            "shared": "target", "t_only": "t", "s_only": "s", "harness_merge": "op"
        });
        assert!(state.verify(1, &folded, 8).await.is_empty());
        assert!(state.verify(2, &json!({}), 0).await.is_empty());
        assert_eq!(
            violation_keys(
                state
                    .verify(
                        1,
                        &json!({"shared": "source", "t_only": "t", "harness_merge": "op"}),
                        8
                    )
                    .await
            ),
            vec!["s_only", "shared"]
        );
        // The folded version is an ack of the survivor.
        assert_eq!(
            violation_keys(state.verify(1, &folded, 7).await),
            vec!["__strong_read_version"]
        );

        let merged = state.snapshot_merged().await;
        assert_eq!(merged[&2].survivor, 1);
        assert_eq!(merged[&2].max_acked_version, 7);
    }

    /// A pre-seal source write can ack after the merge was journaled. It
    /// is part of the sealed document, so it fills a key the survivor
    /// lacks and replaces an older value the journal folded from the
    /// source. It also raises the version the tombstone must sit above.
    /// An errored source write taints the survivor's key.
    #[tokio::test]
    async fn late_source_acks_route_to_the_survivor() {
        let state = PersonState::new();
        state
            .record_write(1, 3, props(&[("shared", "target")]))
            .await;
        state.record_write(2, 5, props(&[("a", "1")])).await;
        state.record_merge(merge(2, 1, 6, &[])).await;

        state
            .record_write(
                2,
                6,
                props(&[("shared", "late"), ("late", "v"), ("a", "2")]),
            )
            .await;
        state
            .record_write_no_change(2, props(&[("echo", "v")]))
            .await;
        state.record_write_uncertain(2, "lost").await;
        assert!(state.take_anomalies().await.is_empty());

        let survivor = json!({"shared": "target", "a": "2", "late": "v", "echo": "v"});
        assert!(state.verify(1, &survivor, 6).await.is_empty());
        assert_eq!(
            violation_keys(
                state
                    .verify(
                        1,
                        &json!({"shared": "target", "a": "1", "late": "v", "echo": "v"}),
                        6
                    )
                    .await
            ),
            vec!["a"]
        );
        // A later survivor ack for the tainted key restores coverage.
        state.record_write(1, 9, props(&[("lost", "found")])).await;
        assert_eq!(
            violation_keys(state.verify(1, &survivor, 9).await),
            vec!["lost"]
        );

        let merged = state.snapshot_merged().await;
        assert_eq!(merged[&2].max_acked_version, 6);
    }

    /// A key the survivor can hold from an uncertain write is never
    /// filled from the source, because the survivor wins every key it
    /// actually has, known to the journal or not.
    #[tokio::test]
    async fn an_uncertain_survivor_key_is_not_filled_from_the_source() {
        let state = PersonState::new();
        state.record_write(1, 3, props(&[("k", "target")])).await;
        state.record_write_uncertain(1, "k").await;
        state.record_write(2, 5, props(&[("k", "source")])).await;
        state.record_merge(merge(2, 1, 6, &[])).await;

        // Either value is acceptable: the key is not asserted.
        assert!(state.verify(1, &json!({"k": "target"}), 6).await.is_empty());
        assert!(state.verify(1, &json!({"k": "source"}), 6).await.is_empty());

        // The source's own uncertain key taints the survivor too.
        let state = PersonState::new();
        state.record_write(3, 2, props(&[("u", "s")])).await;
        state.record_write_uncertain(3, "u").await;
        state.record_merge(merge(3, 4, 3, &[])).await;
        assert!(state.verify(4, &json!({}), 3).await.is_empty());
        state.record_write(4, 4, props(&[("u", "t")])).await;
        assert_eq!(
            violation_keys(state.verify(4, &json!({}), 4).await),
            vec!["u"]
        );
    }

    /// Survivors merge on. A merge ack that names a merged survivor and
    /// a late ack for the first source both land on the final person.
    /// Each hop keeps the leader's precedence: a person's own keys beat
    /// what merged into it.
    #[tokio::test]
    async fn merge_chains_resolve_to_the_final_survivor() {
        let state = PersonState::new();
        state.record_write(1, 1, props(&[("a", "1")])).await;
        state.record_write(2, 1, props(&[("b", "2")])).await;
        state.record_write(3, 1, props(&[("c", "3")])).await;
        state.record_merge(merge(1, 2, 2, &[])).await;
        state.record_merge(merge(2, 3, 2, &[])).await;
        // Person 4 merged into 2 at 2's version 3, but the ack lands
        // after 2's own merge did. 2's own keys beat 4's, the merge
        // event's $set overrode 2's key, and 2's document entered 3.
        state
            .record_merge(merge(4, 2, 3, &[("d", "4"), ("b", "set-4")]))
            .await;
        state.record_write(1, 2, props(&[("late", "1")])).await;
        state.record_write(3, 3, props(&[("own", "3")])).await;
        assert!(state.take_anomalies().await.is_empty());

        assert_eq!(state.person_ids().await, vec![3]);
        let mut merged = state.merged_source_ids().await;
        merged.sort_unstable();
        assert_eq!(merged, vec![1, 2, 4]);
        assert!(state
            .verify(
                3,
                &json!({"a": "1", "b": "set-4", "c": "3", "d": "4", "late": "1", "own": "3"}),
                3
            )
            .await
            .is_empty());
        assert_eq!(
            violation_keys(state.verify(3, &json!({"c": "3"}), 3).await),
            vec!["a", "b", "d", "late", "own"]
        );
        // The fold into 2 raised the version its tombstone must sit
        // above.
        assert_eq!(state.snapshot_merged().await[&2].max_acked_version, 3);

        // A person cannot die twice, and a merge cannot survive itself.
        state.record_merge(merge(1, 3, 4, &[])).await;
        state.record_merge(merge(3, 1, 5, &[])).await;
        assert_eq!(
            violation_keys(state.take_anomalies().await),
            vec!["__merged_twice", "__merged_twice"]
        );
    }

    /// A target's own write for a key beats a fill from a source, in
    /// either ack order. Before the fold the target held the key. After
    /// the fold the target's write overwrote the fill.
    #[tokio::test]
    async fn a_late_own_ack_of_a_dead_target_beats_what_merged_into_it() {
        let state = PersonState::new();
        state.record_write(4, 1, props(&[("k", "from-4")])).await;
        state.record_merge(merge(4, 2, 3, &[])).await;
        state.record_merge(merge(2, 3, 2, &[])).await;
        assert!(state.verify(3, &json!({"k": "from-4"}), 2).await.is_empty());

        state.record_write(2, 2, props(&[("k", "own-2")])).await;
        assert!(state.verify(3, &json!({"k": "own-2"}), 2).await.is_empty());
        assert_eq!(
            violation_keys(state.verify(3, &json!({"k": "from-4"}), 2).await),
            vec!["k"]
        );
        assert!(state.take_anomalies().await.is_empty());
    }

    /// Two merges into one survivor can ack in the opposite order to
    /// their folds. The earlier fold (lower survivor version) filled
    /// the key, and the later fold found it present. A journal that
    /// applied folds in ack order would expect the later source's value
    /// and flag a correct stack.
    #[tokio::test]
    async fn folds_into_one_survivor_are_ordered_by_version_not_ack_arrival() {
        let state = PersonState::new();
        state.record_write(1, 1, props(&[("k", "first")])).await;
        state.record_write(2, 1, props(&[("k", "second")])).await;
        // Person 2's merge folded at survivor version 21. Person 1's
        // folded at 18, but its ack lands second.
        state.record_merge(merge(2, 3, 21, &[])).await;
        state.record_merge(merge(1, 3, 18, &[])).await;
        assert!(state.verify(3, &json!({"k": "first"}), 21).await.is_empty());
        assert_eq!(
            violation_keys(state.verify(3, &json!({"k": "second"}), 21).await),
            vec!["k"]
        );
        // A late ack for the earlier source folds at its own version and
        // still beats the later fold.
        state.record_write(1, 2, props(&[("k2", "first")])).await;
        state.record_write(2, 2, props(&[("k2", "second")])).await;
        assert!(state
            .verify(3, &json!({"k": "first", "k2": "first"}), 21)
            .await
            .is_empty());
        // The survivor's own write wins over every fold, in any arrival
        // order.
        state.record_write(3, 22, props(&[("k", "own")])).await;
        state.record_write(4, 1, props(&[("k", "late")])).await;
        state.record_merge(merge(4, 3, 17, &[])).await;
        assert!(state
            .verify(3, &json!({"k": "own", "k2": "first"}), 22)
            .await
            .is_empty());
        assert!(state.take_anomalies().await.is_empty());
    }

    /// Sources of one call fill in request order. The folded version is
    /// claimed once per call.
    #[tokio::test]
    async fn sources_of_one_merge_fill_in_request_order() {
        let state = PersonState::new();
        state
            .record_write(1, 1, props(&[("k", "first"), ("a", "1")]))
            .await;
        state
            .record_write(2, 1, props(&[("k", "second"), ("b", "2")]))
            .await;
        state.record_write(3, 1, props(&[("k", "third")])).await;
        state.record_write(9, 4, props(&[("t", "9")])).await;
        state
            .record_merge(MergeAck {
                survivor: 9,
                survivor_version: 5,
                sources: vec![2, 1, 3],
                set: props(&[("harness_merge", "op")]),
                set_once: HashMap::new(),
            })
            .await;
        assert!(state.take_anomalies().await.is_empty());
        let mut merged = state.merged_source_ids().await;
        merged.sort_unstable();
        assert_eq!(merged, vec![1, 2, 3]);
        assert!(state
            .verify(
                9,
                &json!({"t": "9", "k": "second", "a": "1", "b": "2", "harness_merge": "op"}),
                5
            )
            .await
            .is_empty());
        assert_eq!(
            violation_keys(state.verify(9, &json!({"k": "first"}), 5).await),
            vec!["a", "b", "harness_merge", "k", "t"]
        );
    }

    /// `$set_once` fills only keys the fold left absent: not a key the
    /// survivor or a source holds, not the same event's `$set` key, and
    /// not an uncertain key.
    #[tokio::test]
    async fn merge_set_once_fills_only_absent_keys() {
        let state = PersonState::new();
        state
            .record_write(1, 3, props(&[("own", "t"), ("raced", "t")]))
            .await;
        state.record_write_uncertain(1, "raced").await;
        state.record_write(2, 5, props(&[("folded", "s")])).await;
        state
            .record_merge(MergeAck {
                survivor: 1,
                survivor_version: 6,
                sources: vec![2],
                set: props(&[("set", "set")]),
                set_once: props(&[
                    ("own", "once"),
                    ("folded", "once"),
                    ("set", "once"),
                    ("raced", "once"),
                    ("fresh", "once"),
                ]),
            })
            .await;
        assert!(state.take_anomalies().await.is_empty());
        let survivor = json!({"own": "t", "folded": "s", "set": "set", "fresh": "once"});
        assert!(state.verify(1, &survivor, 6).await.is_empty());
        assert!(state
            .verify(
                1,
                &json!({"own": "t", "folded": "s", "set": "set", "fresh": "once", "raced": "once"}),
                6
            )
            .await
            .is_empty());
        assert_eq!(
            violation_keys(
                state
                    .verify(
                        1,
                        &json!({"own": "once", "folded": "once", "set": "once", "fresh": "once"}),
                        6
                    )
                    .await
            ),
            vec!["folded", "own", "set"]
        );
    }

    /// A merge that lost every response keeps its journal and stays
    /// tolerated as absent until the op record settles it either way.
    #[tokio::test]
    async fn an_uncertain_merge_keeps_the_source_pending_until_settled() {
        let state = PersonState::new();
        state.record_write(1, 1, props(&[("a", "1")])).await;
        state.mark_merge_pending(1).await;
        state.record_merge_uncertain(1).await;
        assert_eq!(state.person_ids().await, vec![1]);
        assert_eq!(state.merge_uncertain_ids().await, vec![1]);
        assert!(state.is_merge_pending_or_merged(1).await);
        // Settled as merged: the late fold lands like any other.
        state.record_merge(merge(1, 5, 3, &[])).await;
        assert!(state.merge_uncertain_ids().await.is_empty());
        assert!(state.verify(5, &json!({"a": "1"}), 3).await.is_empty());
        // A call that settled without a merge releases the reservation.
        state.mark_merge_pending(2).await;
        state.clear_merge_pending(2).await;
        assert!(!state.is_merge_pending_or_merged(2).await);
    }
}
