//! The offset manifest: for every slice a checkpoint holds, where each input resumes.
//!
//! A RocksDB `Checkpoint` is a whole-DB snapshot, so one checkpoint freezes every slice at once. On
//! restore the DB content is materialized, but each input still needs to know where to resume on
//! each partition. Those positions live in a sibling `offsets.json` written alongside the checkpoint.
//!
//! The positions are the consumer groups' committed offsets, read from the broker just before the
//! checkpoint. Every commit follows a WAL fsync, so the checkpoint holds at least the state up to
//! them, and replay from them re-folds only what per-key `AppliedOffsets` already skips. That
//! holds only for this pod's own commits, so a manifest is built only from positions no other split
//! stamped.
//!
//! The manifest records the split it was captured under. A restore accepts it on any pod whose
//! partitions that split covers: its own lineage, or during a reshard its parent's.

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use super::format_version;
use crate::partitions::{InputTopic, OwnedPositions, PartitionOwnership, ResumeOffset};

/// Filename of the offset manifest, written as a sibling of the RocksDB checkpoint files and tracked
/// by the planner like any other file, so it rides the S3 upload/restore.
pub const MANIFEST_FILENAME: &str = "offsets.json";

/// Current on-disk shape version. Decode refuses any other, so a restore can tell a manifest written
/// by another build from a corrupt one.
pub const MANIFEST_VERSION: u32 = 3;

/// Fields are private: the only constructors are [`Self::capture`] and decoding, and both refuse a
/// slice that lacks a position on any input.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "ManifestWire", into = "ManifestWire")]
pub struct OffsetManifest {
    captured_at: DateTime<Utc>,
    split: PartitionOwnership,
    inputs: BTreeSet<InputTopic>,
    slices: BTreeMap<u16, BTreeMap<InputTopic, ResumeOffset>>,
}

#[derive(Debug, thiserror::Error)]
pub enum ManifestError {
    #[error("manifest format {found}; this build reads {MANIFEST_VERSION}")]
    UnsupportedFormat { found: u32 },
    #[error("slice {partition} has no position on {topic}")]
    Incomplete { partition: u16, topic: InputTopic },
    #[error("the manifest covers no slice")]
    Empty,
    #[error(transparent)]
    Decode(#[from] serde_json::Error),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}

/// The JSON shape.
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ManifestWire {
    version: u32,
    captured_at: DateTime<Utc>,
    split: PartitionOwnership,
    inputs: BTreeSet<InputTopic>,
    slices: BTreeMap<u16, BTreeMap<InputTopic, ResumeOffset>>,
}

impl TryFrom<ManifestWire> for OffsetManifest {
    type Error = ManifestError;

    fn try_from(wire: ManifestWire) -> Result<Self, Self::Error> {
        if wire.version != MANIFEST_VERSION {
            return Err(ManifestError::UnsupportedFormat {
                found: wire.version,
            });
        }
        if wire.slices.is_empty() {
            return Err(ManifestError::Empty);
        }
        for (&partition, positions) in &wire.slices {
            if let Some(topic) = wire.inputs.iter().find(|t| !positions.contains_key(*t)) {
                return Err(ManifestError::Incomplete {
                    partition,
                    topic: topic.clone(),
                });
            }
        }
        Ok(Self {
            captured_at: wire.captured_at,
            split: wire.split,
            inputs: wire.inputs,
            slices: wire.slices,
        })
    }
}

impl From<OffsetManifest> for ManifestWire {
    fn from(manifest: OffsetManifest) -> Self {
        Self {
            version: MANIFEST_VERSION,
            captured_at: manifest.captured_at,
            split: manifest.split,
            inputs: manifest.inputs,
            slices: manifest.slices,
        }
    }
}

impl OffsetManifest {
    /// Record `positions` for every owned slice, under the split that read them. Refuses an owned
    /// slice missing from any input's positions, and an empty `owned`.
    pub fn capture(
        owned: &BTreeSet<u16>,
        positions: OwnedPositions,
    ) -> Result<Self, ManifestError> {
        let slices = owned
            .iter()
            .map(|&partition| {
                let offsets = positions
                    .inputs()
                    .iter()
                    .filter_map(|input| {
                        let offset = input.offsets().get(&partition)?;
                        Some((input.topic().clone(), *offset))
                    })
                    .collect();
                (partition, offsets)
            })
            .collect();
        ManifestWire {
            version: MANIFEST_VERSION,
            captured_at: Utc::now(),
            split: positions.split(),
            inputs: positions
                .inputs()
                .iter()
                .map(|input| input.topic().clone())
                .collect(),
            slices,
        }
        .try_into()
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, ManifestError> {
        let version = format_version(bytes)?;
        if version != MANIFEST_VERSION {
            return Err(ManifestError::UnsupportedFormat { found: version });
        }
        serde_json::from_slice::<ManifestWire>(bytes)?.try_into()
    }

    pub fn load_from_dir(dir: &Path) -> Result<Self, ManifestError> {
        Self::decode(&std::fs::read(dir.join(MANIFEST_FILENAME))?)
    }

    /// Write `<dir>/offsets.json` atomically (tmp file + rename) so a reader never sees a torn file.
    pub fn write_to_dir(&self, dir: &Path) -> Result<(), ManifestError> {
        let json = serde_json::to_vec_pretty(self)?;
        let tmp_path = dir.join(".offsets.json.tmp");
        if let Err(e) = std::fs::write(&tmp_path, &json) {
            drop(std::fs::remove_file(&tmp_path));
            return Err(e.into());
        }
        std::fs::rename(&tmp_path, dir.join(MANIFEST_FILENAME))?;
        Ok(())
    }

    pub fn captured_at(&self) -> DateTime<Utc> {
        self.captured_at
    }

    pub fn split(&self) -> PartitionOwnership {
        self.split
    }

    pub fn inputs(&self) -> &BTreeSet<InputTopic> {
        &self.inputs
    }

    /// Where each input resumes on `partition`, or `None` when the checkpoint does not cover it.
    pub fn slice(&self, partition: u16) -> Option<&BTreeMap<InputTopic, ResumeOffset>> {
        self.slices.get(&partition)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tempfile::TempDir;

    use crate::partitions::InputPositions;

    const EVENTS: &str = "cohort_stream_events";
    const MERGES: &str = "person_merge_events";

    fn owned(inputs: Vec<InputPositions>) -> OwnedPositions {
        OwnedPositions::for_test(PartitionOwnership::single(4), inputs)
    }

    fn positions(topic: &str, offsets: &[(u16, i64)]) -> InputPositions {
        InputPositions::new(
            InputTopic::new(topic),
            offsets
                .iter()
                .map(|&(partition, offset)| (partition, ResumeOffset::try_from(offset).unwrap()))
                .collect(),
        )
    }

    #[test]
    fn capture_round_trips_and_refuses_an_owned_slice_one_input_lacks() {
        let slices = BTreeSet::from([0, 3]);
        let manifest = OffsetManifest::capture(
            &slices,
            owned(vec![
                positions(EVENTS, &[(0, 100), (3, 250)]),
                positions(MERGES, &[(0, 0), (3, 7)]),
            ]),
        )
        .unwrap();
        let dir = TempDir::new().unwrap();
        manifest.write_to_dir(dir.path()).unwrap();
        let loaded = OffsetManifest::load_from_dir(dir.path()).unwrap();
        assert_eq!(loaded, manifest);
        assert_eq!(loaded.split(), PartitionOwnership::single(4));
        assert_eq!(
            loaded.slice(3).unwrap()[&InputTopic::new(MERGES)],
            ResumeOffset::try_from(7).unwrap(),
        );
        assert_eq!(loaded.slice(1), None);

        let err = OffsetManifest::capture(
            &slices,
            owned(vec![
                positions(EVENTS, &[(0, 100), (3, 250)]),
                positions(MERGES, &[(0, 0)]),
            ]),
        )
        .unwrap_err();
        assert!(
            matches!(err, ManifestError::Incomplete { partition: 3, ref topic } if topic.as_str() == MERGES),
            "{err:?}",
        );
        assert!(matches!(
            OffsetManifest::capture(&BTreeSet::new(), owned(vec![positions(EVENTS, &[])])),
            Err(ManifestError::Empty),
        ));
    }

    #[test]
    fn decode_refuses_another_format_an_invalid_split_an_incomplete_slice_a_negative_offset_and_no_slices(
    ) {
        let split = json!({ "pods": 2, "ordinal": 1, "partitions": 4 });
        let wire = |version: u32, split: &serde_json::Value, slices: serde_json::Value| {
            json!({
                "version": version,
                "captured_at": "2026-10-09T16:00:00Z",
                "split": split,
                "inputs": [EVENTS, MERGES],
                "slices": slices,
            })
            .to_string()
        };
        let format_two = json!({
            "version": 2,
            "captured_at": "2026-10-09T16:00:00Z",
            "ordinal": 0,
            "inputs": [EVENTS, MERGES],
            "slices": { "0": { EVENTS: 1, MERGES: 2 } },
        })
        .to_string();
        let format_one = json!({
            "version": 1,
            "captured_at": "2026-10-09T16:00:00Z",
            "topics": { EVENTS: { "0": 100 } },
        })
        .to_string();

        let slice = || json!({ "1": { EVENTS: 1, MERGES: 2 } });

        let decoded =
            OffsetManifest::decode(wire(3, &split, slice()).as_bytes()).expect("format 3 decodes");
        assert_eq!(
            decoded.split(),
            PartitionOwnership::new(
                std::num::NonZeroU16::new(2).unwrap(),
                crate::store::durability::PodOrdinal::from(1),
                4
            )
            .unwrap(),
        );
        for (format, found) in [(&format_one, 1), (&format_two, 2)] {
            assert!(
                matches!(
                    OffsetManifest::decode(format.as_bytes()),
                    Err(ManifestError::UnsupportedFormat { found: f }) if f == found,
                ),
                "format {found}",
            );
        }
        let uneven = json!({ "pods": 3, "ordinal": 0, "partitions": 4 });
        assert!(matches!(
            OffsetManifest::decode(wire(3, &uneven, slice()).as_bytes()),
            Err(ManifestError::Decode(_)),
        ));
        assert!(matches!(
            OffsetManifest::decode(wire(3, &split, json!({ "1": { EVENTS: 1 } })).as_bytes()),
            Err(ManifestError::Incomplete { partition: 1, .. }),
        ));
        assert!(matches!(
            OffsetManifest::decode(
                wire(3, &split, json!({ "1": { EVENTS: -1, MERGES: 2 } })).as_bytes()
            ),
            Err(ManifestError::Decode(_)),
        ));
        assert!(matches!(
            OffsetManifest::decode(wire(3, &split, json!({})).as_bytes()),
            Err(ManifestError::Empty),
        ));
    }
}
