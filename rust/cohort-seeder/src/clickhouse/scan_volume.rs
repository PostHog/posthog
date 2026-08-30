//! Reads a finished scan cursor's byte counters and meters them. Depends on `domain` and the
//! `clickhouse` crate; never on `store` or `kafka`.
//!
//! Both scan paths call [`observe`] at exactly one place, after their cursor loop has stopped for
//! any reason, so the counters cover halts and failures as well as clean exhaustion. That is the
//! point: a chunk that died at the ClickHouse execution-time limit still moved bytes, and those are
//! the chunks worth sizing.

use clickhouse::query::RowCursor;
use metrics::counter;

use crate::domain::ScanVolume;
use crate::observability::metrics::{SCAN_DECODED_BYTES, SCAN_RECEIVED_BYTES};

/// Which scan a volume came from. The two paths read different tables with different row shapes, so
/// one series would average them into a number describing neither.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScanKind {
    Behavioral,
    Person,
}

impl ScanKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Behavioral => "behavioral",
            Self::Person => "person",
        }
    }
}

/// Read what the cursor moved and add it to the counters.
///
/// The cursor counts only what the client actually pulled, so a scan cancelled by shutdown or a
/// lost lease reports less than the query would have returned. That is the intended reading: these
/// counters measure transferred bytes, not query result size.
pub fn observe<T>(kind: ScanKind, cursor: &RowCursor<T>) -> ScanVolume {
    let volume = ScanVolume::new(cursor.received_bytes(), cursor.decoded_bytes());
    counter!(SCAN_RECEIVED_BYTES, "kind" => kind.as_str()).increment(volume.received_bytes());
    counter!(SCAN_DECODED_BYTES, "kind" => kind.as_str()).increment(volume.decoded_bytes());
    volume
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scan_kinds_carry_distinct_label_values() {
        assert_eq!(ScanKind::Behavioral.as_str(), "behavioral");
        assert_eq!(ScanKind::Person.as_str(), "person");
    }
}
