/// Jump consistent hash maps a key to one of `num_buckets` buckets.
///
/// The result is deterministic and has the property that when `num_buckets`
/// changes from N to N+1, only ~1/(N+1) of the keys are reassigned.
///
/// Reference: Lamping & Veach, "A Fast, Minimal Memory, Consistent Hash Algorithm"
/// https://arxiv.org/abs/1406.2294
pub fn jump_consistent_hash(key: u64, num_buckets: i32) -> i32 {
    assert!(num_buckets > 0, "num_buckets must be positive");

    let mut k = key;
    let mut b: i64 = -1;
    let mut j: i64 = 0;

    while j < num_buckets as i64 {
        b = j;
        k = k.wrapping_mul(2862933555777941757).wrapping_add(1);
        j = ((b.wrapping_add(1) as f64) * (f64::from(1u32 << 31))
            / (((k >> 33).wrapping_add(1)) as f64)) as i64;
    }

    b as i32
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    #[test]
    fn deterministic_output() {
        for key in 0..100u64 {
            let a = jump_consistent_hash(key, 10);
            let b = jump_consistent_hash(key, 10);
            assert_eq!(a, b, "key {key} produced different results");
        }
    }

    #[test]
    fn output_within_range() {
        for key in 0..1000u64 {
            let bucket = jump_consistent_hash(key, 10);
            assert!((0..10).contains(&bucket), "key {key} mapped to {bucket}");
        }
    }

    #[test]
    fn single_bucket() {
        for key in 0..100u64 {
            assert_eq!(jump_consistent_hash(key, 1), 0);
        }
    }

    #[test]
    #[should_panic(expected = "num_buckets must be positive")]
    fn zero_buckets_panics() {
        jump_consistent_hash(0, 0);
    }

    #[test]
    fn scale_up_moves_minimal_keys() {
        let total_keys = 10_000u64;
        let old_buckets = 3;
        let new_buckets = 4;

        let mut moved = 0;
        for key in 0..total_keys {
            let old = jump_consistent_hash(key, old_buckets);
            let new = jump_consistent_hash(key, new_buckets);
            if old != new {
                moved += 1;
            }
        }

        // Theoretical minimum: ~1/(N+1) = 25% of keys move when going 3->4.
        let moved_pct = moved as f64 / total_keys as f64;
        let expected_pct = 1.0 / new_buckets as f64;
        assert!(
            (moved_pct - expected_pct).abs() < 0.05,
            "moved {moved_pct:.2}%, expected ~{expected_pct:.2}%"
        );
    }

    #[test]
    fn distribution_is_roughly_even() {
        let num_buckets = 5;
        let total_keys = 10_000u64;
        let mut counts: HashMap<i32, u64> = HashMap::new();

        for key in 0..total_keys {
            *counts
                .entry(jump_consistent_hash(key, num_buckets))
                .or_default() += 1;
        }

        let expected = total_keys / num_buckets as u64;
        for bucket in 0..num_buckets {
            let count = counts.get(&bucket).copied().unwrap_or(0);
            let deviation = (count as f64 - expected as f64).abs() / expected as f64;
            assert!(
                deviation < 0.1,
                "bucket {bucket} has {count} keys, expected ~{expected} (deviation {deviation:.2})"
            );
        }
    }

    #[test]
    fn keys_only_move_forward_on_scale_up() {
        // When scaling from N to N+1, keys either stay or move to bucket N.
        let old_buckets = 5;
        let new_buckets = 6;

        for key in 0..10_000u64 {
            let old = jump_consistent_hash(key, old_buckets);
            let new = jump_consistent_hash(key, new_buckets);
            assert!(
                old == new || new == new_buckets - 1,
                "key {key}: moved from bucket {old} to {new} (expected stay or move to {})",
                new_buckets - 1
            );
        }
    }
}
