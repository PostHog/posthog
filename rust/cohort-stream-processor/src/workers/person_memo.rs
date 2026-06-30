//! Per-worker memoization of person-property condition results.
//!
//! A person-property leaf's result is a pure function of `(catalog generation, person_properties)`:
//! the person globals carry no clock and the STL has no `now()`. So a person's per-condition
//! `matches` bits can be cached and reused while its raw `person_properties` are unchanged, skipping
//! the JSON parse and the HogVM evaluations. A catalog change bumps the generation, invalidating
//! every entry. Keyed by `(team_id, person_id)`, validated by generation + a props fingerprint.

use std::num::NonZeroUsize;

use lru::LruCache;
use sha2::{Digest, Sha256};
use uuid::Uuid;

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

/// `team_id` keeps persons from different teams distinct on a shared worker.
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
struct PersonMemoKey {
    team_id: i32,
    person_id: Uuid,
}

struct MemoEntry {
    generation: u64,
    props_fp: u128,
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

/// `None` cache means disabled (no allocation); callers gate on [`Self::enabled`].
pub struct PersonMemo {
    cache: Option<LruCache<PersonMemoKey, MemoEntry>>,
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

    pub fn enabled(&self) -> bool {
        self.cache.is_some()
    }

    /// Cached results iff the entry matches the current generation and props fingerprint, else `None`.
    pub(crate) fn lookup(
        &mut self,
        team_id: i32,
        person_id: Uuid,
        generation: u64,
        props_fp: u128,
    ) -> Option<ConditionBitset> {
        let cache = self.cache.as_mut()?;
        let key = PersonMemoKey { team_id, person_id };
        match cache.get(&key) {
            Some(entry) if entry.generation == generation && entry.props_fp == props_fp => {
                Some(entry.results.clone())
            }
            _ => None,
        }
    }

    pub(crate) fn store(
        &mut self,
        team_id: i32,
        person_id: Uuid,
        generation: u64,
        props_fp: u128,
        results: ConditionBitset,
    ) {
        if let Some(cache) = self.cache.as_mut() {
            cache.put(
                PersonMemoKey { team_id, person_id },
                MemoEntry {
                    generation,
                    props_fp,
                    results,
                },
            );
        }
    }
}

/// 128 bits of SHA-256 over the raw props — collision-negligible, and computable without a JSON parse.
pub(crate) fn person_props_fingerprint(raw: &str) -> u128 {
    let digest = Sha256::digest(raw.as_bytes());
    u128::from_le_bytes(digest[..16].try_into().expect("SHA-256 yields 32 bytes"))
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
        assert!(!memo.enabled());
        memo.store(7, Uuid::from_u128(1), 1, 42, ConditionBitset::zeros(3));
        assert!(memo.lookup(7, Uuid::from_u128(1), 1, 42).is_none());
    }

    #[test]
    fn hit_requires_matching_generation_and_fingerprint() {
        let mut memo = PersonMemo::new(config(8));
        let person = Uuid::from_u128(1);
        let mut results = ConditionBitset::zeros(2);
        results.set(1);
        memo.store(7, person, 5, 99, results.clone());

        assert_eq!(memo.lookup(7, person, 5, 99), Some(results));
        assert!(memo.lookup(7, person, 6, 99).is_none(), "generation bump");
        assert!(
            memo.lookup(7, person, 5, 100).is_none(),
            "fingerprint change"
        );
        assert!(memo.lookup(8, person, 5, 99).is_none(), "other team");
    }

    #[test]
    fn store_overwrites_a_stale_entry() {
        let mut memo = PersonMemo::new(config(8));
        let person = Uuid::from_u128(1);
        memo.store(7, person, 5, 99, ConditionBitset::zeros(2));
        // New generation for the same person: overwrite, not accumulate.
        let mut fresh = ConditionBitset::zeros(2);
        fresh.set(0);
        memo.store(7, person, 6, 99, fresh.clone());
        assert_eq!(memo.lookup(7, person, 6, 99), Some(fresh));
    }

    #[test]
    fn lru_evicts_the_least_recently_used_entry() {
        let mut memo = PersonMemo::new(config(2));
        let (a, b, c) = (Uuid::from_u128(1), Uuid::from_u128(2), Uuid::from_u128(3));
        memo.store(7, a, 1, 1, ConditionBitset::zeros(1));
        memo.store(7, b, 1, 2, ConditionBitset::zeros(1));
        // Touch `a` so `b` becomes the eviction victim.
        assert!(memo.lookup(7, a, 1, 1).is_some());
        memo.store(7, c, 1, 3, ConditionBitset::zeros(1));
        assert!(memo.lookup(7, b, 1, 2).is_none(), "b evicted as LRU");
        assert!(memo.lookup(7, a, 1, 1).is_some());
        assert!(memo.lookup(7, c, 1, 3).is_some());
    }

    #[test]
    fn fingerprint_is_stable_and_sensitive() {
        let a = person_props_fingerprint(r#"{"email":"u@p.com"}"#);
        assert_eq!(a, person_props_fingerprint(r#"{"email":"u@p.com"}"#));
        assert_ne!(a, person_props_fingerprint(r#"{"email":"v@p.com"}"#));
    }
}
