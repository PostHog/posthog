//! Kafka-compatible `murmur2` partitioner (TDD §4.3 / §4.5.1).
//!
//! The shuffler produces `cohort_stream_events` with the **`murmur2_random`** partitioner —
//! `partition = (murmur2(key) & 0x7fffffff) % partitions`, the Kafka-Java / python-kafka / Node
//! choice, **not** librdkafka's default CRC32 `consistent_random`. The merge protocol must place a
//! merge on the worker that owns `Murmur2(hash(team, person)) mod 64`, so it reproduces that math
//! here (the store has no murmur2 helper and the workspace has no murmur2 crate). The `murmur2` port
//! is byte-for-byte the Kafka `Utils.murmur2` / librdkafka `rd_murmur2` algorithm (seed
//! `0x9747b28c`); the published Kafka test vectors below pin it, and C2's broker test asserts live
//! agreement with the shuffler's producer.

use uuid::Uuid;

use crate::filters::TeamId;

/// The `cohort_stream_events` partition count — every co-partitioned topic (merges, transfers,
/// cascade, seed) must match it (TDD §2.5 worker-affinity invariant).
pub const COHORT_PARTITION_COUNT: u32 = 64;

const MURMUR2_SEED: u32 = 0x9747_b28c;
const MURMUR2_M: u32 = 0x5bd1_e995;
const MURMUR2_R: u32 = 24;

/// The Kafka/`librdkafka` `murmur2` hash of `data`. A direct port of `Utils.murmur2`: little-endian
/// 4-byte blocks, `0x9747b28c` seed, wrapping (two's-complement) arithmetic. Returned as `u32` (the
/// raw bit pattern); [`partition_for`] applies the `& 0x7fffffff` positivity mask Kafka uses.
pub fn murmur2(data: &[u8]) -> u32 {
    let len = data.len();
    let mut h = MURMUR2_SEED ^ (len as u32);

    let nblocks = len / 4;
    for block in 0..nblocks {
        let i = block * 4;
        let mut k = (data[i] as u32)
            | ((data[i + 1] as u32) << 8)
            | ((data[i + 2] as u32) << 16)
            | ((data[i + 3] as u32) << 24);
        k = k.wrapping_mul(MURMUR2_M);
        k ^= k >> MURMUR2_R;
        k = k.wrapping_mul(MURMUR2_M);
        h = h.wrapping_mul(MURMUR2_M);
        h ^= k;
    }

    // The tail falls through Kafka's `switch` from the high byte down, then one final `h *= m`.
    let tail = nblocks * 4;
    let remainder = len & 3;
    if remainder >= 3 {
        h ^= (data[tail + 2] as u32) << 16;
    }
    if remainder >= 2 {
        h ^= (data[tail + 1] as u32) << 8;
    }
    if remainder >= 1 {
        h ^= data[tail] as u32;
        h = h.wrapping_mul(MURMUR2_M);
    }

    h ^= h >> 13;
    h = h.wrapping_mul(MURMUR2_M);
    h ^= h >> 15;
    h
}

/// The partition `key` lands on: `(murmur2(key) & 0x7fffffff) % partition_count` — Kafka's
/// `Utils.toPositive(murmur2(..)) % numPartitions`.
///
/// # Panics
/// Panics if `partition_count` is zero (a partition count is always ≥ 1).
pub fn partition_for(key: &str, partition_count: u32) -> u32 {
    assert!(partition_count > 0, "partition_count must be non-zero");
    (murmur2(key.as_bytes()) & 0x7fff_ffff) % partition_count
}

/// The re-key string for a `(team, person)` pair — `"{team_id}:{person_id}"`, the single source of
/// truth in `cohort-event-shuffler`'s `partition_key`. Every co-partitioned producer (including the
/// future Node merge producer) must reuse it verbatim, or the worker-affinity invariant breaks.
pub fn merge_partition_key(team_id: TeamId, person: &Uuid) -> String {
    format!("{}:{}", team_id.0, person)
}

/// The partition the `(team, person)` pair's state lives on — `partition_for(merge_partition_key)`.
pub fn partition_of(team_id: TeamId, person: &Uuid, partition_count: u32) -> u32 {
    partition_for(&merge_partition_key(team_id, person), partition_count)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Published Kafka `Utils.murmur2` vectors (`org.apache.kafka.common.utils.UtilsTest`), as signed
    /// Java `int`s — pinning the algorithm against external ground truth, not our own implementation.
    #[test]
    fn murmur2_matches_published_kafka_vectors() {
        let cases: [(&[u8], i32); 6] = [
            (b"21", -973_932_308),
            (b"foobar", -790_332_482),
            (b"a-little-bit-long-string", -985_981_536),
            (b"a-little-bit-longer-string", -1_486_304_829),
            (
                b"lkjh234lh9fiuh90y23oiuhsafujhadof229phr9h19h89h8",
                -58_897_971,
            ),
            (b"abc", 479_470_107),
        ];
        for (input, expected) in cases {
            assert_eq!(
                murmur2(input) as i32,
                expected,
                "murmur2({:?}) diverged from the Kafka vector",
                std::str::from_utf8(input).unwrap(),
            );
        }
    }

    #[test]
    fn partition_for_masks_the_sign_bit_and_is_in_range() {
        // toPositive(murmur2("abc")) % 64 — "abc" hashes positive, so the mask is a no-op there, but
        // the result must always be a valid partition index.
        for key in [
            "abc",
            "21",
            "foobar",
            "2:01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        ] {
            let partition = partition_for(key, COHORT_PARTITION_COUNT);
            assert!(partition < COHORT_PARTITION_COUNT, "{key} out of range");
            // Deterministic.
            assert_eq!(partition, partition_for(key, COHORT_PARTITION_COUNT));
        }
        // A key whose raw hash has the sign bit set still maps to a non-negative partition.
        let negative = murmur2(b"a-little-bit-long-string") as i32;
        assert!(negative < 0, "this vector's raw hash is negative");
        assert!(
            partition_for("a-little-bit-long-string", COHORT_PARTITION_COUNT)
                < COHORT_PARTITION_COUNT
        );
    }

    #[test]
    fn merge_partition_key_matches_the_shuffler_format() {
        // Mirrors cohort-event-shuffler's `partition_key_is_team_colon_person`: `"{team}:{person}"`,
        // with the UUID in its canonical hyphenated-lowercase form.
        let person = Uuid::from_u128(0x0192_8aaa_bbbb_cccc_dddd_eeee_eeee_eeee);
        assert_eq!(
            merge_partition_key(TeamId(42), &person),
            format!("42:{person}"),
        );
        assert_eq!(
            merge_partition_key(TeamId(2), &Uuid::nil()),
            "2:00000000-0000-0000-0000-000000000000",
        );
    }

    #[test]
    fn partition_of_is_partition_for_over_the_re_key() {
        let person = Uuid::from_u128(7);
        assert_eq!(
            partition_of(TeamId(42), &person, COHORT_PARTITION_COUNT),
            partition_for(
                &merge_partition_key(TeamId(42), &person),
                COHORT_PARTITION_COUNT
            ),
        );
    }

    #[test]
    fn distinct_persons_can_land_on_distinct_partitions() {
        // Sanity that the hash actually spreads — used by the cross-partition merge tests to pick a
        // P_old and P_new on different partitions.
        let team = TeamId(7);
        let p0 = partition_of(team, &Uuid::from_u128(1), COHORT_PARTITION_COUNT);
        let other = (2..1000)
            .map(|n| partition_of(team, &Uuid::from_u128(n), COHORT_PARTITION_COUNT))
            .find(|&p| p != p0);
        assert!(
            other.is_some(),
            "expected some person to hash to a different partition"
        );
    }
}
