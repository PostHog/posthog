//! Versions this pod put on the wire but never heard the outcome of.
//!
//! A changelog record can become durable without the write that produced
//! it learning so. A request cancelled while its send is in flight leaves
//! the record to ride its window's commit; a request cancelled while
//! waiting on that commit has already been counted, and the commit lands
//! with nobody to tell; and a commit whose outcome stays unknown is, by
//! construction, a record that may or may not exist.
//!
//! In each case the version is spent. The cache still holds the version
//! before the write, so the next write for that person derives the same
//! number again and produces a second record carrying it. The writer
//! keeps whichever of the two arrived first and discards the other — and
//! when the discarded one is the acked write, the acknowledgement was a
//! lie.
//!
//! Recording a floor costs nothing on the path that succeeds: the guard
//! is a stack value that only writes to the map when it is dropped
//! without an answer.

use std::sync::Arc;

use dashmap::DashMap;
use metrics::{counter, gauge};

use crate::cache::PersonCacheKey;

/// The highest version this pod emitted for a person without confirming
/// what became of it.
#[derive(Default)]
pub struct EmittedVersions {
    floors: DashMap<(u32, PersonCacheKey), i64>,
}

impl EmittedVersions {
    pub fn new() -> Self {
        Self::default()
    }

    /// The version a write for this person must exceed: whatever the
    /// caller derived from cached or recovered state, or an unresolved
    /// emission, whichever is further ahead.
    pub fn floor_for(&self, partition: u32, key: &PersonCacheKey, known: i64) -> i64 {
        self.floors
            .get(&(partition, key.clone()))
            .map(|floor| known.max(*floor))
            .unwrap_or(known)
    }

    fn raise(&self, partition: u32, key: PersonCacheKey, version: i64) {
        // The entry guard holds a write lock on its shard, and `len`
        // walks every shard — including that one. Anything that reads the
        // map as a whole has to wait until the guard is gone.
        {
            let mut entry = self.floors.entry((partition, key)).or_insert(version);
            if *entry < version {
                *entry = version;
            }
        }
        counter!("personhog_leader_unresolved_versions_total").increment(1);
        gauge!("personhog_leader_unresolved_versions").set(self.floors.len() as f64);
    }

    /// Forget a person's floor: the cache now holds a version at least
    /// this high, so it already carries the constraint.
    fn resolve(&self, partition: u32, key: &PersonCacheKey, version: i64) {
        // Same discipline as `raise`: settle the map first, then read it.
        let removed = self
            .floors
            .remove_if(&(partition, key.clone()), |_, floor| *floor <= version)
            .is_some();
        if removed {
            gauge!("personhog_leader_unresolved_versions").set(self.floors.len() as f64);
        }
    }

    /// Drop every floor for a partition's persons. Ownership is leaving,
    /// and the incoming owner derives versions from the changelog, which
    /// is the authority these floors stand in for.
    pub fn clear_partition(&self, partition: u32) {
        self.floors.retain(|(owner, _), _| *owner != partition);
        gauge!("personhog_leader_unresolved_versions").set(self.floors.len() as f64);
    }

    /// Stage the state a cancelled or indeterminate write leaves behind.
    ///
    /// The real path needs a request to vanish mid-produce or a broker to
    /// fail a commit ambiguously; neither is stageable against a healthy
    /// cluster, and what matters is that the *derivation* consults the
    /// floor afterwards.
    #[cfg(any(test, feature = "test-support"))]
    pub fn raise_for_test(&self, partition: u32, key: PersonCacheKey, version: i64) {
        self.raise(partition, key, version);
    }

    #[cfg(test)]
    fn len(&self) -> usize {
        self.floors.len()
    }
}

/// Holds a version open until the write that emitted it is answered for.
///
/// Dropped without a call to [`EmittedVersionGuard::resolved`] — a
/// cancelled request, or a commit whose fate is unknown — the version is
/// recorded as spent so no later write can reuse it.
pub struct EmittedVersionGuard {
    versions: Arc<EmittedVersions>,
    partition: u32,
    key: PersonCacheKey,
    version: i64,
    settled: bool,
}

impl EmittedVersionGuard {
    pub fn new(
        versions: Arc<EmittedVersions>,
        partition: u32,
        key: PersonCacheKey,
        version: i64,
    ) -> Self {
        Self {
            versions,
            partition,
            key,
            version,
            settled: true,
        }
    }

    /// Arm the guard: from here the record may exist, so an unanswered
    /// drop has to assume it does.
    pub fn emitting(&mut self) {
        self.settled = false;
    }

    /// The write resolved and the cache carries the version now.
    pub fn resolved(mut self) {
        self.settled = true;
        self.versions
            .resolve(self.partition, &self.key, self.version);
    }

    /// The record is known not to exist — the window aborted, or the send
    /// never reached the broker. The version is free again.
    pub fn discarded(mut self) {
        self.settled = true;
    }
}

impl Drop for EmittedVersionGuard {
    fn drop(&mut self) {
        if !self.settled {
            self.versions
                .raise(self.partition, self.key.clone(), self.version);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(person_id: i64) -> PersonCacheKey {
        PersonCacheKey {
            team_id: 1,
            person_id,
        }
    }

    /// The whole point: a write that is never answered for spends its
    /// version, so the next write derives past it instead of colliding.
    #[test]
    fn an_unanswered_emission_raises_the_floor() {
        let versions = Arc::new(EmittedVersions::new());
        let mut guard = EmittedVersionGuard::new(Arc::clone(&versions), 0, key(1), 5);
        guard.emitting();
        drop(guard);

        assert_eq!(versions.floor_for(0, &key(1), 4), 5);
    }

    /// A resolved write needs no floor: the cache holds the version, so
    /// the ordinary derivation already accounts for it.
    #[test]
    fn a_resolved_emission_leaves_no_floor() {
        let versions = Arc::new(EmittedVersions::new());
        let mut guard = EmittedVersionGuard::new(Arc::clone(&versions), 0, key(1), 5);
        guard.emitting();
        guard.resolved();

        assert_eq!(versions.floor_for(0, &key(1), 4), 4);
        assert_eq!(versions.len(), 0);
    }

    /// A window that demonstrably aborted frees its version, so ordinary
    /// retryable failures do not march the counter forward.
    #[test]
    fn a_discarded_emission_leaves_no_floor() {
        let versions = Arc::new(EmittedVersions::new());
        let mut guard = EmittedVersionGuard::new(Arc::clone(&versions), 0, key(1), 5);
        guard.emitting();
        guard.discarded();

        assert_eq!(versions.floor_for(0, &key(1), 4), 4);
    }

    /// A guard that never armed covers a write rejected before anything
    /// could reach the broker.
    #[test]
    fn an_unarmed_guard_records_nothing() {
        let versions = Arc::new(EmittedVersions::new());
        drop(EmittedVersionGuard::new(
            Arc::clone(&versions),
            0,
            key(1),
            5,
        ));

        assert_eq!(versions.floor_for(0, &key(1), 4), 4);
    }

    /// Later state supersedes the floor; an older confirmation must not
    /// clear a newer doubt.
    #[test]
    fn only_a_version_that_covers_the_floor_clears_it() {
        let versions = Arc::new(EmittedVersions::new());
        let mut guard = EmittedVersionGuard::new(Arc::clone(&versions), 0, key(1), 9);
        guard.emitting();
        drop(guard);

        versions.resolve(0, &key(1), 7);
        assert_eq!(versions.floor_for(0, &key(1), 0), 9, "a stale confirmation");

        versions.resolve(0, &key(1), 9);
        assert_eq!(versions.floor_for(0, &key(1), 0), 0, "the covering one");
    }
}
