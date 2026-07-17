//! Tombstone redirect for post-merge straggler events.
//!
//! After a merge, P_old's state rows are gone but a `cf_merge_tombstones` entry records
//! `P_old -> P_new`. A straggler event for P_old resolves through the tombstone chain to the
//! person it should fold into.
//!
//! [`resolve`] follows same-partition tombstone hops in process, stopping at the first hop that
//! lands on a different partition (re-keyed and re-produced). The chain `origin` is always the
//! straggler's own person id, since it keys into `redirect_dedup`.

use metrics::counter;
use tracing::{debug, warn};
use uuid::Uuid;

use crate::filters::TeamId;
use crate::merge::transfer::Tombstone;
use crate::observability::metrics::MERGE_TOMBSTONE_REDIRECTS_TOTAL;
use crate::partitions::partitioner::partition_of;
use crate::store::{CohortStore, StoreError, StoreHandle, TombstoneKey};

/// Defensive bound on same-partition tombstone hops in one [`resolve`] call.
const MAX_TOMBSTONE_HOPS: usize = 16;

/// Bound on cross-partition re-produce hops (`redirect_hops` on the wire). Prevents infinite
/// re-production between partitions in case of a corrupt cross-partition tombstone cycle.
pub(crate) const MAX_CROSS_PARTITION_REDIRECT_HOPS: u8 = 8;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Resolution {
    /// No tombstone -- process the event normally.
    NotMerged,
    /// Chain resolves to `final_person` on this partition. Process inline with `origin` as the
    /// dedup key into `redirect_dedup`.
    Inline { final_person: Uuid, origin: Uuid },
    /// Chain reaches `target_person` on a different partition. Re-key and re-produce.
    CrossPartition { target_person: Uuid, origin: Uuid },
}

/// Resolve a straggler event's person through the tombstone chain.
///
/// `partition_count` is the live co-partitioned topic count (production 64; test lanes lower it):
/// a cross-partition hop is decided by whether the next person hashes off `partition_id` under
/// this count, so it must match the deploy's topology, not a literal.
pub fn resolve(
    store: &CohortStore,
    partition_id: u16,
    team_id: TeamId,
    person: Uuid,
    partition_count: u32,
) -> Result<Resolution, StoreError> {
    let team = team_id.0 as u64;

    let Some(first) = read_tombstone(store, partition_id, team, person)? else {
        return Ok(Resolution::NotMerged);
    };

    let origin = person;
    let mut current = first.new_person;

    for _hop in 0..MAX_TOMBSTONE_HOPS {
        let current_partition = partition_of(team_id, &current, partition_count);
        if current_partition as u16 != partition_id {
            return Ok(Resolution::CrossPartition {
                target_person: current,
                origin,
            });
        }
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

/// Read and decode one tombstone, or `None` when absent or corrupt.
// Section-core surface: `resolve` calls this inside drain/apply `run_section` closures, so its direct
// `get_tombstone` is already off the runtime threads. The async `resolve_offloaded` twin reads through
// the `StoreHandle` facade, and the crate-wide lint keeps it free of raw `CohortStore` calls.
#[allow(clippy::disallowed_methods)]
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

/// Async twin of [`resolve`] over the [`StoreHandle`] facade: identical tombstone walk,
/// [`Resolution`] semantics, and [`MAX_TOMBSTONE_HOPS`] cap, but each hop reads through the Event
/// lane so the store I/O runs on the blocking pool. Used by the event-path worker; drain/apply call
/// the sync [`resolve`] inside their `run_section` closures.
pub async fn resolve_offloaded(
    handle: &StoreHandle,
    partition_id: u16,
    team_id: TeamId,
    person: Uuid,
    partition_count: u32,
) -> Result<Resolution, StoreError> {
    let team = team_id.0 as u64;

    let Some(first) = read_tombstone_offloaded(handle, partition_id, team, person).await? else {
        return Ok(Resolution::NotMerged);
    };

    let origin = person;
    let mut current = first.new_person;

    for _hop in 0..MAX_TOMBSTONE_HOPS {
        let current_partition = partition_of(team_id, &current, partition_count);
        if current_partition as u16 != partition_id {
            return Ok(Resolution::CrossPartition {
                target_person: current,
                origin,
            });
        }
        match read_tombstone_offloaded(handle, partition_id, team, current).await? {
            Some(next) => current = next.new_person,
            None => {
                return Ok(Resolution::Inline {
                    final_person: current,
                    origin,
                })
            }
        }
    }

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

/// Read and decode one tombstone through the Event lane, or `None` when absent or corrupt.
async fn read_tombstone_offloaded(
    handle: &StoreHandle,
    partition_id: u16,
    team: u64,
    person: Uuid,
) -> Result<Option<Tombstone>, StoreError> {
    let key = TombstoneKey {
        partition_id,
        team_id: team,
        person,
    };
    let Some(bytes) = handle.get_tombstone(&key).await? else {
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

/// Record an inline redirect metric. Cross-partition redirects are counted separately via
/// [`record_re_keyed`] after the re-produce ack.
pub fn record_redirect(resolution: &Resolution) {
    match resolution {
        Resolution::NotMerged | Resolution::CrossPartition { .. } => {}
        Resolution::Inline { .. } => {
            counter!(MERGE_TOMBSTONE_REDIRECTS_TOTAL, "path" => "inline").increment(1);
        }
    }
}

/// Record `count` cross-partition redirects (called after the re-produce ack).
pub fn record_re_keyed(count: u64) {
    if count > 0 {
        counter!(MERGE_TOMBSTONE_REDIRECTS_TOTAL, "path" => "re_keyed").increment(count);
    }
}

// Tests seed and read tombstones directly against the store.
#[cfg(test)]
#[allow(clippy::disallowed_methods)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    use crate::merge::transfer::Tombstone;
    use crate::partitions::partitioner::COHORT_PARTITION_COUNT;
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

    /// Find a UUID that hashes to `target` partition.
    fn person_on(target: u16) -> Uuid {
        (1u128..)
            .map(Uuid::from_u128)
            .find(|p| partition(*p) == target)
            .expect("some uuid hashes to the target partition")
    }

    /// Find a UUID that hashes to any partition except `avoid`.
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
            resolve(
                &store,
                partition(person),
                TEAM,
                person,
                COHORT_PARTITION_COUNT
            )
            .unwrap(),
            Resolution::NotMerged,
        );
    }

    #[test]
    fn same_partition_tombstone_resolves_inline() {
        let (_dir, store) = temp_store();
        let p_old = Uuid::from_u128(0xA11CE);
        let part = partition(p_old);
        let p_new = person_on(part);
        write_tombstone(&store, part, p_old, p_new);

        assert_eq!(
            resolve(&store, part, TEAM, p_old, COHORT_PARTITION_COUNT).unwrap(),
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
        let p_new = person_not_on(part);
        write_tombstone(&store, part, p_old, p_new);

        assert_eq!(
            resolve(&store, part, TEAM, p_old, COHORT_PARTITION_COUNT).unwrap(),
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
        let mids = (1u128..)
            .map(Uuid::from_u128)
            .filter(|p| partition(*p) == part && *p != p_old)
            .take(2)
            .collect::<Vec<_>>();
        let (p_mid, p_final) = (mids[0], mids[1]);
        write_tombstone(&store, part, p_old, p_mid);
        write_tombstone(&store, part, p_mid, p_final);

        assert_eq!(
            resolve(&store, part, TEAM, p_old, COHORT_PARTITION_COUNT).unwrap(),
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
        let p_mid = person_on(part);
        let p_far = person_not_on(part);
        write_tombstone(&store, part, p_old, p_mid);
        write_tombstone(&store, part, p_mid, p_far);

        assert_eq!(
            resolve(&store, part, TEAM, p_old, COHORT_PARTITION_COUNT).unwrap(),
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
        write_tombstone(&store, part, p_old, p_b);
        write_tombstone(&store, part, p_b, p_old);

        assert!(matches!(
            resolve(&store, part, TEAM, p_old, COHORT_PARTITION_COUNT).unwrap(),
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
            resolve(&store, part, TEAM, person, COHORT_PARTITION_COUNT).unwrap(),
            Resolution::NotMerged,
            "a corrupt tombstone degrades to not-merged, never a panic",
        );
    }
}
