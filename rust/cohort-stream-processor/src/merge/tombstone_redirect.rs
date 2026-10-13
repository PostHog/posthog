//! Tombstone redirect for post-merge straggler events.
//!
//! After a merge, P_old's state rows are gone but a `cf_merge_tombstones` entry records
//! `P_old -> P_new`. A straggler event for P_old resolves through the tombstone chain to the
//! person it should fold into.
//!
//! [`resolve`] follows same-partition tombstone hops in process, stopping at the first hop that
//! lands on a different partition (re-keyed and re-produced). The chain `origin` is always the
//! straggler's own person id, since it keys into `redirect_dedup`.

use std::collections::HashMap;

use metrics::counter;
use tracing::{debug, warn};
use uuid::Uuid;

use crate::filters::TeamId;
use crate::merge::transfer::Tombstone;
use crate::observability::metrics::MERGE_TOMBSTONE_REDIRECTS_TOTAL;
use crate::partitions::partitioner::partition_of;
use crate::store::{CohortStore, ReadLane, StoreError, StoreHandle, TombstoneKey};

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
    Ok(decode_tombstone(partition_id, person, &bytes))
}

/// Async twin of [`resolve`] over the [`StoreHandle`] facade; each hop reads on the caller's
/// `lane`. Drain/apply call the sync [`resolve`] inside their `run_section` closures.
pub async fn resolve_offloaded(
    handle: &StoreHandle,
    partition_id: u16,
    team_id: TeamId,
    person: Uuid,
    partition_count: u32,
    lane: ReadLane,
) -> Result<Resolution, StoreError> {
    let team = team_id.0 as u64;

    let Some(first) = read_tombstone_offloaded(handle, partition_id, team, person, lane).await?
    else {
        return Ok(Resolution::NotMerged);
    };
    walk_from(
        handle,
        partition_id,
        team_id,
        person,
        first,
        partition_count,
        lane,
    )
    .await
}

/// Resolve many distinct `(team, person)` keys, reading every chain's first hop in one batched
/// `multi_get` and walking the rest from there.
///
/// Only a chain whose first hop lands back on this partition needs its later hops walked one at a
/// time, and that requires a merge, so a backfill run normally pays exactly one read for the whole
/// run. A repeated key costs a redundant read and resolves to the same verdict.
///
/// A short `multi_get` yields a map missing those keys. The caller must treat a missing key as a
/// failure, never as `NotMerged`: applying a seed to a person that may have merged away is durable
/// state nothing downstream can retract.
pub async fn resolve_batch_offloaded(
    handle: &StoreHandle,
    partition_id: u16,
    persons: &[(TeamId, Uuid)],
    partition_count: u32,
    lane: ReadLane,
) -> Result<HashMap<(TeamId, Uuid), Resolution>, StoreError> {
    let keys: Vec<TombstoneKey> = persons
        .iter()
        .map(|&(team_id, person)| TombstoneKey {
            partition_id,
            team_id: team_id.0 as u64,
            person,
        })
        .collect();
    let values = handle.multi_get_tombstones(keys, lane).await?;

    let mut resolved = HashMap::with_capacity(persons.len());
    for (&(team_id, person), bytes) in persons.iter().zip(values) {
        let first = bytes
            .as_deref()
            .and_then(|bytes| decode_tombstone(partition_id, person, bytes));
        let resolution = match first {
            None => Resolution::NotMerged,
            Some(first) => {
                walk_from(
                    handle,
                    partition_id,
                    team_id,
                    person,
                    first,
                    partition_count,
                    lane,
                )
                .await?
            }
        };
        resolved.insert((team_id, person), resolution);
    }
    Ok(resolved)
}

/// Follow a chain from its already-read first hop. Shared by the single and batched resolvers, so
/// a batched read's decoded hop is never re-read: the walk starts from its target and checks that
/// target's partition before touching the store again.
async fn walk_from(
    handle: &StoreHandle,
    partition_id: u16,
    team_id: TeamId,
    origin: Uuid,
    first: Tombstone,
    partition_count: u32,
    lane: ReadLane,
) -> Result<Resolution, StoreError> {
    let team = team_id.0 as u64;
    let mut current = first.new_person;

    for _hop in 0..MAX_TOMBSTONE_HOPS {
        let current_partition = partition_of(team_id, &current, partition_count);
        if current_partition as u16 != partition_id {
            return Ok(Resolution::CrossPartition {
                target_person: current,
                origin,
            });
        }
        match read_tombstone_offloaded(handle, partition_id, team, current, lane).await? {
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
async fn read_tombstone_offloaded(
    handle: &StoreHandle,
    partition_id: u16,
    team: u64,
    person: Uuid,
    lane: ReadLane,
) -> Result<Option<Tombstone>, StoreError> {
    let key = TombstoneKey {
        partition_id,
        team_id: team,
        person,
    };
    let Some(bytes) = handle.get_tombstone(&key, lane).await? else {
        return Ok(None);
    };
    Ok(decode_tombstone(partition_id, person, &bytes))
}

/// Decode one stored tombstone, or `None` when the bytes are corrupt. A corrupt marker reads as
/// "not merged", the same degrade a missing marker gets.
fn decode_tombstone(partition_id: u16, person: Uuid, bytes: &[u8]) -> Option<Tombstone> {
    match Tombstone::decode(bytes) {
        Ok(tombstone) => Some(tombstone),
        Err(error) => {
            debug!(partition_id, %person, error = %error, "corrupt tombstone; treating as not merged");
            None
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
    use crate::store::{OffloadConfig, OffloadMode, StoreConfig};

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

    /// One batched first-hop read must answer every key with its own verdict. A shifted answer
    /// would route one person's seed through another person's merge chain, which is durable state
    /// nothing downstream can retract.
    #[tokio::test]
    async fn resolve_batch_reads_one_first_hop_per_key_and_walks_only_local_chains() {
        let (_dir, store) = temp_store();
        let handle = StoreHandle::new(
            store.clone(),
            OffloadConfig {
                mode: OffloadMode::All,
                event_read_permits: 4,
                maintenance_permits: 4,
            },
        );
        let p_old = Uuid::from_u128(0xA11CE);
        let part = partition(p_old);
        let locals = (1u128..)
            .map(Uuid::from_u128)
            .filter(|p| partition(*p) == part && *p != p_old)
            .take(3)
            .collect::<Vec<_>>();
        let (p_mid, p_final, p_unmerged) = (locals[0], locals[1], locals[2]);
        let p_leaving = (1u128..)
            .map(Uuid::from_u128)
            .find(|p| partition(*p) == part && ![p_old, p_mid, p_final, p_unmerged].contains(p))
            .unwrap();
        let p_far = person_not_on(part);
        write_tombstone(&store, part, p_old, p_mid);
        write_tombstone(&store, part, p_mid, p_final);
        write_tombstone(&store, part, p_leaving, p_far);

        let resolved = resolve_batch_offloaded(
            &handle,
            part,
            &[(TEAM, p_old), (TEAM, p_unmerged), (TEAM, p_leaving)],
            COHORT_PARTITION_COUNT,
            ReadLane::Maintenance,
        )
        .await
        .unwrap();

        assert_eq!(resolved.len(), 3, "one verdict per key asked");
        assert_eq!(
            resolved[&(TEAM, p_old)],
            Resolution::Inline {
                final_person: p_final,
                origin: p_old,
            },
            "the chain converges past the batched hop and the origin stays the first person",
        );
        assert_eq!(resolved[&(TEAM, p_unmerged)], Resolution::NotMerged);
        assert_eq!(
            resolved[&(TEAM, p_leaving)],
            Resolution::CrossPartition {
                target_person: p_far,
                origin: p_leaving,
            },
            "a first hop that leaves the partition is a hand-off, not a walk",
        );
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
