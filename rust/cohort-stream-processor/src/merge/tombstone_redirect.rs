//! Tombstone redirect for post-merge straggler events (TDD §4.5.1, "Late events for merged persons").
//!
//! After a merge, P_old's `cf_stage1`/`cf_person_index` rows are gone but a `cf_merge_tombstones`
//! entry records `P_old → P_new`. A straggler `cohort_stream_events` message for P_old then resolves
//! through that tombstone (and any chain of further merges) to the person it should fold into.
//!
//! [`resolve`] follows **same-partition** tombstone hops in process (no cross-worker reads), stopping
//! at the first hop that lands on a different partition — that one is re-keyed and re-produced (in C2)
//! so it hops to the owning worker, which re-resolves from there. The chain `origin` is always the
//! **first** person (the straggler's own id): it keys the merged record's `redirect_dedup`, so
//! rewriting it mid-chain would consult the wrong dedup map and re-open the double-fold hazard.

use metrics::counter;
use tracing::{debug, warn};
use uuid::Uuid;

use crate::filters::TeamId;
use crate::merge::transfer::Tombstone;
use crate::observability::metrics::MERGE_TOMBSTONE_REDIRECTS_TOTAL;
use crate::partitions::partitioner::{partition_of, COHORT_PARTITION_COUNT};
use crate::store::{CohortStore, StoreError, TombstoneKey};

/// Bound on a merge chain followed in one [`resolve`] call. Merge chains only grow forward (a
/// merged-away person is deleted and never becomes a target again), so a real chain is short; the cap
/// is a defensive backstop against a pathological/corrupt cycle.
const MAX_TOMBSTONE_HOPS: usize = 16;

/// Where a straggler event for `person` should actually be processed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Resolution {
    /// No tombstone — process the event normally for `person`.
    NotMerged,
    /// The chain resolves to `final_person`, which co-resides on this partition. Rewrite the event's
    /// person to `final_person` and process inline, stamping `origin` (the first person in the chain)
    /// as the merge origin so the fold dedups against `redirect_dedup[origin]`.
    Inline { final_person: Uuid, origin: Uuid },
    /// The chain reaches `target_person` on a **different** partition. Re-key the event to
    /// `target_person` and re-produce it (C2) so it lands on the owning worker; `origin` is preserved.
    CrossPartition { target_person: Uuid, origin: Uuid },
}

/// Resolve a straggler event's person through the tombstone chain. A backend read error propagates; a
/// corrupt tombstone is treated as "not merged" (debug-logged) rather than panicking.
pub fn resolve(
    store: &CohortStore,
    partition_id: u16,
    team_id: TeamId,
    person: Uuid,
) -> Result<Resolution, StoreError> {
    let team = team_id.0 as u64;

    let Some(first) = read_tombstone(store, partition_id, team, person)? else {
        return Ok(Resolution::NotMerged);
    };

    // The origin is the straggler's own id — fixed across the whole chain.
    let origin = person;
    let mut current = first.new_person;

    for _hop in 0..MAX_TOMBSTONE_HOPS {
        let current_partition = partition_of(team_id, &current, COHORT_PARTITION_COUNT);
        if current_partition as u16 != partition_id {
            // First cross-partition hop: stop and let the re-produce carry it to the owning worker.
            return Ok(Resolution::CrossPartition {
                target_person: current,
                origin,
            });
        }
        // Same partition: follow the chain if `current` was itself merged away, else we are done.
        match read_tombstone(store, partition_id, team, current)? {
            Some(next) => current = next.new_person,
            None => {
                return Ok(Resolution::Inline {
                    final_person: current,
                    origin,
                })
            }
        }
    }

    // Hop cap hit — a corrupt/cyclic chain. Degrade to processing inline at the best-known target
    // rather than looping forever; near-impossible in practice (chains only grow forward).
    warn!(
        partition_id,
        team_id = team_id.0,
        %origin,
        %current,
        "tombstone chain exceeded the hop cap; resolving inline to the last hop",
    );
    Ok(Resolution::Inline {
        final_person: current,
        origin,
    })
}

/// Read and decode one tombstone, or [`None`] when absent or corrupt (the latter debug-logged + read
/// as "not merged" — a single bad row must not wedge the hot path).
fn read_tombstone(
    store: &CohortStore,
    partition_id: u16,
    team: u64,
    person: Uuid,
) -> Result<Option<Tombstone>, StoreError> {
    let key = TombstoneKey {
        partition_id,
        team_id: team,
        person,
    };
    let Some(bytes) = store.get_tombstone(&key)? else {
        return Ok(None);
    };
    match Tombstone::decode(&bytes) {
        Ok(tombstone) => Ok(Some(tombstone)),
        Err(error) => {
            debug!(partition_id, %person, error = %error, "corrupt tombstone; treating as not merged");
            Ok(None)
        }
    }
}

/// The `merge_tombstone_redirects_total{path}` label for a resolution that triggered a redirect.
/// `NotMerged` has no label (it is the no-op path).
pub fn redirect_path(resolution: &Resolution) -> Option<&'static str> {
    match resolution {
        Resolution::NotMerged => None,
        Resolution::Inline { .. } => Some("inline"),
        // C1 drops this arm (no producer yet); C2 re-produces it and relabels to `re_keyed`.
        Resolution::CrossPartition { .. } => Some("cross_partition"),
    }
}

/// Record the redirect under its `path` label (a no-op for [`Resolution::NotMerged`]).
pub fn record_redirect(resolution: &Resolution) {
    if let Some(path) = redirect_path(resolution) {
        counter!(MERGE_TOMBSTONE_REDIRECTS_TOTAL, "path" => path).increment(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    use crate::merge::transfer::Tombstone;
    use crate::store::StoreConfig;

    const TEAM: TeamId = TeamId(7);

    fn temp_store() -> (TempDir, CohortStore) {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        (dir, store)
    }

    fn partition(person: Uuid) -> u16 {
        partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16
    }

    /// A person UUID whose merge partition equals `target`.
    fn person_on(target: u16) -> Uuid {
        (1u128..)
            .map(Uuid::from_u128)
            .find(|p| partition(*p) == target)
            .expect("some uuid hashes to the target partition")
    }

    /// A person UUID whose merge partition is anything but `avoid`.
    fn person_not_on(avoid: u16) -> Uuid {
        (1u128..)
            .map(Uuid::from_u128)
            .find(|p| partition(*p) != avoid)
            .expect("some uuid hashes off the avoided partition")
    }

    fn write_tombstone(store: &CohortStore, on_partition: u16, old: Uuid, new: Uuid) {
        let key = TombstoneKey {
            partition_id: on_partition,
            team_id: TEAM.0 as u64,
            person: old,
        };
        let value = Tombstone {
            new_person: new,
            merged_at_ms: 1_716_800_000_000,
        };
        store
            .write_batch(|b| b.put_tombstone(&key, &value.encode()))
            .unwrap();
    }

    #[test]
    fn no_tombstone_is_not_merged() {
        let (_dir, store) = temp_store();
        let person = Uuid::from_u128(1);
        assert_eq!(
            resolve(&store, partition(person), TEAM, person).unwrap(),
            Resolution::NotMerged,
        );
    }

    #[test]
    fn same_partition_tombstone_resolves_inline() {
        let (_dir, store) = temp_store();
        let p_old = Uuid::from_u128(0xA11CE);
        let part = partition(p_old);
        let p_new = person_on(part); // co-resides
        write_tombstone(&store, part, p_old, p_new);

        assert_eq!(
            resolve(&store, part, TEAM, p_old).unwrap(),
            Resolution::Inline {
                final_person: p_new,
                origin: p_old,
            },
        );
    }

    #[test]
    fn cross_partition_tombstone_stops_at_the_first_hop() {
        let (_dir, store) = temp_store();
        let p_old = Uuid::from_u128(0xA11CE);
        let part = partition(p_old);
        let p_new = person_not_on(part); // different partition
        write_tombstone(&store, part, p_old, p_new);

        assert_eq!(
            resolve(&store, part, TEAM, p_old).unwrap(),
            Resolution::CrossPartition {
                target_person: p_new,
                origin: p_old,
            },
        );
    }

    #[test]
    fn same_partition_chain_converges_to_the_final_person() {
        let (_dir, store) = temp_store();
        let p_old = Uuid::from_u128(0xA11CE);
        let part = partition(p_old);
        // Build a 2-hop same-partition chain: p_old → p_mid → p_final.
        let mids = (1u128..)
            .map(Uuid::from_u128)
            .filter(|p| partition(*p) == part && *p != p_old)
            .take(2)
            .collect::<Vec<_>>();
        let (p_mid, p_final) = (mids[0], mids[1]);
        write_tombstone(&store, part, p_old, p_mid);
        write_tombstone(&store, part, p_mid, p_final);

        assert_eq!(
            resolve(&store, part, TEAM, p_old).unwrap(),
            Resolution::Inline {
                final_person: p_final,
                origin: p_old,
            },
            "the chain converges and the origin stays the first person",
        );
    }

    #[test]
    fn chain_stops_at_the_first_cross_partition_hop() {
        let (_dir, store) = temp_store();
        let p_old = Uuid::from_u128(0xA11CE);
        let part = partition(p_old);
        let p_mid = person_on(part); // same partition (continues)
        let p_far = person_not_on(part); // different partition (stop here)
        write_tombstone(&store, part, p_old, p_mid);
        write_tombstone(&store, part, p_mid, p_far);

        assert_eq!(
            resolve(&store, part, TEAM, p_old).unwrap(),
            Resolution::CrossPartition {
                target_person: p_far,
                origin: p_old,
            },
        );
    }

    #[test]
    fn a_cyclic_chain_is_hop_capped_not_infinite() {
        let (_dir, store) = temp_store();
        let p_old = Uuid::from_u128(0xA11CE);
        let part = partition(p_old);
        let p_b = person_on(part);
        // A degenerate cycle p_old → p_b → p_old (impossible in practice): resolve must terminate.
        write_tombstone(&store, part, p_old, p_b);
        write_tombstone(&store, part, p_b, p_old);

        // Terminates with an Inline (best-effort), not a hang.
        assert!(matches!(
            resolve(&store, part, TEAM, p_old).unwrap(),
            Resolution::Inline { origin, .. } if origin == p_old,
        ));
    }

    #[test]
    fn corrupt_tombstone_reads_as_not_merged() {
        let (_dir, store) = temp_store();
        let person = Uuid::from_u128(1);
        let part = partition(person);
        let key = TombstoneKey {
            partition_id: part,
            team_id: TEAM.0 as u64,
            person,
        };
        store
            .write_batch(|b| b.put_tombstone(&key, b"not json"))
            .unwrap();
        assert_eq!(
            resolve(&store, part, TEAM, person).unwrap(),
            Resolution::NotMerged,
            "a corrupt tombstone degrades to not-merged, never a panic",
        );
    }
}
