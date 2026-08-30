//! The `log_comment` ClickHouse query setting the seeder stamps on every scan, so a row in
//! `system.query_log` names the run, chunk, and claim epoch that issued it. Depends on `domain`;
//! never on `store` or `kafka`.
//!
//! ClickHouse copies `log_comment` verbatim into `system.query_log.log_comment`, which is how an
//! operator joins a slow or killed query back to the chunk ledger. That join only works while every
//! call site renders the same field vocabulary, so this type is the sole writer: a scanner picks a
//! variant, never a format string.

use std::fmt;

use cohort_core::filters::TeamId;

use crate::domain::{ChunkSpec, RunId};

/// The setting name ClickHouse reads. Bound through `Query::with_option`, which URL-encodes the
/// value, so the rendered comment needs no escaping of its own.
pub const LOG_COMMENT_OPTION: &str = "log_comment";

/// One scan's attribution. Each variant carries only what identifies that query's work:
/// a person chunk has no meaningful `day` (person runs are planned under a far-future sentinel day
/// that would read as a real date in `query_log`), and a boundary aggregation runs before any chunk
/// exists.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScanLogComment {
    BehavioralChunk(ChunkSpec),
    PersonChunk(ChunkSpec),
    PersonBoundaries { run_id: RunId, team_id: TeamId },
}

impl ScanLogComment {
    const fn phase(self) -> &'static str {
        match self {
            Self::BehavioralChunk(_) => "behavioral",
            Self::PersonChunk(_) => "person_scan",
            Self::PersonBoundaries { .. } => "person_boundaries",
        }
    }
}

impl fmt::Display for ScanLogComment {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let phase = self.phase();
        match self {
            // `day` is the seeder's day index, the same value its logs and its chunk planner carry,
            // so an operator matches a `query_log` row to a log line without converting anything.
            Self::BehavioralChunk(spec) => write!(
                formatter,
                "cohort-seeder phase={phase} team={team} run={run} chunk={chunk} day={day} \
                 band={band}/{num_bands} epoch={epoch}",
                team = spec.team_id.0,
                run = spec.lease.run_id().0,
                chunk = spec.lease.chunk_id().0,
                day = spec.day,
                band = spec.band.band(),
                num_bands = spec.band.num_bands(),
                epoch = spec.lease.epoch().0,
            ),
            Self::PersonChunk(spec) => write!(
                formatter,
                "cohort-seeder phase={phase} team={team} run={run} chunk={chunk} \
                 band={band}/{num_bands} epoch={epoch}",
                team = spec.team_id.0,
                run = spec.lease.run_id().0,
                chunk = spec.lease.chunk_id().0,
                band = spec.band.band(),
                num_bands = spec.band.num_bands(),
                epoch = spec.lease.epoch().0,
            ),
            Self::PersonBoundaries { run_id, team_id } => write!(
                formatter,
                "cohort-seeder phase={phase} team={team} run={run}",
                team = team_id.0,
                run = run_id.0,
            ),
        }
    }
}

#[cfg(test)]
mod tests {
    use uuid::Uuid;

    use super::*;
    use crate::domain::{
        AttemptCount, BandSpec, ChunkId, ChunkLease, ClaimEpoch, PersonRange, SChunkMs,
    };

    fn spec(person_range: Option<PersonRange>) -> ChunkSpec {
        ChunkSpec {
            lease: ChunkLease::new(
                ChunkId(Uuid::from_u128(0xC0)),
                RunId(Uuid::from_u128(0x2A)),
                ClaimEpoch(7),
            ),
            team_id: TeamId(2),
            day: 20_000,
            band: BandSpec::new(3, 8).unwrap(),
            s_chunk: SChunkMs(1_700_000_000_000),
            person_range,
            attempt: AttemptCount::from_row(1),
        }
    }

    /// The rendered text is the join key an operator types into `system.query_log`, so it is pinned
    /// byte for byte: a renamed or reordered field silently breaks every saved query against it.
    #[test]
    fn each_scan_phase_renders_its_pinned_field_vocabulary() {
        assert_eq!(
            ScanLogComment::BehavioralChunk(spec(None)).to_string(),
            "cohort-seeder phase=behavioral team=2 \
             run=00000000-0000-0000-0000-00000000002a \
             chunk=00000000-0000-0000-0000-0000000000c0 day=20000 band=3/8 epoch=7"
        );
        let range = PersonRange::new(Uuid::from_u128(1), Some(Uuid::from_u128(2))).unwrap();
        assert_eq!(
            ScanLogComment::PersonChunk(spec(Some(range))).to_string(),
            "cohort-seeder phase=person_scan team=2 \
             run=00000000-0000-0000-0000-00000000002a \
             chunk=00000000-0000-0000-0000-0000000000c0 band=3/8 epoch=7"
        );
        assert_eq!(
            ScanLogComment::PersonBoundaries {
                run_id: RunId(Uuid::from_u128(0x2A)),
                team_id: TeamId(2),
            }
            .to_string(),
            "cohort-seeder phase=person_boundaries team=2 \
             run=00000000-0000-0000-0000-00000000002a"
        );
    }

    /// Every comment starts with the same literal prefix, which is what
    /// `log_comment LIKE 'cohort-seeder%'` selects on. A phase that lost the prefix would be
    /// invisible to the one query an operator runs to find the seeder's work.
    #[test]
    fn every_phase_shares_the_service_prefix_and_names_itself_once() {
        let range = PersonRange::new(Uuid::from_u128(1), None).unwrap();
        for comment in [
            ScanLogComment::BehavioralChunk(spec(None)),
            ScanLogComment::PersonChunk(spec(Some(range))),
            ScanLogComment::PersonBoundaries {
                run_id: RunId(Uuid::nil()),
                team_id: TeamId(2),
            },
        ] {
            let rendered = comment.to_string();
            assert!(
                rendered.starts_with("cohort-seeder phase="),
                "{rendered} does not carry the service prefix"
            );
            assert_eq!(
                rendered.matches("phase=").count(),
                1,
                "{rendered} names its phase more than once"
            );
        }
    }
}
