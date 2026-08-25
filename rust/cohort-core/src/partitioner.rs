//! Kafka-compatible `murmur2` partitioner.
//!
//! Uses the `murmur2_random` algorithm (`(murmur2(key) & 0x7fffffff) % partitions`) — the
//! Kafka-Java / python-kafka / Node default, not librdkafka's CRC32 `consistent_random`. The merge
//! protocol must place a merge on the worker that owns `murmur2(hash(team, person)) mod 64`, so it
//! reproduces that math here. Pinned by the published Kafka test vectors below.

use uuid::Uuid;

use crate::filters::TeamId;

/// The `cohort_stream_events` partition count. All co-partitioned topics must match.
pub const COHORT_PARTITION_COUNT: u32 = 64;

const MURMUR2_SEED: u32 = 0x9747_b28c;
const MURMUR2_M: u32 = 0x5bd1_e995;
const MURMUR2_R: u32 = 24;

/// Kafka `murmur2` hash. Returns raw `u32`; [`partition_for`] applies the positivity mask.
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

/// The partition `key` lands on: `(murmur2(key) & 0x7fffffff) % partition_count`.
///
/// # Panics
/// Panics if `partition_count` is zero.
pub fn partition_for(key: &str, partition_count: u32) -> u32 {
    assert!(partition_count > 0, "partition_count must be non-zero");
    (murmur2(key.as_bytes()) & 0x7fff_ffff) % partition_count
}

/// The partition key for a `(team, person)` pair: `"{team_id}:{person_id}"`. Must match the
/// shuffler's `partition_key` exactly.
pub fn merge_partition_key(team_id: TeamId, person: &Uuid) -> String {
    format!("{}:{}", team_id.0, person)
}

/// The partition a `(team, person)` pair's state lives on.
pub fn partition_of(team_id: TeamId, person: &Uuid, partition_count: u32) -> u32 {
    partition_for(&merge_partition_key(team_id, person), partition_count)
}

#[cfg(test)]
mod tests {
    use super::*;

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
    fn cross_language_fixture_is_pinned_at_64_and_8_partitions() {
        // Mirrors the Node/Python self-test fixture (`murmur2.test.ts`, harness `partition.py`).
        // Pinning both counts keeps the COHORT_PARTITION_COUNT env override from silently changing
        // placement math: the raw hash is fixed, only the modulus varies with the configured count.
        let key = "2:01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee";
        assert_eq!(
            murmur2(key.as_bytes()),
            989_609_914,
            "raw murmur2 is the cross-language anchor"
        );
        assert_eq!(
            partition_for(key, 64),
            58,
            "production count (64) → partition 58"
        );
        assert_eq!(
            partition_for(key, 8),
            2,
            "frugal test-lane count (8) → partition 2"
        );
    }

    #[test]
    fn partition_for_masks_the_sign_bit_and_is_in_range() {
        for key in [
            "abc",
            "21",
            "foobar",
            "2:01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        ] {
            let partition = partition_for(key, COHORT_PARTITION_COUNT);
            assert!(partition < COHORT_PARTITION_COUNT, "{key} out of range");
            assert_eq!(partition, partition_for(key, COHORT_PARTITION_COUNT));
        }
        let negative = murmur2(b"a-little-bit-long-string") as i32;
        assert!(negative < 0, "this vector's raw hash is negative");
        assert!(
            partition_for("a-little-bit-long-string", COHORT_PARTITION_COUNT)
                < COHORT_PARTITION_COUNT
        );
    }

    #[test]
    fn merge_partition_key_matches_the_shuffler_format() {
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
