//! Which pod a checkpoint belongs to. Every local path and S3 key a checkpoint uses comes from a
//! [`CheckpointLineage`], so two ordinals never read or write each other's checkpoints.

use std::fmt;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::STORE_TOPIC;

/// The `n` in a StatefulSet pod name `cohort-stream-processor-n`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct PodOrdinal(u16);

#[derive(Debug, thiserror::Error)]
#[error("pod name {0:?} does not end in a StatefulSet ordinal")]
pub struct NotAnOrdinalPod(String);

impl PodOrdinal {
    /// A process outside a StatefulSet, a local run or a test, uses the lineage the single pod
    /// always used.
    pub const STANDALONE: Self = Self(0);

    /// Accepts only `<name>-<ascii digits>`, which is the only shape a StatefulSet gives. `u16`'s
    /// own parser also takes a leading `+`, which would map `x-+5` and `x-5` to one lineage.
    pub fn from_pod_name(name: &str) -> Result<Self, NotAnOrdinalPod> {
        name.rsplit_once('-')
            .map(|(_, digits)| digits)
            .filter(|digits| !digits.is_empty() && digits.bytes().all(|b| b.is_ascii_digit()))
            .and_then(|digits| digits.parse().ok())
            .map(Self)
            .ok_or_else(|| NotAnOrdinalPod(name.to_owned()))
    }
}

impl fmt::Display for PodOrdinal {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}

/// One pod's checkpoint lineage.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CheckpointLineage(PodOrdinal);

impl CheckpointLineage {
    pub fn new(ordinal: PodOrdinal) -> Self {
        Self(ordinal)
    }

    pub fn ordinal(self) -> PodOrdinal {
        self.0
    }

    /// `<base>/cohort_stream_state/<ordinal>`.
    pub fn local_dir(self, base: &Path) -> PathBuf {
        base.join(STORE_TOPIC).join(self.0.to_string())
    }

    /// `<hash>/<s3_key_prefix>/cohort_stream_state/<ordinal>/`. The hash spreads lineages across S3
    /// key partitions. Ordinal 0 keeps the single pod's original layout. The trailing slash keeps a
    /// sibling namespace from prefix-matching.
    pub fn remote_dir(self, s3_key_prefix: &str) -> String {
        let identity = format!("{STORE_TOPIC}/{}", self.0);
        let hash = Sha256::digest(identity.as_bytes());
        format!(
            "{:02x}{:02x}{:02x}{:02x}/{s3_key_prefix}/{identity}/",
            hash[0], hash[1], hash[2], hash[3]
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_a_statefulset_suffix_parses_to_an_ordinal() {
        let cases = [
            ("cohort-stream-processor-0", Some(0)),
            ("cohort-stream-processor-12", Some(12)),
            ("cohort-stream-processor-65535", Some(65535)),
            ("cohort-stream-processor", None),
            ("cohort-stream-processor-", None),
            ("cohort-stream-processor-+5", None),
            ("cohort-stream-processor-65536", None),
            ("cohort-stream-processor-1a", None),
        ];
        for (name, expected) in cases {
            assert_eq!(
                PodOrdinal::from_pod_name(name).ok(),
                expected.map(PodOrdinal),
                "{name}",
            );
        }
    }

    #[test]
    fn ordinal_zero_keeps_the_single_pod_layout_and_other_ordinals_get_their_own() {
        let zero = CheckpointLineage::new(PodOrdinal::STANDALONE);
        assert_eq!(
            zero.remote_dir("cohort-stream-checkpoints"),
            "819f7b67/cohort-stream-checkpoints/cohort_stream_state/0/",
        );
        assert_eq!(
            zero.local_dir(Path::new("/ckpt")),
            PathBuf::from("/ckpt/cohort_stream_state/0"),
        );

        let one = CheckpointLineage::new(PodOrdinal(1));
        let one_remote = one.remote_dir("cohort-stream-checkpoints");
        assert!(
            one_remote.ends_with("/cohort-stream-checkpoints/cohort_stream_state/1/"),
            "{one_remote}",
        );
        assert_ne!(
            one_remote[..8],
            zero.remote_dir("cohort-stream-checkpoints")[..8]
        );
        assert!(!one_remote.starts_with(&zero.remote_dir("cohort-stream-checkpoints")));
        assert_eq!(
            one.local_dir(Path::new("/ckpt")),
            PathBuf::from("/ckpt/cohort_stream_state/1"),
        );
    }
}
