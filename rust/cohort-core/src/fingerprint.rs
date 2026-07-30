use sha2::{Digest, Sha256};

/// 128 bits of SHA-256 over the concatenation of a team's sorted person condition hashes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CatalogFingerprint(pub u128);

impl CatalogFingerprint {
    /// Fingerprint the already-sorted person condition hashes. The input must be sorted so a
    /// permutation of the same conditions yields one value.
    pub fn of_sorted(conditions: &[[u8; 16]]) -> Self {
        let mut hasher = Sha256::new();
        for condition in conditions {
            hasher.update(condition);
        }
        let digest = hasher.finalize();
        Self(u128::from_le_bytes(
            digest[..16].try_into().expect("SHA-256 yields 32 bytes"),
        ))
    }
}
