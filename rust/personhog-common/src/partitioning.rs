//! Person → changelog-partition mapping shared by the router (routing) and
//! the leader (validation). Both sides must agree exactly: the router picks
//! the partition a request is sent to, and the leader rejects requests whose
//! `x-partition` doesn't match what it computes from the request body.

/// Compute the Kafka partition for a person. The key is `team_id:person_id`,
/// hashed with Kafka's default-partitioner murmur2 so partition placement
/// matches messages produced with the same key by any standard Kafka client.
pub fn partition_for_person(team_id: i64, person_id: i64, num_partitions: u32) -> u32 {
    assert!(num_partitions > 0, "num_partitions must be > 0");
    // i64 max string length is 20 chars. Two i64s + ':' = 41 bytes max.
    let mut buf = [0u8; 41];
    let len = {
        use std::io::Write;
        let mut cursor = std::io::Cursor::new(&mut buf[..]);
        write!(cursor, "{team_id}:{person_id}").unwrap();
        cursor.position() as usize
    };
    let hash = kafka_murmur2(&buf[..len]);
    // Kafka's toPositive: hash & 0x7fffffff
    let positive = (hash & 0x7fffffff) as u32;
    positive % num_partitions
}

/// Kafka-compatible murmur2 hash.
///
/// This matches the Java Kafka client's `Utils.murmur2()` implementation
/// so that partition assignment is consistent with Kafka's default partitioner.
fn kafka_murmur2(data: &[u8]) -> i32 {
    let length = data.len();
    let seed: i32 = 0x9747b28cu32 as i32;
    let m: i32 = 0x5bd1e995u32 as i32;
    let r: u32 = 24;

    let mut h: i32 = seed ^ (length as i32);

    let length4 = length / 4;
    for i in 0..length4 {
        let i4 = i * 4;
        let mut k: i32 = (data[i4] as i32 & 0xff)
            | ((data[i4 + 1] as i32 & 0xff) << 8)
            | ((data[i4 + 2] as i32 & 0xff) << 16)
            | ((data[i4 + 3] as i32 & 0xff) << 24);

        k = k.wrapping_mul(m);
        k ^= (k as u32 >> r) as i32;
        k = k.wrapping_mul(m);
        h = h.wrapping_mul(m);
        h ^= k;
    }

    let tail = length & !3;
    match length % 4 {
        3 => {
            h ^= (data[tail + 2] as i32 & 0xff) << 16;
            h ^= (data[tail + 1] as i32 & 0xff) << 8;
            h ^= data[tail] as i32 & 0xff;
            h = h.wrapping_mul(m);
        }
        2 => {
            h ^= (data[tail + 1] as i32 & 0xff) << 8;
            h ^= data[tail] as i32 & 0xff;
            h = h.wrapping_mul(m);
        }
        1 => {
            h ^= data[tail] as i32 & 0xff;
            h = h.wrapping_mul(m);
        }
        _ => {}
    }

    h ^= (h as u32 >> 13) as i32;
    h = h.wrapping_mul(m);
    h ^= (h as u32 >> 15) as i32;

    h
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn murmur2_deterministic_and_consistent() {
        // Same input always produces same hash
        let h1 = kafka_murmur2(b"42");
        let h2 = kafka_murmur2(b"42");
        assert_eq!(h1, h2);

        // Different inputs produce different hashes
        let h3 = kafka_murmur2(b"43");
        assert_ne!(h1, h3);
    }

    /// Pin murmur2 output so accidental algorithm changes are caught.
    /// These values must match `org.apache.kafka.common.utils.Utils.murmur2()`
    /// to ensure partition assignment is consistent with Kafka's default partitioner.
    #[test]
    fn murmur2_pinned_values() {
        assert_eq!(kafka_murmur2(b""), 275646681);
        assert_eq!(kafka_murmur2(b"21"), -973932308);
        assert_eq!(kafka_murmur2(b"42"), 417700972);
        assert_eq!(kafka_murmur2(b"1:42"), -1141388408);
        assert_eq!(kafka_murmur2(b"hello"), 2132663229);
        assert_eq!(kafka_murmur2(b"test-key"), -1341026247);
    }

    #[test]
    fn partition_for_person_deterministic() {
        let p1 = partition_for_person(1, 42, 16);
        let p2 = partition_for_person(1, 42, 16);
        assert_eq!(p1, p2);
        assert!(p1 < 16);

        // Different person_ids should (likely) produce different partitions
        let p3 = partition_for_person(1, 43, 16);
        assert!(p3 < 16);
    }

    #[test]
    fn partition_distribution_is_reasonable() {
        let mut counts = [0u32; 8];
        for person_id in 1..=1000 {
            let partition = partition_for_person(1, person_id, 8);
            counts[partition as usize] += 1;
        }

        // Each partition should get at least some keys (rough check)
        for (i, count) in counts.iter().enumerate() {
            assert!(
                *count > 50,
                "partition {i} only got {count} keys out of 1000"
            );
        }
    }
}
