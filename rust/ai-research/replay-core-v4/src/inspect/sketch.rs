//! A HyperLogLog sketch of a set of strings: small enough for an index row, and the union of two sets is the
//! register-wise maximum of their sketches, so a fold of rows counts the distinct values of all of them.

use sha2::{Digest, Sha256};

/// The standard error of [`DistinctSketch::estimate`] is about `1.04 / sqrt(REGISTERS)`.
pub const REGISTERS: usize = 64;
const REGISTER_BITS: u32 = REGISTERS.trailing_zeros();
const MAX_RANK: u32 = u64::BITS - REGISTER_BITS + 1;
const HYPERLOGLOG_BIAS_CORRECTION_FOR_64_REGISTERS: f64 = 0.709;

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct DistinctSketch([u8; REGISTERS]);

impl Default for DistinctSketch {
    fn default() -> Self {
        Self([0; REGISTERS])
    }
}

impl DistinctSketch {
    pub fn insert(&mut self, value: &str) {
        let digest = Sha256::digest(value.as_bytes());
        let hash = u64::from_be_bytes(
            digest[..8]
                .try_into()
                .expect("a SHA-256 digest has 8 bytes"),
        );
        let register = (hash >> (u64::BITS - REGISTER_BITS)) as usize;
        let rank = ((hash << REGISTER_BITS).leading_zeros() + 1).min(MAX_RANK) as u8;
        self.0[register] = self.0[register].max(rank);
    }

    pub fn merge(&mut self, other: &DistinctSketch) {
        for (register, other) in self.0.iter_mut().zip(other.0) {
            *register = (*register).max(other);
        }
    }

    pub fn is_empty(&self) -> bool {
        self.0.iter().all(|&rank| rank == 0)
    }

    pub fn estimate(&self) -> f64 {
        let registers = REGISTERS as f64;
        let empty = self.0.iter().filter(|&&rank| rank == 0).count();
        let harmonic: f64 = self.0.iter().map(|&rank| (-f64::from(rank)).exp2()).sum();
        let raw = HYPERLOGLOG_BIAS_CORRECTION_FOR_64_REGISTERS * registers * registers / harmonic;
        if raw <= 2.5 * registers && empty > 0 {
            registers * (registers / empty as f64).ln()
        } else {
            raw
        }
    }

    /// The registers that hold a rank, each as `register * 64 + rank`, in register order: the form an index row
    /// stores, so that a block with few values takes few entries.
    pub fn entries(&self) -> Vec<u16> {
        self.0
            .iter()
            .enumerate()
            .filter(|(_, &rank)| rank > 0)
            .map(|(register, &rank)| (register as u16) << 6 | u16::from(rank))
            .collect()
    }

    pub fn from_entries(entries: impl IntoIterator<Item = i64>) -> Self {
        let mut sketch = Self::default();
        for entry in entries {
            let (Ok(register), Ok(rank)) = (usize::try_from(entry >> 6), u8::try_from(entry & 63))
            else {
                continue;
            };
            if let Some(slot) = sketch.0.get_mut(register) {
                *slot = (*slot).max(rank);
            }
        }
        sketch
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sketch_of(values: impl IntoIterator<Item = usize>) -> DistinctSketch {
        let mut sketch = DistinctSketch::default();
        for value in values {
            sketch.insert(&format!("image:v4:2:2026-11:{value}"));
        }
        sketch
    }

    #[test]
    fn estimates_a_count_within_three_standard_errors() {
        for (distinct, repeats) in [(0, 1), (1, 5), (40, 3), (1_000, 2), (50_000, 1)] {
            let sketch = sketch_of((0..repeats).flat_map(|_| 0..distinct));
            let estimate = sketch.estimate();
            let allowed = (3.0 * 1.04 / (REGISTERS as f64).sqrt() * distinct as f64).max(0.5);
            assert!(
                (estimate - distinct as f64).abs() <= allowed,
                "{distinct} distinct values estimated as {estimate}"
            );
        }
    }

    #[test]
    fn the_merge_of_two_sketches_is_the_sketch_of_the_union() {
        let mut merged = sketch_of(0..3_000);
        merged.merge(&sketch_of(2_000..7_000));

        assert_eq!(merged, sketch_of(0..7_000));
    }

    #[test]
    fn its_entries_read_back_as_the_same_sketch() {
        for sketch in [
            DistinctSketch::default(),
            sketch_of(0..3),
            sketch_of(0..100_000),
        ] {
            let entries = sketch.entries().into_iter().map(i64::from);

            assert_eq!(DistinctSketch::from_entries(entries), sketch);
        }
    }
}
