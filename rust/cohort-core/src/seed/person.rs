//! [`PersonSeed`]: one person's person-property scan verdict, produced by the backfill seeder and
//! applied by the stream processor to `cf_person_records`.
//!
//! Field order is the wire order. New fields must be appended and skipped at their
//! absent-equivalent value (see `redirect_hops`), or bytes an older seeder produced stop parsing.
//!
//! Every change here is consumer-first. An older consumer ignores an unknown field, so a producer
//! that starts populating one is silently half-understood; bumping the schema version instead
//! routes the payload to `UnsupportedSchema`, which commits the offset without applying. Either way
//! the consumer has to reach every pod before the producer emits.

use serde::de::{Deserializer, Error as DeError, Unexpected};
use serde::ser::{SerializeSeq, Serializer};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::filters::TeamId;

use super::ids::{ClaimEpoch, ConditionHash, ConditionHashError, RunId, ScannedAtMs};

pub(super) const PERSON_SCHEMA_VERSION: u32 = 1;
pub(super) const PERSON_KIND: &str = "person_property";

/// Decode guard bounding `evaluated`, and through the subset invariant `matched` too.
pub const MAX_PERSON_SEED_HASHES: usize = 1024;

/// `evaluated` is what the scan ran (sorted, distinct, non-empty); `matched ⊆ evaluated` is what
/// came back TRUE. A hash in `evaluated` but not in `matched` asserts FALSE, which is what lets a
/// seed retract a stale TRUE.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "PersonSeedWire")]
pub struct PersonSeed {
    schema_version: u32,
    kind: PersonKind,
    #[serde(serialize_with = "serialize_team_id")]
    team_id: TeamId,
    person_id: Uuid,
    #[serde(serialize_with = "serialize_hashes")]
    evaluated: Vec<ConditionHash>,
    #[serde(serialize_with = "serialize_hashes")]
    matched: Vec<ConditionHash>,
    scanned_at_ms: ScannedAtMs,
    run_id: RunId,
    claim_epoch: ClaimEpoch,
    /// Times re-produced to a merge survivor's partition. Absent on the wire at 0.
    #[serde(skip_serializing_if = "hops_are_zero")]
    redirect_hops: u8,
}

impl PersonSeed {
    /// The only constructor. [`Deserialize`] funnels through it too, so an illegal payload fails
    /// to decode instead of half-applying.
    pub fn new(
        team_id: TeamId,
        person_id: Uuid,
        evaluated: Vec<ConditionHash>,
        matched: Vec<ConditionHash>,
        scanned_at_ms: ScannedAtMs,
        run_id: RunId,
        claim_epoch: ClaimEpoch,
    ) -> Result<Self, PersonSeedError> {
        if evaluated.is_empty() {
            return Err(PersonSeedError::EvaluatedEmpty);
        }
        if evaluated.len() > MAX_PERSON_SEED_HASHES {
            return Err(PersonSeedError::EvaluatedTooLarge(evaluated.len()));
        }
        if !is_strictly_sorted(&evaluated) {
            return Err(PersonSeedError::EvaluatedNotSortedDistinct);
        }
        if !is_strictly_sorted(&matched) {
            return Err(PersonSeedError::MatchedNotSortedDistinct);
        }
        if !is_subset(&matched, &evaluated) {
            return Err(PersonSeedError::MatchedNotSubset);
        }
        if scanned_at_ms.0 <= 0 {
            return Err(PersonSeedError::ScannedAtNotPositive(scanned_at_ms.0));
        }
        Ok(Self {
            schema_version: PERSON_SCHEMA_VERSION,
            kind: PersonKind,
            team_id,
            person_id,
            evaluated,
            matched,
            scanned_at_ms,
            run_id,
            claim_epoch,
            redirect_hops: 0,
        })
    }

    /// The seed re-keyed to a merge survivor, or `None` once `cap` hops are exhausted, forcing the
    /// caller to handle exhaustion explicitly.
    #[must_use]
    pub fn rekeyed_to(&self, survivor: Uuid, cap: u8) -> Option<Self> {
        let redirect_hops = self
            .redirect_hops
            .checked_add(1)
            .filter(|hops| *hops <= cap)?;
        Some(Self {
            person_id: survivor,
            redirect_hops,
            ..self.clone()
        })
    }

    /// Must stay identical to [`super::tile::SeedTile::partition_key`]: both kinds have to land on
    /// the worker that owns the person's state.
    pub fn partition_key(&self) -> String {
        format!("{}:{}", self.team_id.0, self.person_id)
    }

    pub const fn team_id(&self) -> TeamId {
        self.team_id
    }

    pub const fn person_id(&self) -> Uuid {
        self.person_id
    }

    pub fn evaluated(&self) -> &[ConditionHash] {
        &self.evaluated
    }

    pub fn matched(&self) -> &[ConditionHash] {
        &self.matched
    }

    pub const fn scanned_at_ms(&self) -> ScannedAtMs {
        self.scanned_at_ms
    }

    pub const fn run_id(&self) -> RunId {
        self.run_id
    }

    pub const fn claim_epoch(&self) -> ClaimEpoch {
        self.claim_epoch
    }

    pub const fn redirect_hops(&self) -> u8 {
        self.redirect_hops
    }
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum PersonSeedError {
    #[error("evaluated must not be empty: a seed that ran no condition asserts nothing")]
    EvaluatedEmpty,
    #[error("evaluated must hold at most {MAX_PERSON_SEED_HASHES} hashes, got {0}")]
    EvaluatedTooLarge(usize),
    #[error("evaluated must be sorted and distinct")]
    EvaluatedNotSortedDistinct,
    #[error("matched must be sorted and distinct")]
    MatchedNotSortedDistinct,
    #[error("matched must be a subset of evaluated")]
    MatchedNotSubset,
    /// An unset or negative scan instant would floor `last_seen_ms` below every TTL cutoff and
    /// never win the apply path's last-write-wins comparison.
    #[error("scanned_at_ms must be a positive epoch-ms instant, got {0}")]
    ScannedAtNotPositive(i64),
    #[error("malformed condition hash: {0}")]
    Hash(#[from] ConditionHashError),
}

/// Raw strings for the hash lists, then one [`TryFrom`] into [`PersonSeed::new`]'s validation.
#[derive(Deserialize)]
struct PersonSeedWire {
    #[serde(deserialize_with = "deserialize_schema_version")]
    #[allow(dead_code)] // Validated by its deserializer, never read.
    schema_version: u32,
    #[allow(dead_code)] // Validated by its deserializer, never read.
    kind: PersonKind,
    #[serde(deserialize_with = "deserialize_team_id")]
    team_id: TeamId,
    person_id: Uuid,
    evaluated: Vec<String>,
    matched: Vec<String>,
    scanned_at_ms: ScannedAtMs,
    run_id: RunId,
    claim_epoch: ClaimEpoch,
    #[serde(default)]
    redirect_hops: u8,
}

impl TryFrom<PersonSeedWire> for PersonSeed {
    type Error = PersonSeedError;

    fn try_from(wire: PersonSeedWire) -> Result<Self, Self::Error> {
        let evaluated = parse_hashes(&wire.evaluated)?;
        let matched = parse_hashes(&wire.matched)?;
        let seed = Self::new(
            wire.team_id,
            wire.person_id,
            evaluated,
            matched,
            wire.scanned_at_ms,
            wire.run_id,
            wire.claim_epoch,
        )?;
        // Reinstated outside the constructor, which only ever mints hop 0. The cap belongs to the
        // re-keying caller (`rekeyed_to`), so validating it here would fork a second copy of a
        // constant this crate does not own; an over-cap value is already unrepresentable as a
        // further re-produce and degrades to an inline apply.
        Ok(Self {
            redirect_hops: wire.redirect_hops,
            ..seed
        })
    }
}

fn parse_hashes(raw: &[String]) -> Result<Vec<ConditionHash>, ConditionHashError> {
    raw.iter()
        .map(|value| ConditionHash::parse(value))
        .collect()
}

fn is_strictly_sorted(hashes: &[ConditionHash]) -> bool {
    hashes.windows(2).all(|pair| pair[0] < pair[1])
}

/// Subset test over two sorted-distinct lists, in one merge walk.
fn is_subset(subset: &[ConditionHash], superset: &[ConditionHash]) -> bool {
    let mut candidates = superset.iter();
    subset
        .iter()
        .all(|hash| candidates.any(|candidate| candidate == hash))
}

/// A zero-sized discriminant proven to be [`PERSON_KIND`] during deserialization.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct PersonKind;

impl Serialize for PersonKind {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(PERSON_KIND)
    }
}

impl<'de> Deserialize<'de> for PersonKind {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = String::deserialize(deserializer)?;
        if value != PERSON_KIND {
            return Err(DeError::invalid_value(
                Unexpected::Str(&value),
                &"seed kind \"person_property\"",
            ));
        }
        Ok(Self)
    }
}

fn hops_are_zero(hops: &u8) -> bool {
    *hops == 0
}

fn serialize_team_id<S: Serializer>(value: &TeamId, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_i32(value.0)
}

fn deserialize_team_id<'de, D: Deserializer<'de>>(deserializer: D) -> Result<TeamId, D::Error> {
    i32::deserialize(deserializer).map(TeamId)
}

fn serialize_hashes<S: Serializer>(
    hashes: &[ConditionHash],
    serializer: S,
) -> Result<S::Ok, S::Error> {
    let mut sequence = serializer.serialize_seq(Some(hashes.len()))?;
    for hash in hashes {
        sequence.serialize_element(hash.as_str())?;
    }
    sequence.end()
}

fn deserialize_schema_version<'de, D: Deserializer<'de>>(deserializer: D) -> Result<u32, D::Error> {
    let value = u32::deserialize(deserializer)?;
    if value != PERSON_SCHEMA_VERSION {
        return Err(DeError::invalid_value(
            Unexpected::Unsigned(u64::from(value)),
            &"person seed schema version 1",
        ));
    }
    Ok(value)
}

#[cfg(test)]
mod tests {
    use crate::partitioner::{partition_for, COHORT_PARTITION_COUNT};

    use super::*;

    fn hash(value: &str) -> ConditionHash {
        ConditionHash::parse(value).unwrap()
    }

    fn seed() -> PersonSeed {
        PersonSeed::new(
            TeamId(2),
            Uuid::from_u128(0x0192_8aaa_bbbb_cccc_dddd_eeee_eeee_eeee),
            vec![hash("0123456789abcdef"), hash("fedcba9876543210")],
            vec![hash("0123456789abcdef")],
            ScannedAtMs(1_783_470_000_000),
            RunId(Uuid::nil()),
            ClaimEpoch(4),
        )
        .unwrap()
    }

    #[test]
    fn person_seed_wire_contract_and_partition_key_are_fixed_by_construction() {
        let seed = seed();
        assert_eq!(
            seed.partition_key(),
            "2:01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        );
        assert_eq!(
            partition_for(&seed.partition_key(), COHORT_PARTITION_COUNT),
            58,
            "a person seed must route exactly like the same person's day tiles",
        );
        assert_eq!(
            serde_json::to_string(&seed).unwrap(),
            r#"{"schema_version":1,"kind":"person_property","team_id":2,"person_id":"01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee","evaluated":["0123456789abcdef","fedcba9876543210"],"matched":["0123456789abcdef"],"scanned_at_ms":1783470000000,"run_id":"00000000-0000-0000-0000-000000000000","claim_epoch":4}"#,
        );
        assert_eq!(
            serde_json::from_str::<PersonSeed>(&serde_json::to_string(&seed).unwrap()).unwrap(),
            seed,
        );
    }

    #[test]
    fn an_empty_matched_set_is_legal_and_is_the_stale_true_healing_case() {
        let healing = PersonSeed::new(
            TeamId(2),
            Uuid::from_u128(7),
            vec![hash("0123456789abcdef")],
            Vec::new(),
            ScannedAtMs(1),
            RunId(Uuid::nil()),
            ClaimEpoch(1),
        )
        .unwrap();
        assert!(healing.matched().is_empty());
        assert_eq!(
            serde_json::from_value::<PersonSeed>(serde_json::to_value(&healing).unwrap()).unwrap(),
            healing,
        );
    }

    #[test]
    fn the_constructor_rejects_every_illegal_hash_list() {
        let build = |evaluated: Vec<ConditionHash>, matched: Vec<ConditionHash>| {
            PersonSeed::new(
                TeamId(2),
                Uuid::from_u128(7),
                evaluated,
                matched,
                ScannedAtMs(1),
                RunId(Uuid::nil()),
                ClaimEpoch(1),
            )
        };
        let scanned_at = |ms: i64| {
            PersonSeed::new(
                TeamId(2),
                Uuid::from_u128(7),
                vec![hash("0123456789abcdef")],
                Vec::new(),
                ScannedAtMs(ms),
                RunId(Uuid::nil()),
                ClaimEpoch(1),
            )
        };
        let a = hash("0123456789abcdef");
        let b = hash("fedcba9876543210");

        assert_eq!(
            build(Vec::new(), Vec::new()),
            Err(PersonSeedError::EvaluatedEmpty)
        );
        assert_eq!(
            build(vec![a; MAX_PERSON_SEED_HASHES + 1], Vec::new()),
            Err(PersonSeedError::EvaluatedTooLarge(
                MAX_PERSON_SEED_HASHES + 1
            )),
        );
        assert_eq!(
            build(vec![b, a], Vec::new()),
            Err(PersonSeedError::EvaluatedNotSortedDistinct),
        );
        assert_eq!(
            build(vec![a, a], Vec::new()),
            Err(PersonSeedError::EvaluatedNotSortedDistinct),
            "a duplicate is as unrepresentable as a bad order",
        );
        assert_eq!(
            build(vec![a, b], vec![b, a]),
            Err(PersonSeedError::MatchedNotSortedDistinct),
        );
        assert_eq!(
            build(vec![a], vec![b]),
            Err(PersonSeedError::MatchedNotSubset),
            "a matched hash the scan never evaluated cannot be applied",
        );
        assert_eq!(
            scanned_at(0),
            Err(PersonSeedError::ScannedAtNotPositive(0)),
            "an unset scan instant floors last_seen below every TTL cutoff",
        );
        assert_eq!(
            scanned_at(-1),
            Err(PersonSeedError::ScannedAtNotPositive(-1))
        );
        assert!(scanned_at(1).is_ok());
    }

    #[test]
    fn deserialize_funnels_through_the_same_validation_as_the_constructor() {
        let golden = serde_json::to_value(seed()).unwrap();
        for (field, value, why) in [
            ("kind", serde_json::json!("behavioral_tile"), "foreign kind"),
            ("schema_version", serde_json::json!(2), "newer schema"),
            ("evaluated", serde_json::json!([]), "empty evaluated"),
            (
                "evaluated",
                serde_json::json!(["fedcba9876543210", "0123456789abcdef"]),
                "unsorted evaluated",
            ),
            (
                "evaluated",
                serde_json::json!(["0123456789abcdef", "0123456789abcdef"]),
                "duplicate evaluated",
            ),
            (
                "evaluated",
                serde_json::json!(vec!["0123456789abcdef"; MAX_PERSON_SEED_HASHES + 1]),
                "oversize evaluated",
            ),
            ("evaluated", serde_json::json!(["short"]), "malformed hash"),
            (
                "matched",
                serde_json::json!(["00000000000000ff"]),
                "matched outside evaluated",
            ),
            ("scanned_at_ms", serde_json::json!(0), "unset scan instant"),
        ] {
            let mut broken = golden.clone();
            broken[field] = value;
            assert!(
                serde_json::from_value::<PersonSeed>(broken).is_err(),
                "accepted a person seed with {why}",
            );
        }

        // An unknown future field is ignored, so an older consumer keeps parsing a newer producer.
        let mut extended = golden;
        extended["future_metadata"] = serde_json::json!({ "source": "seeder" });
        assert_eq!(
            serde_json::from_value::<PersonSeed>(extended).unwrap(),
            seed(),
        );
    }

    #[test]
    fn redirect_hops_are_absent_at_zero_and_roundtrip_when_set() {
        let seed = seed();
        assert!(!serde_json::to_string(&seed)
            .unwrap()
            .contains("redirect_hops"));

        let hopped = seed
            .rekeyed_to(Uuid::from_u128(1), 3)
            .and_then(|seed| seed.rekeyed_to(Uuid::from_u128(2), 3))
            .and_then(|seed| seed.rekeyed_to(Uuid::from_u128(3), 3))
            .unwrap();
        assert_eq!(hopped.redirect_hops(), 3);
        let encoded = serde_json::to_string(&hopped).unwrap();
        assert!(encoded.contains(r#""redirect_hops":3"#));
        assert_eq!(
            serde_json::from_str::<PersonSeed>(&encoded).unwrap(),
            hopped
        );
    }

    #[test]
    fn rekeyed_to_swaps_the_person_rides_the_scan_instant_and_exhausts_at_the_cap() {
        let seed = seed();
        let survivor = Uuid::from_u128(0xdead_beef);
        let rekeyed = seed.rekeyed_to(survivor, 2).unwrap();
        assert_eq!(rekeyed.person_id(), survivor);
        assert_eq!(rekeyed.redirect_hops(), 1);
        assert_eq!(rekeyed.scanned_at_ms(), seed.scanned_at_ms());
        assert_eq!(rekeyed.team_id(), seed.team_id());
        assert_eq!(rekeyed.evaluated(), seed.evaluated());
        assert_eq!(rekeyed.matched(), seed.matched());
        assert_eq!(rekeyed.run_id(), seed.run_id());
        assert_eq!(rekeyed.claim_epoch(), seed.claim_epoch());

        let at_cap = rekeyed.rekeyed_to(survivor, 2).unwrap();
        assert_eq!(at_cap.redirect_hops(), 2);
        assert!(at_cap.rekeyed_to(survivor, 2).is_none());
        assert!(seed.rekeyed_to(survivor, 0).is_none());
    }
}
