//! Wire contract for one partition-targeted reconcile control tile.

use std::fmt;
use std::str::FromStr;

use serde::de::{Deserializer, Error as DeError, Unexpected};
use serde::ser::Serializer;
use serde::{Deserialize, Serialize};

use crate::filters::{CohortId, TeamId};

use super::ids::{CoverageStartMs, RunBoundaryMs, RunId};

pub(super) const RECONCILE_SCHEMA_VERSION: u32 = 1;
pub(super) const RECONCILE_KIND: &str = "reconcile";
pub(super) const RECONCILE_PERSON_KIND: &str = "reconcile_person";

/// The bounds every persisted shape-hash column shares: non-empty, ASCII, at most 64 bytes.
fn validate_shape_hash(value: &str) -> Result<(), ShapeHashError> {
    if value.is_empty() {
        return Err(ShapeHashError::Empty);
    }
    if value.len() > 64 {
        return Err(ShapeHashError::TooLong(value.len()));
    }
    if !value.is_ascii() {
        return Err(ShapeHashError::NonAscii);
    }
    Ok(())
}

/// The persisted behavioral filter-shape fingerprint that fences a reconcile job from cohort edits.
///
/// Distinct from [`PersonShapeHash`] despite sharing its bounds: the type is what stops a person
/// hash from ever being compared against a behavioral one.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BehavioralShapeHash(Box<str>);

impl BehavioralShapeHash {
    pub fn parse(value: &str) -> Result<Self, ShapeHashError> {
        validate_shape_hash(value)?;
        Ok(Self(value.into()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// The persisted person-property filter-shape fingerprint, the person-run counterpart of
/// [`BehavioralShapeHash`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PersonShapeHash(Box<str>);

impl PersonShapeHash {
    pub fn parse(value: &str) -> Result<Self, ShapeHashError> {
        validate_shape_hash(value)?;
        Ok(Self(value.into()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum ShapeHashError {
    #[error("shape hash must not be empty")]
    Empty,
    #[error("shape hash must be at most 64 bytes, got {0}")]
    TooLong(usize),
    #[error("shape hash must contain only ASCII characters")]
    NonAscii,
}

/// Which definition fingerprint a reconcile is fenced by. Also the run kind it belongs to, so it
/// doubles as the queue-supersession key and a `&'static str` metric label.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ScopeKind {
    Behavioral,
    PersonProperty,
}

impl ScopeKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Behavioral => "behavioral",
            Self::PersonProperty => "person_property",
        }
    }
}

impl fmt::Display for ScopeKind {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl FromStr for ScopeKind {
    type Err = UnknownScopeKind;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "behavioral" => Ok(Self::Behavioral),
            "person_property" => Ok(Self::PersonProperty),
            other => Err(UnknownScopeKind(other.to_string())),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("unknown scope kind {0:?}")]
pub struct UnknownScopeKind(pub String);

/// Which definition fingerprint fences a reconcile from edits. On the wire the hash rides the
/// original `filters_hash` field and the variant rides the top-level `kind`: a behavioral tile
/// keeps the pre-person `"reconcile"` bytes, a person tile is `"reconcile_person"`. Riding the
/// kind rather than a body field is what protects a mixed-deploy fleet: a consumer predating the
/// split routes a person tile to `UnknownKind` and skip-commits it before the tile can reach its
/// reconcile queue — where, parsed as behavioral, it would evict a queued behavioral job for the
/// same cohort and leave that run permanently short a marker.
///
/// The skip is still a loss: the person run settles as a shortfall an operator re-dispatches after
/// the fleet upgrade, so every consumer must carry this decode before any producer emits a person
/// tile.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReconcileScope {
    Behavioral(BehavioralShapeHash),
    PersonProperty(PersonShapeHash),
}

impl ReconcileScope {
    pub fn parse(kind: ScopeKind, hash: &str) -> Result<Self, ShapeHashError> {
        Ok(match kind {
            ScopeKind::Behavioral => Self::Behavioral(BehavioralShapeHash::parse(hash)?),
            ScopeKind::PersonProperty => Self::PersonProperty(PersonShapeHash::parse(hash)?),
        })
    }

    pub const fn kind(&self) -> ScopeKind {
        match self {
            Self::Behavioral(_) => ScopeKind::Behavioral,
            Self::PersonProperty(_) => ScopeKind::PersonProperty,
        }
    }

    pub fn hash_str(&self) -> &str {
        match self {
            Self::Behavioral(hash) => hash.as_str(),
            Self::PersonProperty(hash) => hash.as_str(),
        }
    }
}

/// A control tile that requests one partition's full current snapshot for one cohort, fenced by the
/// dispatching run's [`ReconcileScope`].
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(try_from = "ReconcileTileWire")]
pub struct ReconcileTile {
    team_id: TeamId,
    cohort_id: CohortId,
    scope: ReconcileScope,
    run_id: RunId,
    boundary: Option<RunBoundaryMs>,
}

impl ReconcileTile {
    pub const fn new(
        team_id: TeamId,
        cohort_id: CohortId,
        scope: ReconcileScope,
        run_id: RunId,
        boundary: RunBoundaryMs,
    ) -> Self {
        Self {
            team_id,
            cohort_id,
            scope,
            run_id,
            boundary: Some(boundary),
        }
    }

    pub const fn team_id(&self) -> TeamId {
        self.team_id
    }

    pub const fn cohort_id(&self) -> CohortId {
        self.cohort_id
    }

    pub const fn scope(&self) -> &ReconcileScope {
        &self.scope
    }

    pub const fn run_id(&self) -> RunId {
        self.run_id
    }

    /// `None` on a tile from an older seeder.
    pub const fn boundary(&self) -> Option<RunBoundaryMs> {
        self.boundary
    }
}

/// The wire projection. Field order here is the wire order; the scope's kind picks the top-level
/// `kind` string, so a behavioral tile keeps the pre-person `"reconcile"` kind.
#[derive(Serialize)]
struct ReconcileTileOut<'a> {
    schema_version: u32,
    kind: &'static str,
    team_id: i32,
    cohort_id: i32,
    filters_hash: &'a str,
    run_id: RunId,
    #[serde(skip_serializing_if = "Option::is_none")]
    boundary_ms: Option<RunBoundaryMs>,
}

impl Serialize for ReconcileTile {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        ReconcileTileOut {
            schema_version: RECONCILE_SCHEMA_VERSION,
            kind: match self.scope.kind() {
                ScopeKind::Behavioral => RECONCILE_KIND,
                ScopeKind::PersonProperty => RECONCILE_PERSON_KIND,
            },
            team_id: self.team_id.0,
            cohort_id: self.cohort_id.0,
            filters_hash: self.scope.hash_str(),
            run_id: self.run_id,
            boundary_ms: self.boundary,
        }
        .serialize(serializer)
    }
}

/// The raw wire fields, funneled through [`TryFrom`] so an unparseable hash or an unrecognized kind
/// fails the decode rather than half-building a tile.
#[derive(Deserialize)]
struct ReconcileTileWire {
    #[serde(deserialize_with = "deserialize_schema_version")]
    #[allow(dead_code)] // Validated by its deserializer, never read.
    schema_version: u32,
    kind: ReconcileKind,
    team_id: i32,
    cohort_id: i32,
    filters_hash: String,
    run_id: RunId,
    boundary_ms: Option<RunBoundaryMs>,
}

impl TryFrom<ReconcileTileWire> for ReconcileTile {
    type Error = ReconcileTileError;

    fn try_from(wire: ReconcileTileWire) -> Result<Self, Self::Error> {
        let kind = wire.kind.scope_kind();
        let scope = ReconcileScope::parse(kind, &wire.filters_hash).map_err(|source| {
            ReconcileTileError {
                kind,
                hash: wire.filters_hash.clone(),
                source,
            }
        })?;
        Ok(Self {
            team_id: TeamId(wire.team_id),
            cohort_id: CohortId(wire.cohort_id),
            scope,
            run_id: wire.run_id,
            boundary: wire.boundary_ms,
        })
    }
}

/// Serde stringifies a `try_from` error, so the offending value and reason have to ride the message
/// — a decode failure is skip-and-count, and this line is the only forensics an operator gets.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("malformed {kind} shape hash {hash:?}: {source}")]
pub struct ReconcileTileError {
    kind: ScopeKind,
    hash: String,
    #[source]
    source: ShapeHashError,
}

/// The wire `kind` discriminant, proven to be [`RECONCILE_KIND`] or [`RECONCILE_PERSON_KIND`]
/// during deserialization.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct ReconcileKind(ScopeKind);

impl ReconcileKind {
    const fn scope_kind(self) -> ScopeKind {
        self.0
    }
}

impl<'de> Deserialize<'de> for ReconcileKind {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = String::deserialize(deserializer)?;
        match value.as_str() {
            RECONCILE_KIND => Ok(Self(ScopeKind::Behavioral)),
            RECONCILE_PERSON_KIND => Ok(Self(ScopeKind::PersonProperty)),
            _ => Err(DeError::invalid_value(
                Unexpected::Str(&value),
                &"seed kind \"reconcile\" or \"reconcile_person\"",
            )),
        }
    }
}

fn deserialize_schema_version<'de, D: Deserializer<'de>>(deserializer: D) -> Result<u32, D::Error> {
    let value = u32::deserialize(deserializer)?;
    if value != RECONCILE_SCHEMA_VERSION {
        return Err(DeError::invalid_value(
            Unexpected::Unsigned(u64::from(value)),
            &"reconcile schema version 1",
        ));
    }
    Ok(value)
}

/// A completion certificate emitted after one partition's reconcile snapshot is durable. Produced by
/// the stream processor onto the dedicated reconcile-marker topic and folded by the seeder's marker
/// watcher, so it lives here — the shared seed contract — rather than in either crate. Field order
/// is the wire order; the golden test below pins the exact bytes both ends depend on. Serialize it
/// through [`ReconcileMarker`], which adds the `type` tag.
///
/// Deliberately carries no dispatch epoch. A marker is a run-scoped durable fact: that partition's
/// snapshot drained under this run's pinned filters. If a re-dispatch's watcher folds a late marker
/// from the previous dispatch, it counts toward the same end state the new drain would reach — a run
/// is only re-dispatched for a *retryable* shortfall, whose hash still matches (a diverged cohort is
/// superseded and excluded), so both dispatches drain identical filters. Adding an epoch here would
/// discard that work and buy nothing.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReconcileCompleteMarker {
    team_id: i32,
    cohort_id: i32,
    partition: u16,
    run_id: RunId,
    /// ClickHouse `DateTime64(6)` wire format.
    last_updated: String,
}

impl ReconcileCompleteMarker {
    pub fn new(
        team_id: TeamId,
        cohort_id: CohortId,
        partition: u16,
        run_id: RunId,
        last_updated: String,
    ) -> Self {
        Self {
            team_id: team_id.0,
            cohort_id: cohort_id.0,
            partition,
            run_id,
            last_updated,
        }
    }

    pub const fn team_id(&self) -> TeamId {
        TeamId(self.team_id)
    }

    pub const fn cohort_id(&self) -> CohortId {
        CohortId(self.cohort_id)
    }

    pub const fn partition(&self) -> u16 {
        self.partition
    }

    pub const fn run_id(&self) -> RunId {
        self.run_id
    }

    pub fn last_updated(&self) -> &str {
        &self.last_updated
    }
}

/// Why the catalog rules out a reconcile.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CatalogMiss {
    TeamAbsent,
    CohortAbsent,
    NotEmitting,
    HashUnknown,
    HashMismatch,
}

impl CatalogMiss {
    const ALL: [Self; 5] = [
        Self::TeamAbsent,
        Self::CohortAbsent,
        Self::NotEmitting,
        Self::HashUnknown,
        Self::HashMismatch,
    ];

    /// The wire `reason` and a metric label.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::TeamAbsent => "team_absent",
            Self::CohortAbsent => "cohort_absent",
            Self::NotEmitting => "not_emitting",
            Self::HashUnknown => "hash_unknown",
            Self::HashMismatch => "hash_mismatch",
        }
    }

    fn parse(value: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|miss| miss.as_str() == value)
    }
}

const PARTIAL_COVERAGE: &str = "partial_coverage";

/// Why a partition withheld its reconcile certificate. Every reason is final for the run.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WithheldReason {
    /// The slice's history starts after the run's boundary. A recovery run needs a boundary at or
    /// after `covered_since`.
    PartialCoverage {
        covered_since: CoverageStartMs,
    },
    Catalog(CatalogMiss),
}

impl WithheldReason {
    /// The wire `reason` and a metric label.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::PartialCoverage { .. } => PARTIAL_COVERAGE,
            Self::Catalog(miss) => miss.as_str(),
        }
    }
}

/// A partition's refusal to certify a run. It shares the complete marker's key.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(try_from = "ReconcileWithheldWire")]
pub struct ReconcileWithheldMarker {
    team_id: TeamId,
    cohort_id: CohortId,
    partition: u16,
    run_id: RunId,
    reason: WithheldReason,
}

impl ReconcileWithheldMarker {
    pub const fn new(
        team_id: TeamId,
        cohort_id: CohortId,
        partition: u16,
        run_id: RunId,
        reason: WithheldReason,
    ) -> Self {
        Self {
            team_id,
            cohort_id,
            partition,
            run_id,
            reason,
        }
    }

    pub const fn team_id(&self) -> TeamId {
        self.team_id
    }

    pub const fn cohort_id(&self) -> CohortId {
        self.cohort_id
    }

    pub const fn partition(&self) -> u16 {
        self.partition
    }

    pub const fn run_id(&self) -> RunId {
        self.run_id
    }

    pub const fn reason(&self) -> WithheldReason {
        self.reason
    }
}

/// The wire projection. Field order is the wire order.
#[derive(Serialize)]
struct ReconcileWithheldOut {
    team_id: i32,
    cohort_id: i32,
    partition: u16,
    run_id: RunId,
    reason: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    covered_since_ms: Option<CoverageStartMs>,
}

impl Serialize for ReconcileWithheldMarker {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        ReconcileWithheldOut {
            team_id: self.team_id.0,
            cohort_id: self.cohort_id.0,
            partition: self.partition,
            run_id: self.run_id,
            reason: self.reason.as_str(),
            covered_since_ms: match self.reason {
                WithheldReason::PartialCoverage { covered_since } => Some(covered_since),
                WithheldReason::Catalog(_) => None,
            },
        }
        .serialize(serializer)
    }
}

/// Decoded through [`TryFrom`], so a malformed reason fails the decode.
#[derive(Deserialize)]
struct ReconcileWithheldWire {
    team_id: i32,
    cohort_id: i32,
    partition: u16,
    run_id: RunId,
    reason: String,
    covered_since_ms: Option<CoverageStartMs>,
}

impl TryFrom<ReconcileWithheldWire> for ReconcileWithheldMarker {
    type Error = WithheldReasonError;

    fn try_from(wire: ReconcileWithheldWire) -> Result<Self, Self::Error> {
        let reason = match (wire.reason.as_str(), wire.covered_since_ms) {
            (PARTIAL_COVERAGE, Some(covered_since)) => {
                WithheldReason::PartialCoverage { covered_since }
            }
            (PARTIAL_COVERAGE, None) => return Err(WithheldReasonError::MissingCoveredSince),
            (other, _) => WithheldReason::Catalog(
                CatalogMiss::parse(other)
                    .ok_or_else(|| WithheldReasonError::Unknown(wire.reason.clone()))?,
            ),
        };
        Ok(Self::new(
            TeamId(wire.team_id),
            CohortId(wire.cohort_id),
            wire.partition,
            wire.run_id,
            reason,
        ))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
enum WithheldReasonError {
    #[error("unknown withheld reason {0:?}")]
    Unknown(String),
    #[error("a partial_coverage reason must carry covered_since_ms")]
    MissingCoveredSince,
}

/// A reconcile outcome on `cohort_reconcile_markers`, tagged by `type`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum ReconcileMarker {
    #[serde(rename = "reconcile_complete")]
    Complete(ReconcileCompleteMarker),
    #[serde(rename = "reconcile_withheld")]
    Withheld(ReconcileWithheldMarker),
}

impl ReconcileMarker {
    pub const fn team_id(&self) -> TeamId {
        match self {
            Self::Complete(marker) => marker.team_id(),
            Self::Withheld(marker) => marker.team_id(),
        }
    }

    pub const fn cohort_id(&self) -> CohortId {
        match self {
            Self::Complete(marker) => marker.cohort_id(),
            Self::Withheld(marker) => marker.cohort_id(),
        }
    }

    pub const fn partition(&self) -> u16 {
        match self {
            Self::Complete(marker) => marker.partition(),
            Self::Withheld(marker) => marker.partition(),
        }
    }

    pub const fn run_id(&self) -> RunId {
        match self {
            Self::Complete(marker) => marker.run_id(),
            Self::Withheld(marker) => marker.run_id(),
        }
    }
}

#[cfg(test)]
mod tests {
    use uuid::Uuid;

    use super::*;

    // `extract_behavioral_leaf_shape_hash` for the canonical Python behavioral-leaf fixture.
    const SHA256: &str = "9efcd8a99c5334a19b52f6a7b990e3b862ad116031a0b47481f8bbb09e54a7de";

    fn tile() -> ReconcileTile {
        scoped_tile(ScopeKind::Behavioral)
    }

    fn scoped_tile(kind: ScopeKind) -> ReconcileTile {
        ReconcileTile::new(
            TeamId(2),
            CohortId(42),
            ReconcileScope::parse(kind, SHA256).unwrap(),
            RunId(Uuid::nil()),
            RunBoundaryMs(1_791_547_200_000),
        )
    }

    #[test]
    fn reconcile_wire_contract_is_fixed() {
        let tile = tile();
        assert_eq!(
            serde_json::to_value(&tile).unwrap(),
            serde_json::json!({
                "schema_version": 1,
                "kind": "reconcile",
                "team_id": 2,
                "cohort_id": 42,
                "filters_hash": SHA256,
                "run_id": "00000000-0000-0000-0000-000000000000",
                "boundary_ms": 1_791_547_200_000_i64,
            })
        );
        assert_eq!(
            serde_json::to_string(&tile).unwrap(),
            r#"{"schema_version":1,"kind":"reconcile","team_id":2,"cohort_id":42,"filters_hash":"9efcd8a99c5334a19b52f6a7b990e3b862ad116031a0b47481f8bbb09e54a7de","run_id":"00000000-0000-0000-0000-000000000000","boundary_ms":1791547200000}"#
        );
    }

    #[test]
    fn a_tile_from_a_seeder_without_boundaries_decodes_with_none_and_keeps_its_bytes() {
        let legacy = r#"{"schema_version":1,"kind":"reconcile","team_id":2,"cohort_id":42,"filters_hash":"9efcd8a99c5334a19b52f6a7b990e3b862ad116031a0b47481f8bbb09e54a7de","run_id":"00000000-0000-0000-0000-000000000000"}"#;
        let decoded = serde_json::from_str::<ReconcileTile>(legacy).unwrap();
        assert_eq!(decoded.boundary(), None);
        assert_eq!(decoded.scope(), tile().scope());
        assert_eq!(serde_json::to_string(&decoded).unwrap(), legacy);
    }

    #[test]
    fn reconcile_roundtrips_and_rejects_foreign_kind_schema_and_hash() {
        let tile = tile();
        let bytes = serde_json::to_vec(&tile).unwrap();
        assert_eq!(
            serde_json::from_slice::<ReconcileTile>(&bytes).unwrap(),
            tile
        );

        let golden = serde_json::to_value(&tile).unwrap();
        let mut extended = golden.clone();
        extended["future_metadata"] = serde_json::json!({ "source": "scheduler" });
        assert_eq!(
            serde_json::from_value::<ReconcileTile>(extended).unwrap(),
            tile
        );

        for (field, value) in [
            ("kind", serde_json::json!("behavioral_tile")),
            ("schema_version", serde_json::json!(2)),
            ("filters_hash", serde_json::json!("")),
            ("filters_hash", serde_json::json!("x".repeat(65))),
            ("filters_hash", serde_json::json!("non-ascii-é")),
        ] {
            let mut broken = golden.clone();
            broken[field] = value;
            assert!(
                serde_json::from_value::<ReconcileTile>(broken).is_err(),
                "accepted a reconcile tile with mutated {field}",
            );
        }
    }

    #[test]
    fn a_person_tile_rides_its_own_kind_and_legacy_bytes_stay_behavioral() {
        // The distinct kind is what routes a person tile to `UnknownKind` on a consumer predating
        // the split, instead of parsing as behavioral and evicting a queued behavioral job.
        let person = scoped_tile(ScopeKind::PersonProperty);
        assert_eq!(
            serde_json::to_string(&person).unwrap(),
            r#"{"schema_version":1,"kind":"reconcile_person","team_id":2,"cohort_id":42,"filters_hash":"9efcd8a99c5334a19b52f6a7b990e3b862ad116031a0b47481f8bbb09e54a7de","run_id":"00000000-0000-0000-0000-000000000000","boundary_ms":1791547200000}"#
        );
        assert_eq!(
            serde_json::from_str::<ReconcileTile>(&serde_json::to_string(&person).unwrap())
                .unwrap(),
            person,
        );

        // Bytes a pre-person seeder produced decode as the behavioral scope.
        assert_eq!(
            serde_json::from_value::<ReconcileTile>(serde_json::to_value(tile()).unwrap()).unwrap(),
            tile(),
        );
    }

    #[test]
    fn a_decode_failure_names_the_kind_and_the_offending_hash() {
        let mut broken = serde_json::to_value(scoped_tile(ScopeKind::PersonProperty)).unwrap();
        broken["filters_hash"] = serde_json::json!("non-ascii-é");
        let error = serde_json::from_value::<ReconcileTile>(broken)
            .unwrap_err()
            .to_string();
        assert!(error.contains("person_property"), "{error}");
        assert!(error.contains("non-ascii-é"), "{error}");
        assert!(error.contains("ASCII"), "{error}");
    }

    #[test]
    fn the_scope_kind_token_round_trips() {
        // The same string is the persisted `backfill_kind` value, the queue-supersession key, and
        // a metric label.
        for kind in [ScopeKind::Behavioral, ScopeKind::PersonProperty] {
            assert_eq!(kind.as_str().parse::<ScopeKind>().unwrap(), kind);
        }
        assert!("person".parse::<ScopeKind>().is_err());
    }

    fn withheld(reason: WithheldReason) -> ReconcileMarker {
        ReconcileMarker::Withheld(ReconcileWithheldMarker::new(
            TeamId(42),
            CohortId(91204),
            7,
            RunId(Uuid::nil()),
            reason,
        ))
    }

    #[test]
    fn both_reconcile_markers_have_the_exact_wire_contract() {
        let complete = ReconcileMarker::Complete(ReconcileCompleteMarker::new(
            TeamId(42),
            CohortId(91204),
            7,
            RunId(Uuid::nil()),
            "2026-05-26 12:34:56.789123".to_string(),
        ));
        let cases = [
            (
                complete,
                r#"{"type":"reconcile_complete","team_id":42,"cohort_id":91204,"partition":7,"run_id":"00000000-0000-0000-0000-000000000000","last_updated":"2026-05-26 12:34:56.789123"}"#,
            ),
            (
                withheld(WithheldReason::PartialCoverage {
                    covered_since: CoverageStartMs(1_791_547_200_000),
                }),
                r#"{"type":"reconcile_withheld","team_id":42,"cohort_id":91204,"partition":7,"run_id":"00000000-0000-0000-0000-000000000000","reason":"partial_coverage","covered_since_ms":1791547200000}"#,
            ),
            (
                withheld(WithheldReason::Catalog(CatalogMiss::HashMismatch)),
                r#"{"type":"reconcile_withheld","team_id":42,"cohort_id":91204,"partition":7,"run_id":"00000000-0000-0000-0000-000000000000","reason":"hash_mismatch"}"#,
            ),
        ];

        for (marker, golden) in cases {
            assert_eq!(serde_json::to_string(&marker).unwrap(), golden);
            assert_eq!(
                serde_json::from_str::<ReconcileMarker>(golden).unwrap(),
                marker
            );
        }
    }

    #[test]
    fn every_withheld_reason_rides_its_pinned_string() {
        // Also the `reason` metric label that alerts select on.
        let cases = [
            (
                WithheldReason::Catalog(CatalogMiss::TeamAbsent),
                "team_absent",
            ),
            (
                WithheldReason::Catalog(CatalogMiss::CohortAbsent),
                "cohort_absent",
            ),
            (
                WithheldReason::Catalog(CatalogMiss::NotEmitting),
                "not_emitting",
            ),
            (
                WithheldReason::Catalog(CatalogMiss::HashUnknown),
                "hash_unknown",
            ),
            (
                WithheldReason::Catalog(CatalogMiss::HashMismatch),
                "hash_mismatch",
            ),
            (
                WithheldReason::PartialCoverage {
                    covered_since: CoverageStartMs(1),
                },
                "partial_coverage",
            ),
        ];
        assert_eq!(
            cases.len(),
            CatalogMiss::ALL.len() + 1,
            "every reason is pinned"
        );

        for (reason, pinned) in cases {
            let marker = withheld(reason);
            let wire = serde_json::to_value(&marker).unwrap();
            assert_eq!(wire["reason"], pinned);
            assert_eq!(
                serde_json::from_value::<ReconcileMarker>(wire).unwrap(),
                marker
            );
        }
    }

    #[test]
    fn a_marker_decode_rejects_a_foreign_type_and_a_half_built_reason() {
        let partial = serde_json::to_value(withheld(WithheldReason::PartialCoverage {
            covered_since: CoverageStartMs(1),
        }))
        .unwrap();

        let mut extended = partial.clone();
        extended["future_metadata"] = serde_json::json!(1);
        assert!(serde_json::from_value::<ReconcileMarker>(extended).is_ok());

        let mut missing_instant = partial.clone();
        missing_instant
            .as_object_mut()
            .unwrap()
            .remove("covered_since_ms");
        let mut unknown_reason = partial.clone();
        unknown_reason["reason"] = serde_json::json!("store_on_fire");
        let mut foreign_type = partial;
        foreign_type["type"] = serde_json::json!("seed");

        for broken in [missing_instant, unknown_reason, foreign_type] {
            assert!(
                serde_json::from_value::<ReconcileMarker>(broken.clone()).is_err(),
                "accepted {broken}",
            );
        }
    }

    #[test]
    fn both_shape_hashes_match_the_persisted_column_bounds() {
        for kind in [ScopeKind::Behavioral, ScopeKind::PersonProperty] {
            let parse = |value: &str| ReconcileScope::parse(kind, value);
            assert_eq!(parse(SHA256).unwrap().hash_str(), SHA256, "{kind}");
            assert_eq!(parse("a").unwrap().hash_str(), "a", "{kind}");
            assert_eq!(parse("").unwrap_err(), ShapeHashError::Empty, "{kind}");
            assert_eq!(
                parse(&"x".repeat(65)).unwrap_err(),
                ShapeHashError::TooLong(65),
                "{kind}",
            );
            assert_eq!(parse("é").unwrap_err(), ShapeHashError::NonAscii, "{kind}");
        }
    }

    #[test]
    fn scopes_of_different_kinds_never_compare_equal() {
        assert_ne!(
            *scoped_tile(ScopeKind::Behavioral).scope(),
            *scoped_tile(ScopeKind::PersonProperty).scope(),
            "the same hash under two kinds is two different fences",
        );
    }
}
