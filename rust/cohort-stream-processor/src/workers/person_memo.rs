//! Per-worker memoization of person-property condition results.
//!
//! A person-property leaf's result is a pure function of `(catalog generation, person_properties)`:
//! the person globals carry no clock and the STL has no `now()`. So a person's per-condition
//! `matches` bits can be cached and reused while its raw `person_properties` are unchanged, skipping
//! the JSON parse and the HogVM evaluations. A catalog change bumps the generation, invalidating
//! every entry.

use std::num::NonZeroUsize;

use lru::LruCache;
use metrics::counter;
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::filters::{Generation, TeamId};
use crate::observability::metrics::STAGE1_PERSON_MEMO;

#[derive(Clone, Copy, Debug)]
pub struct PersonMemoConfig {
    pub enabled: bool,
    pub capacity: usize,
}

impl PersonMemoConfig {
    pub const DISABLED: Self = Self {
        enabled: false,
        capacity: 0,
    };
}

/// `team` keeps persons from different teams distinct on a shared worker.
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub(crate) struct PersonKey {
    pub team: TeamId,
    pub person: Uuid,
}

/// A cached result's validity: an entry is current iff its stamp equals the lookup's, so `==` is the
/// invalidation rule. The generation also guarantees the bits align with the current
/// `person_conditions_ordered`.
#[derive(Clone, Copy, PartialEq, Eq)]
struct Stamp {
    generation: Generation,
    fingerprint: PropsFingerprint,
}

/// 128 bits of SHA-256 over the raw props — collision-negligible, and computable without a JSON parse.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct PropsFingerprint(u128);

impl PropsFingerprint {
    fn of(raw: &str) -> Self {
        let digest = Sha256::digest(raw.as_bytes());
        Self(u128::from_le_bytes(
            digest[..16].try_into().expect("SHA-256 yields 32 bytes"),
        ))
    }
}

struct MemoEntry {
    stamp: Stamp,
    results: ConditionBitset,
}

/// Person-condition results, one bit per position in `person_conditions_ordered`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct ConditionBitset {
    bits: Box<[u8]>,
    len: usize,
}

impl ConditionBitset {
    pub(crate) fn zeros(len: usize) -> Self {
        Self {
            bits: vec![0u8; len.div_ceil(8)].into_boxed_slice(),
            len,
        }
    }

    pub(crate) fn set(&mut self, idx: usize) {
        debug_assert!(idx < self.len);
        self.bits[idx / 8] |= 1 << (idx % 8);
    }

    pub(crate) fn get(&self, idx: usize) -> bool {
        debug_assert!(idx < self.len);
        self.bits[idx / 8] & (1 << (idx % 8)) != 0
    }
}

/// The outcome of [`PersonMemo::probe`].
pub(crate) enum Lookup {
    /// The cached results are current; reuse them.
    Hit(ConditionBitset),
    /// Evaluate, then redeem the [`Receipt`] with the fresh results.
    Miss(Receipt),
}

/// Proof of a miss carrying the `(key, stamp)` to cache under, so [`PersonMemo::store`] can only
/// write what was probed. `None` when the memo is disabled, making the write a no-op.
pub(crate) struct Receipt(Option<(PersonKey, Stamp)>);

/// `None` cache means disabled (no allocation).
pub struct PersonMemo {
    cache: Option<LruCache<PersonKey, MemoEntry>>,
}

impl PersonMemo {
    pub fn new(config: PersonMemoConfig) -> Self {
        let cache = config.enabled.then(|| {
            // Clamp so a misconfigured `0` still caches one entry rather than panicking.
            LruCache::new(NonZeroUsize::new(config.capacity.max(1)).expect("capacity is >= 1"))
        });
        Self { cache }
    }

    pub fn disabled() -> Self {
        Self { cache: None }
    }

    /// Consult the memo for `key` at the current `generation` and props. A stale, absent, or disabled
    /// entry is a [`Lookup::Miss`]; the fingerprint is computed only when enabled, so the kill-switch
    /// costs no hash.
    pub(crate) fn probe(&mut self, key: PersonKey, generation: Generation, raw: &str) -> Lookup {
        let Some(cache) = self.cache.as_mut() else {
            return Lookup::Miss(Receipt(None));
        };
        let stamp = Stamp {
            generation,
            fingerprint: PropsFingerprint::of(raw),
        };
        if let Some(entry) = cache.get(&key) {
            if entry.stamp == stamp {
                counter!(STAGE1_PERSON_MEMO, "result" => "hit").increment(1);
                return Lookup::Hit(entry.results.clone());
            }
        }
        counter!(STAGE1_PERSON_MEMO, "result" => "miss").increment(1);
        Lookup::Miss(Receipt(Some((key, stamp))))
    }

    /// Cache `results` under a miss receipt; a no-op when the receipt came from a disabled memo.
    pub(crate) fn store(&mut self, receipt: Receipt, results: ConditionBitset) {
        if let (Some(cache), Receipt(Some((key, stamp)))) = (self.cache.as_mut(), receipt) {
            cache.put(key, MemoEntry { stamp, results });
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(capacity: usize) -> PersonMemoConfig {
        PersonMemoConfig {
            enabled: true,
            capacity,
        }
    }

    fn key(team: i32, person: u128) -> PersonKey {
        PersonKey {
            team: TeamId(team),
            person: Uuid::from_u128(person),
        }
    }

    /// Probe (asserting a miss) and cache `results` under the returned receipt.
    fn seed(
        memo: &mut PersonMemo,
        key: PersonKey,
        gen: Generation,
        raw: &str,
        results: ConditionBitset,
    ) {
        let Lookup::Miss(receipt) = memo.probe(key, gen, raw) else {
            panic!("expected a miss for a fresh entry");
        };
        memo.store(receipt, results);
    }

    fn hit_bits(
        memo: &mut PersonMemo,
        key: PersonKey,
        gen: Generation,
        raw: &str,
    ) -> ConditionBitset {
        match memo.probe(key, gen, raw) {
            Lookup::Hit(bits) => bits,
            Lookup::Miss(_) => panic!("expected a hit"),
        }
    }

    #[test]
    fn bitset_roundtrips_each_bit_and_packs_to_ceil_div_8() {
        let mut bits = ConditionBitset::zeros(10);
        assert_eq!(bits.bits.len(), 2, "10 bits pack into 2 bytes");
        for idx in [0, 3, 7, 8, 9] {
            bits.set(idx);
        }
        for idx in 0..10 {
            assert_eq!(bits.get(idx), [0, 3, 7, 8, 9].contains(&idx), "bit {idx}");
        }
    }

    #[test]
    fn zero_length_bitset_allocates_nothing() {
        assert!(ConditionBitset::zeros(0).bits.is_empty());
    }

    #[test]
    fn disabled_memo_never_caches() {
        let mut memo = PersonMemo::disabled();
        seed(
            &mut memo,
            key(7, 1),
            Generation(1),
            "p",
            ConditionBitset::zeros(3),
        );
        assert!(matches!(
            memo.probe(key(7, 1), Generation(1), "p"),
            Lookup::Miss(_)
        ));
    }

    #[test]
    fn hit_requires_matching_generation_props_and_team() {
        let mut memo = PersonMemo::new(config(8));
        let mut results = ConditionBitset::zeros(2);
        results.set(1);
        seed(
            &mut memo,
            key(7, 1),
            Generation(5),
            "props-A",
            results.clone(),
        );

        assert_eq!(
            hit_bits(&mut memo, key(7, 1), Generation(5), "props-A"),
            results
        );
        assert!(matches!(
            memo.probe(key(7, 1), Generation(6), "props-A"),
            Lookup::Miss(_)
        ));
        assert!(matches!(
            memo.probe(key(7, 1), Generation(5), "props-B"),
            Lookup::Miss(_)
        ));
        assert!(matches!(
            memo.probe(key(8, 1), Generation(5), "props-A"),
            Lookup::Miss(_)
        ));
    }

    #[test]
    fn a_new_generation_overwrites_the_stale_entry() {
        let mut memo = PersonMemo::new(config(8));
        seed(
            &mut memo,
            key(7, 1),
            Generation(5),
            "p",
            ConditionBitset::zeros(2),
        );
        let mut fresh = ConditionBitset::zeros(2);
        fresh.set(0);
        seed(&mut memo, key(7, 1), Generation(6), "p", fresh.clone());
        assert_eq!(hit_bits(&mut memo, key(7, 1), Generation(6), "p"), fresh);
    }

    #[test]
    fn lru_evicts_the_least_recently_used_entry() {
        let mut memo = PersonMemo::new(config(2));
        let g = Generation(1);
        seed(&mut memo, key(7, 1), g, "a", ConditionBitset::zeros(1));
        seed(&mut memo, key(7, 2), g, "b", ConditionBitset::zeros(1));
        // Touch entry 1 so entry 2 becomes the eviction victim.
        assert!(matches!(memo.probe(key(7, 1), g, "a"), Lookup::Hit(_)));
        seed(&mut memo, key(7, 3), g, "c", ConditionBitset::zeros(1));
        assert!(matches!(memo.probe(key(7, 2), g, "b"), Lookup::Miss(_)));
        assert!(matches!(memo.probe(key(7, 1), g, "a"), Lookup::Hit(_)));
        assert!(matches!(memo.probe(key(7, 3), g, "c"), Lookup::Hit(_)));
    }

    #[test]
    fn fingerprint_is_stable_and_sensitive() {
        assert_eq!(PropsFingerprint::of("x"), PropsFingerprint::of("x"));
        assert_ne!(PropsFingerprint::of("x"), PropsFingerprint::of("y"));
    }
}
