//! Slice coverage: what part of its partition's history a slice holds. Written when the slice
//! begins and deleted with it, never rewritten, so an older image cannot make it stale.

use cohort_core::seed::{CoverageStartMs, RunBoundaryMs};

/// Not the person-record format version `1`, so the TTL compaction filter keeps the value.
const VALUE_TAG: u8 = 0xC5;
const VALUE_FORMAT: u8 = 1;
const KIND_COMPLETE: u8 = 0;
const KIND_SINCE: u8 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SliceCoverage {
    /// The whole history. Only adoption writes it.
    Complete,
    /// Every event the partition delivered after this instant.
    Since(CoverageStartMs),
}

impl SliceCoverage {
    /// A run certifies only if coverage began at or before its boundary; with no boundary, only a
    /// complete slice does. `Err` is the boundary a recovery run needs. Assumes NTP-synced clocks.
    pub fn admits(self, boundary: Option<RunBoundaryMs>) -> Result<(), CoverageStartMs> {
        match (self, boundary) {
            (Self::Complete, _) => Ok(()),
            (Self::Since(start), Some(boundary)) if start.0 <= boundary.0 => Ok(()),
            (Self::Since(start), _) => Err(start),
        }
    }

    pub(crate) fn encode(self) -> Vec<u8> {
        match self {
            Self::Complete => vec![VALUE_TAG, VALUE_FORMAT, KIND_COMPLETE],
            Self::Since(start) => {
                let mut out = vec![VALUE_TAG, VALUE_FORMAT, KIND_SINCE];
                out.extend_from_slice(&start.0.to_be_bytes());
                out
            }
        }
    }

    /// `None` reads as no record, so the slice begins again.
    pub(crate) fn decode(bytes: &[u8]) -> Option<Self> {
        match bytes {
            [VALUE_TAG, VALUE_FORMAT, KIND_COMPLETE] => Some(Self::Complete),
            [VALUE_TAG, VALUE_FORMAT, KIND_SINCE, start @ ..] => Some(Self::Since(
                CoverageStartMs(i64::from_be_bytes(start.try_into().ok()?)),
            )),
            _ => None,
        }
    }
}

/// What resuming a slice found.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SliceTenure {
    Resumed(SliceCoverage),
    /// No record, so the slice holds nothing older than now.
    Begun(CoverageStartMs),
}

#[cfg(test)]
mod tests {
    use super::*;

    const T: i64 = 1_791_547_200_000;

    #[test]
    fn a_partial_slice_certifies_only_runs_whose_boundary_is_at_or_after_its_start() {
        let since = SliceCoverage::Since(CoverageStartMs(T));
        let cases = [
            (SliceCoverage::Complete, None, Ok(())),
            (SliceCoverage::Complete, Some(T - 1), Ok(())),
            (since, None, Err(CoverageStartMs(T))),
            (since, Some(T - 1), Err(CoverageStartMs(T))),
            (since, Some(T), Ok(())),
            (since, Some(T + 1), Ok(())),
        ];
        for (coverage, boundary, expected) in cases {
            assert_eq!(
                coverage.admits(boundary.map(RunBoundaryMs)),
                expected,
                "{coverage:?} against boundary {boundary:?}",
            );
        }
    }

    #[test]
    fn a_coverage_value_round_trips_and_anything_else_reads_as_no_record() {
        for coverage in [
            SliceCoverage::Complete,
            SliceCoverage::Since(CoverageStartMs(T)),
            SliceCoverage::Since(CoverageStartMs(i64::MIN)),
        ] {
            assert_eq!(SliceCoverage::decode(&coverage.encode()), Some(coverage));
        }

        let mut truncated = SliceCoverage::Since(CoverageStartMs(T)).encode();
        truncated.pop();
        let mut extended = SliceCoverage::Complete.encode();
        extended.push(0);
        let mut future_format = SliceCoverage::Complete.encode();
        future_format[1] = VALUE_FORMAT + 1;
        for undecodable in [
            Vec::new(),
            truncated,
            extended,
            future_format,
            vec![VALUE_TAG, VALUE_FORMAT, 7],
        ] {
            assert_eq!(SliceCoverage::decode(&undecodable), None, "{undecodable:?}");
        }
    }
}
