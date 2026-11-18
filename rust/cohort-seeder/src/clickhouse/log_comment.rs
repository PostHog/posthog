//! The `log_comment` ClickHouse query setting the seeder stamps on every scan, so a row in
//! `system.query_log` names the run, chunk, and claim epoch that issued it. Depends on `domain`;
//! never on `store` or `kafka`.
//!
//! ClickHouse copies `log_comment` verbatim into `system.query_log.log_comment`, which is how an
//! operator joins a slow or killed query back to the chunk ledger. That join only works while every
//! call site renders the same field vocabulary, so this type is the sole writer: a scanner picks a
//! variant, never a format string.
//!
//! The rendering is a JSON object because `system.query_log` has short retention and the durable
//! record is `query_log_archive`, which extracts its columns with `JSONExtract*` over
//! `log_comment` — `team_id`, `product`, `feature`, and `cohort_id` among them. A non-JSON comment
//! extracts to defaults, so every seeder scan would archive under team 0. The key vocabulary is
//! `posthog/clickhouse/query_tagging.py`'s, so the seeder's rows read the same as Django's.

use std::fmt;

use cohort_core::filters::{CohortId, TeamId};
use serde::Serialize;
use uuid::Uuid;

use crate::domain::{ChunkSpec, DayIdx, RunId};

/// The setting name ClickHouse reads. Bound through `Query::with_option`, which URL-encodes the
/// value, so the rendered comment needs no escaping of its own.
pub const LOG_COMMENT_OPTION: &str = "log_comment";

/// The `kind` every seeder comment carries, in the same slot `query_tagging.py` gives `"temporal"`
/// and `"dagster"`: the process that issued the query. This is what an operator filters the
/// archive on to select the seeder's work.
const SEEDER_KIND: &str = "cohort_seeder";

/// `Product.COHORTS` and `Feature.BEHAVIORAL_COHORTS` from `query_tagging.py`. Repeated here rather
/// than generated, because the Python enum is not reachable from Rust; the archive's `lc_product`
/// and `lc_feature` columns are what tie the two spellings together.
const COHORTS_PRODUCT: &str = "cohorts";
const BEHAVIORAL_COHORTS_FEATURE: &str = "behavioral_cohorts";

/// One scan's attribution. Each variant carries only what identifies that query's work:
/// a person chunk has no meaningful `day` (person runs are planned under a far-future sentinel day
/// that would read as a real date in `query_log`), and a boundary aggregation runs before any chunk
/// exists. An absent field is omitted rather than rendered empty, so `JSONExtract*` returns its
/// default and the archive column reads as "not applicable to this phase".
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScanLogComment {
    /// `cohort_id` is present only when every pinned condition on the run belongs to one cohort —
    /// the save-triggered shape. A team-enablement run spans cohorts, and naming any one of them
    /// would misattribute the scan's cost to it.
    BehavioralChunk {
        spec: ChunkSpec,
        cohort_id: Option<CohortId>,
    },
    /// The shadow compare's legacy wide re-scan of a behavioral chunk. Its own phase, so
    /// `query_log_archive` separates the diagnostic's cost from the authoritative scan's.
    BehavioralCompareChunk {
        spec: ChunkSpec,
        cohort_id: Option<CohortId>,
    },
    PersonChunk(ChunkSpec),
    PersonBoundaries {
        run_id: RunId,
        team_id: TeamId,
    },
}

impl ScanLogComment {
    const fn phase(self) -> &'static str {
        match self {
            Self::BehavioralChunk { .. } => "behavioral",
            Self::BehavioralCompareChunk { .. } => "behavioral_compare",
            Self::PersonChunk(_) => "person_scan",
            Self::PersonBoundaries { .. } => "person_boundaries",
        }
    }

    fn fields(self) -> LogCommentFields {
        let phase = self.phase();
        match self {
            // `day` is the seeder's day index, the same value its logs and its chunk planner carry,
            // so an operator matches a `query_log` row to a log line without converting anything.
            Self::BehavioralChunk { spec, cohort_id }
            | Self::BehavioralCompareChunk { spec, cohort_id } => LogCommentFields {
                cohort_id: cohort_id.map(|cohort_id| cohort_id.0),
                day: Some(spec.day),
                ..LogCommentFields::for_chunk(phase, spec)
            },
            Self::PersonChunk(spec) => LogCommentFields::for_chunk(phase, spec),
            Self::PersonBoundaries { run_id, team_id } => {
                LogCommentFields::for_run(phase, team_id, run_id)
            }
        }
    }
}

/// The rendered object. Field order is declaration order, which is what makes the byte-pinning
/// test below a contract rather than a snapshot of whatever order a map happened to produce.
#[derive(Debug, Serialize)]
struct LogCommentFields {
    kind: &'static str,
    product: &'static str,
    feature: &'static str,
    team_id: i32,
    #[serde(skip_serializing_if = "Option::is_none")]
    cohort_id: Option<i32>,
    run_id: Uuid,
    phase: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    chunk: Option<Uuid>,
    #[serde(skip_serializing_if = "Option::is_none")]
    day: Option<DayIdx>,
    #[serde(skip_serializing_if = "Option::is_none")]
    band: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    num_bands: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    epoch: Option<i32>,
}

impl LogCommentFields {
    /// The attribution every phase carries. The three constant keys are set here rather than
    /// defaulted, so a new variant cannot render an unattributed comment by forgetting them.
    fn for_run(phase: &'static str, team_id: TeamId, run_id: RunId) -> Self {
        Self {
            kind: SEEDER_KIND,
            product: COHORTS_PRODUCT,
            feature: BEHAVIORAL_COHORTS_FEATURE,
            team_id: team_id.0,
            cohort_id: None,
            run_id: run_id.0,
            phase,
            chunk: None,
            day: None,
            band: None,
            num_bands: None,
            epoch: None,
        }
    }

    fn for_chunk(phase: &'static str, spec: ChunkSpec) -> Self {
        Self {
            chunk: Some(spec.lease.chunk_id().0),
            band: Some(spec.band.band()),
            num_bands: Some(spec.band.num_bands().get()),
            epoch: Some(spec.lease.epoch().0),
            ..Self::for_run(phase, spec.team_id, spec.lease.run_id())
        }
    }
}

impl fmt::Display for ScanLogComment {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Every value is an integer, a UUID, or one of this module's static strings, so the only
        // way `to_string` fails is a serde bug. Rendering nothing would silently un-attribute the
        // scan, so the error surfaces as a formatting error instead.
        let json = serde_json::to_string(&self.fields()).map_err(|_| fmt::Error)?;
        formatter.write_str(&json)
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

    /// The rendered text is the join key an operator types into `system.query_log`, and the shape
    /// `query_log_archive` extracts its columns from, so it is pinned byte for byte: a renamed or
    /// reordered field silently breaks every saved query against it.
    #[test]
    fn each_scan_phase_renders_its_pinned_field_vocabulary() {
        assert_eq!(
            ScanLogComment::BehavioralChunk {
                spec: spec(None),
                cohort_id: None,
            }
            .to_string(),
            r#"{"kind":"cohort_seeder","product":"cohorts","feature":"behavioral_cohorts","#
                .to_owned()
                + r#""team_id":2,"run_id":"00000000-0000-0000-0000-00000000002a","#
                + r#""phase":"behavioral","chunk":"00000000-0000-0000-0000-0000000000c0","#
                + r#""day":20000,"band":3,"num_bands":8,"epoch":7}"#
        );
        assert_eq!(
            ScanLogComment::BehavioralChunk {
                spec: spec(None),
                cohort_id: Some(CohortId(91)),
            }
            .to_string(),
            r#"{"kind":"cohort_seeder","product":"cohorts","feature":"behavioral_cohorts","#
                .to_owned()
                + r#""team_id":2,"cohort_id":91,"run_id":"00000000-0000-0000-0000-00000000002a","#
                + r#""phase":"behavioral","chunk":"00000000-0000-0000-0000-0000000000c0","#
                + r#""day":20000,"band":3,"num_bands":8,"epoch":7}"#
        );
        assert_eq!(
            ScanLogComment::BehavioralCompareChunk {
                spec: spec(None),
                cohort_id: Some(CohortId(91)),
            }
            .to_string(),
            r#"{"kind":"cohort_seeder","product":"cohorts","feature":"behavioral_cohorts","#
                .to_owned()
                + r#""team_id":2,"cohort_id":91,"run_id":"00000000-0000-0000-0000-00000000002a","#
                + r#""phase":"behavioral_compare","chunk":"00000000-0000-0000-0000-0000000000c0","#
                + r#""day":20000,"band":3,"num_bands":8,"epoch":7}"#
        );
        let range = PersonRange::new(Uuid::from_u128(1), Some(Uuid::from_u128(2))).unwrap();
        assert_eq!(
            ScanLogComment::PersonChunk(spec(Some(range))).to_string(),
            r#"{"kind":"cohort_seeder","product":"cohorts","feature":"behavioral_cohorts","#
                .to_owned()
                + r#""team_id":2,"run_id":"00000000-0000-0000-0000-00000000002a","#
                + r#""phase":"person_scan","chunk":"00000000-0000-0000-0000-0000000000c0","#
                + r#""band":3,"num_bands":8,"epoch":7}"#
        );
        assert_eq!(
            ScanLogComment::PersonBoundaries {
                run_id: RunId(Uuid::from_u128(0x2A)),
                team_id: TeamId(2),
            }
            .to_string(),
            r#"{"kind":"cohort_seeder","product":"cohorts","feature":"behavioral_cohorts","#
                .to_owned()
                + r#""team_id":2,"run_id":"00000000-0000-0000-0000-00000000002a","#
                + r#""phase":"person_boundaries"}"#
        );
    }

    /// `query_log_archive` reads these four keys with `JSONExtract*`, and `team_id` is the archive
    /// table's own sort key. A phase that dropped one would archive unattributed — under team 0,
    /// which reads as a bug in someone else's product.
    #[test]
    fn every_phase_archives_under_its_team_product_and_feature() {
        let range = PersonRange::new(Uuid::from_u128(1), None).unwrap();
        for comment in [
            ScanLogComment::BehavioralChunk {
                spec: spec(None),
                cohort_id: None,
            },
            ScanLogComment::BehavioralCompareChunk {
                spec: spec(None),
                cohort_id: None,
            },
            ScanLogComment::PersonChunk(spec(Some(range))),
            ScanLogComment::PersonBoundaries {
                run_id: RunId(Uuid::nil()),
                team_id: TeamId(2),
            },
        ] {
            let rendered = comment.to_string();
            let parsed: serde_json::Value =
                serde_json::from_str(&rendered).expect("the comment is JSON");
            assert_eq!(parsed["team_id"], 2, "{rendered} lost its team");
            assert_eq!(parsed["kind"], SEEDER_KIND, "{rendered} lost its kind");
            assert_eq!(parsed["product"], "cohorts", "{rendered} lost its product");
            assert_eq!(
                parsed["feature"], "behavioral_cohorts",
                "{rendered} lost its feature"
            );
            assert_eq!(
                parsed["phase"],
                comment.phase(),
                "{rendered} lost its phase"
            );
        }
    }
}
