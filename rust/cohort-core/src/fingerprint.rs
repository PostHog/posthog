use sha2::{Digest, Sha256};

/// Raise with any change to `cohort_execution_context` that can flip a verdict, so that every stored
/// person record is evaluated again instead of keeping a verdict of the old rules.
const EVALUATOR_VERSION: u8 = 1;

/// 128 bits of SHA-256 over [`EVALUATOR_VERSION`] and a team's sorted person condition hashes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CatalogFingerprint(pub u128);

impl CatalogFingerprint {
    /// Fingerprint the already-sorted person condition hashes. The input must be sorted so a
    /// permutation of the same conditions yields one value.
    pub fn of_sorted(conditions: &[[u8; 16]]) -> Self {
        let mut hasher = Sha256::new();
        hasher.update([EVALUATOR_VERSION]);
        for condition in conditions {
            hasher.update(condition);
        }
        let digest = hasher.finalize();
        Self(u128::from_le_bytes(
            digest[..16].try_into().expect("SHA-256 yields 32 bytes"),
        ))
    }
}
