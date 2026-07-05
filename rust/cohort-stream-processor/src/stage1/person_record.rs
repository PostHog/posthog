//! The durable per-person record: one row that collapses all of a person's person-property leaf
//! state into a single value, plus the pure decision core that drives its update.
//!
//! Where per-leaf `PersonProperty` rows each carried their own last-write-wins bit, argMax stamp,
//! and replay-dedup offsets, a [`PersonRecord`] carries them once for the whole person:
//!
//! - A record-level argMax [`Stamp`] (`(ms, offset)`) decides staleness for the person as a unit,
//!   with the same "an equal-or-older stamp is stale" rule the per-leaf path used.
//! - A [`PropsFingerprint`] (SHA-256 of the raw `person_properties`) and a [`CatalogFingerprint`]
//!   (SHA-256 over the sorted person condition hashes) together decide whether the person's
//!   evaluated membership can possibly have changed: if both match the stored record, no HogVM
//!   evaluation is needed.
//! - A [`MatchedSet`] of the condition hashes that currently evaluate TRUE replaces the per-leaf
//!   bits; membership transitions are the set difference between the stored and freshly-evaluated
//!   sets, so per-condition transition continuity across catalog edits is preserved.
//! - The replay-dedup offsets (`applied_offsets` + `redirect_dedup`) are shared with the per-row
//!   codec via the same free functions in [`crate::stage1::state`], so record- and row-level dedup
//!   cannot drift.
//!
//! The [`decide`] / `apply_*` split is a pure, table-testable core with no store, HogVM, or clock:
//! [`decide`] classifies an event against the prior record into a [`Decision`], and the `apply_*`
//! constructors build the next record for each arm. The freshness decision table lives entirely in
//! these functions.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::stage1::state::{dedup_is_replay, dedup_record, AppliedOffsets};
use crate::stage1::transition::TransitionKind;

/// The record-level argMax key: last-write-wins ordered by event time then source offset. "Fresh"
/// is strictly greater — an equal-or-older stamp is stale, matching the per-leaf `PersonProperty`
/// comparison `(event_ms, offset) <= (prev_at, prev_off)` that classified a stale write.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Stamp {
    pub ms: i64,
    pub offset: i64,
}

impl Stamp {
    /// The baseline for an absent (or corrupt) prior record: older than every real event, so the
    /// first event is always fresh against it.
    pub const MIN: Self = Self {
        ms: i64::MIN,
        offset: i64::MIN,
    };

    pub fn new(ms: i64, offset: i64) -> Self {
        Self { ms, offset }
    }
}

impl PartialOrd for Stamp {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for Stamp {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        // Lexicographic: ms first, offset as the tiebreaker — the same key the per-leaf argMax used.
        (self.ms, self.offset).cmp(&(other.ms, other.offset))
    }
}

/// 128 bits of SHA-256 over the raw `person_properties` bytes — collision-negligible and computable
/// without a JSON parse, so an unchanged props payload short-circuits before any evaluation.
///
/// The `u128` is the little-endian interpretation of the digest's first 16 bytes, so its 16-byte
/// encoding is exactly those digest bytes (round-trip byte-stable).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PropsFingerprint(pub u128);

impl PropsFingerprint {
    pub fn of(raw: &str) -> Self {
        let digest = Sha256::digest(raw.as_bytes());
        Self(u128::from_le_bytes(
            digest[..16].try_into().expect("SHA-256 yields 32 bytes"),
        ))
    }

    /// The raw digest-prefix bytes (little-endian of the `u128`).
    fn to_bytes(self) -> [u8; 16] {
        self.0.to_le_bytes()
    }

    fn from_bytes(bytes: [u8; 16]) -> Self {
        Self(u128::from_le_bytes(bytes))
    }
}

/// 128 bits of SHA-256 over the concatenation of a team's `person_conditions_ordered` (its sorted
/// person condition hashes). Two catalog snapshots with the same person conditions produce the same
/// fingerprint; adding, removing, or changing a person condition changes it. Empty conditions hash
/// the empty input, a stable constant.
///
/// This replaces the per-worker catalog `Generation` as the person-record invalidation key: a
/// content fingerprint, so a no-op catalog refresh (same conditions, new generation) does not
/// invalidate stored records.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CatalogFingerprint(pub u128);

impl CatalogFingerprint {
    /// Fingerprint the already-sorted person condition hashes. The input must be sorted (as
    /// `person_conditions_ordered` is) so a permutation of the same conditions yields one value.
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

    fn to_bytes(self) -> [u8; 16] {
        self.0.to_le_bytes()
    }

    fn from_bytes(bytes: [u8; 16]) -> Self {
        Self(u128::from_le_bytes(bytes))
    }
}

/// A sorted, deduplicated set of condition hashes that currently evaluate TRUE for a person. The
/// sortedness is upheld by the constructors, so a stored record's bytes are canonical and
/// [`Self::contains`] is a binary search.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MatchedSet(Vec<[u8; 16]>);

impl MatchedSet {
    pub fn empty() -> Self {
        Self(Vec::new())
    }

    /// Reconstruct from bytes already known to be sorted and distinct (the codec verifies this
    /// before calling), skipping the re-sort.
    fn from_sorted_distinct(hashes: Vec<[u8; 16]>) -> Self {
        Self(hashes)
    }

    pub fn contains(&self, hash: &[u8; 16]) -> bool {
        self.0.binary_search(hash).is_ok()
    }

    pub fn len(&self) -> usize {
        self.0.len()
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub fn iter(&self) -> impl Iterator<Item = &[u8; 16]> {
        self.0.iter()
    }

    /// The person transitions from this set (`S`, the stored/prior TRUE set) to `next` (`T`, the
    /// freshly evaluated TRUE set), given the current `catalog` (`person_conditions_ordered`,
    /// sorted). This is the ONLY producer of person membership transitions:
    ///
    /// - `Entered` = `T \ S`: a hash that is TRUE now and was not before.
    /// - `Left` = `(S ∩ catalog) \ T`: a hash that was TRUE, is still in the catalog, and is no
    ///   longer TRUE. Restricting to `S ∩ catalog` means a hash whose condition was removed from the
    ///   catalog does NOT emit `Left` — it is retained silently, mirroring the orphan rows the
    ///   per-leaf path left behind. That retention is what prevents a duplicate `Entered` if the
    ///   condition is later re-added: the hash stays in `S`, so re-adding it is not a new entry.
    ///
    /// Hashes in `S \ catalog` are neither entered nor left — they are the retained orphans.
    pub fn diff<'a>(
        &'a self,
        next: &'a MatchedSet,
        catalog: &'a [[u8; 16]],
    ) -> impl Iterator<Item = ([u8; 16], TransitionKind)> + 'a {
        debug_assert_sorted(catalog);
        let entered = next
            .0
            .iter()
            .filter(move |hash| !self.contains(hash))
            .map(|hash| (*hash, TransitionKind::Entered));
        let left = self
            .0
            .iter()
            .filter(move |hash| catalog.binary_search(hash).is_ok() && !next.contains(hash))
            .map(|hash| (*hash, TransitionKind::Left));
        entered.chain(left)
    }
}

/// `MatchedSet::from_iter(...)` (and `.collect()`) sorts and deduplicates so the sortedness invariant
/// holds regardless of input order.
impl FromIterator<[u8; 16]> for MatchedSet {
    fn from_iter<I: IntoIterator<Item = [u8; 16]>>(hashes: I) -> Self {
        let mut hashes: Vec<[u8; 16]> = hashes.into_iter().collect();
        hashes.sort_unstable();
        hashes.dedup();
        Self(hashes)
    }
}

/// The replay-dedup carrier a merge moves from P_old to P_new: only the offsets, never the matched
/// set, fingerprints, or stamp ("drop P_old's bit; re-eval lazily"). Serde-serialized onto the merge
/// transfer in Slice B2; the field shape (`applied_offsets`, `redirect_dedup`) matches
/// [`crate::stage1::state::StatefulRecord`]'s JSON conventions.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct PersonDedup {
    pub applied_offsets: AppliedOffsets,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub redirect_dedup: BTreeMap<Uuid, AppliedOffsets>,
}

/// The durable per-person value. See the module docs for the field roles.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PersonRecord {
    /// Most recent event time (epoch ms) seen for this person — the ONLY field the TTL filter reads,
    /// at a fixed byte offset. Advanced on every non-replay event (fresh or stale).
    pub last_seen_ms: i64,
    /// The record-level argMax key: adopts a fresh event's `(ms, offset)`; unchanged by a stale one.
    pub stamp: Stamp,
    /// SHA-256 of the raw props behind the current matched set.
    pub props_fingerprint: PropsFingerprint,
    /// SHA-256 of the catalog the current matched set was evaluated against.
    pub catalog_fingerprint: CatalogFingerprint,
    /// Condition hashes currently TRUE (sorted, distinct).
    pub matched: MatchedSet,
    /// Per-source-partition replay-dedup high-water marks for direct events.
    pub applied_offsets: AppliedOffsets,
    /// Per-ancestor replay-dedup for post-merge straggler events, keyed by the ancestor person.
    pub redirect_dedup: BTreeMap<Uuid, AppliedOffsets>,
}

impl PersonRecord {
    /// The evaluation baseline for a person with no stored record (or a corrupt one): nothing
    /// matched, a stamp every real event beats, fingerprints that are never consulted (the decision
    /// table routes Absent/Corrupt straight to a full evaluation, which overwrites them), and no
    /// dedup history.
    pub fn absent() -> Self {
        Self {
            last_seen_ms: i64::MIN,
            stamp: Stamp::MIN,
            props_fingerprint: PropsFingerprint(0),
            catalog_fingerprint: CatalogFingerprint(0),
            matched: MatchedSet::empty(),
            applied_offsets: AppliedOffsets::default(),
            redirect_dedup: BTreeMap::new(),
        }
    }

    /// Origin-aware replay check, sharing the row-level implementation so the two cannot drift.
    pub fn is_replay_for(&self, origin: Option<&Uuid>, sp: i32, so: i64) -> bool {
        dedup_is_replay(&self.applied_offsets, &self.redirect_dedup, origin, sp, so)
    }

    /// Origin-aware offset advance, sharing the row-level implementation.
    pub fn record_for(&mut self, origin: Option<&Uuid>, sp: i32, so: i64) {
        dedup_record(
            &mut self.applied_offsets,
            &mut self.redirect_dedup,
            origin,
            sp,
            so,
        );
    }

    /// Extract this record's replay-dedup for a merge transfer. Carries only the offsets — never the
    /// matched set, fingerprints, or stamp — so P_new re-evaluates the person lazily on its next
    /// event.
    pub fn dedup_carrier(&self) -> PersonDedup {
        PersonDedup {
            applied_offsets: self.applied_offsets.clone(),
            redirect_dedup: self.redirect_dedup.clone(),
        }
    }

    /// Fold a merged-away ancestor's replay-dedup into this record, mirroring
    /// [`crate::merge::rules`]'s per-leaf `compose_ancestor_dedup`: `old_person` becomes an ancestor
    /// under its own uuid (its direct offsets merged there), and each of its own ancestors carries
    /// forward under its original origin. Ancestors are keyed, never unioned into the main map, so a
    /// straggler routed by tombstone to a specific ancestor deduplicates against exactly that
    /// ancestor's high-water marks.
    pub fn absorb_ancestor(&mut self, old_person: Uuid, dedup: &PersonDedup) {
        self.redirect_dedup
            .entry(old_person)
            .or_default()
            .merge_max(&dedup.applied_offsets);
        for (ancestor, offsets) in &dedup.redirect_dedup {
            self.redirect_dedup
                .entry(*ancestor)
                .or_default()
                .merge_max(offsets);
        }
    }

    pub fn encode(&self) -> Vec<u8> {
        encode(self)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PersonRecordCodecError> {
        decode(bytes)
    }
}

/// Whether a person's evaluated membership can have changed since the stored record — the axis the
/// decision table's row 4 splits on. A total function of the two fingerprint comparisons, with a
/// stable metric label.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Freshness {
    /// Both fingerprints match: the stored matched set is still correct, no evaluation needed.
    Fresh,
    /// Only the props changed.
    StaleProps,
    /// Only the catalog changed.
    StaleCatalog,
    /// Both changed.
    StaleBoth,
}

impl Freshness {
    /// The total truth table over `(props_match, catalog_match)`.
    pub fn of(props_match: bool, catalog_match: bool) -> Self {
        match (props_match, catalog_match) {
            (true, true) => Self::Fresh,
            (false, true) => Self::StaleProps,
            (true, false) => Self::StaleCatalog,
            (false, false) => Self::StaleBoth,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Fresh => "fresh",
            Self::StaleProps => "stale_props",
            Self::StaleCatalog => "stale_catalog",
            Self::StaleBoth => "stale_both",
        }
    }
}

/// One stored `cf_person_records` slot as read by the event's single batched pre-event read. Mirrors
/// the per-leaf `PriorState` (`Absent | Present | Corrupt`) but without the decode metric — Slice B2
/// counts at the call site so this stays a pure classifier. `Corrupt` never panics.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PriorRecord {
    /// No row: the person has no stored record.
    Absent,
    /// The decoded prior record.
    Present(PersonRecord),
    /// A row exists but does not decode; the caller re-evaluates from an absent-equivalent baseline
    /// rather than skipping (a skip on a corrupt row would silently freeze membership).
    Corrupt,
}

impl PriorRecord {
    pub fn decode(bytes: Option<&[u8]>) -> Self {
        match bytes {
            None => Self::Absent,
            Some(bytes) => match PersonRecord::decode(bytes) {
                Ok(record) => Self::Present(record),
                Err(_) => Self::Corrupt,
            },
        }
    }
}

/// The dedup routing coordinates for one event: the origin ancestor (from a tombstone redirect, else
/// `None`) plus the source partition/offset.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DedupCoords {
    pub origin: Option<Uuid>,
    pub sp: i32,
    pub so: i64,
}

impl DedupCoords {
    pub fn new(origin: Option<Uuid>, sp: i32, so: i64) -> Self {
        Self { origin, sp, so }
    }
}

/// The classification of one active event against the prior record — the freshness decision table's
/// rows 1, 3, 4a, 4b (row 0, "person side inactive", is decided by the caller before touching the
/// record and never reaches here).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Decision {
    /// Row 1: this `(origin, sp, so)` was already applied. Skip the person side entirely — no write.
    Replay,
    /// Row 3: argMax-stale (`event <= stamp`). Advance dedup + `last_seen`, keep the matched set,
    /// stamp, and fingerprints. One write, no transitions, no evaluation.
    Stale,
    /// Row 4a: fresh and both fingerprints match. Adopt the event stamp, advance dedup + `last_seen`.
    /// One write, no transitions, no evaluation.
    SkipEval,
    /// Row 4b: fresh with a fingerprint mismatch (or an absent/corrupt prior). Needs a props parse
    /// and a HogVM evaluation of every person condition; the caller then calls [`apply_eval`].
    Eval { freshness: Freshness },
}

/// Classify one active event against the prior record. Pure: no store, HogVM, or clock.
///
/// Check order (the decision table, top to bottom):
/// 1. `Replay` — an already-applied offset skips everything (no write).
/// 2. dedup advance happens *after* the replay check but is applied by the `apply_*` constructors,
///    not here — a stale event still records its offset, so this fn only classifies.
/// 3. `Stale` — an equal-or-older stamp.
/// 4. fingerprints — matching ⇒ `SkipEval`, mismatched ⇒ `Eval`.
///
/// A corrupt or absent prior classifies as `Eval` against an absent-equivalent baseline
/// (`matched = ∅`, `stamp = MIN`), never a skip: freezing membership on a corrupt row would be a
/// silent correctness hole.
pub fn decide(
    prior: &PriorRecord,
    event: Stamp,
    dedup: DedupCoords,
    props_fp: PropsFingerprint,
    catalog_fp: CatalogFingerprint,
) -> Decision {
    match prior {
        PriorRecord::Present(record) => {
            if record.is_replay_for(dedup.origin.as_ref(), dedup.sp, dedup.so) {
                return Decision::Replay;
            }
            // An equal-or-older stamp is stale — the same `<=` rule the per-leaf argMax used.
            if event <= record.stamp {
                return Decision::Stale;
            }
            let props_match = props_fp == record.props_fingerprint;
            let catalog_match = catalog_fp == record.catalog_fingerprint;
            if props_match && catalog_match {
                Decision::SkipEval
            } else {
                Decision::Eval {
                    freshness: Freshness::of(props_match, catalog_match),
                }
            }
        }
        // Absent or corrupt: nothing to replay against, and a full re-eval from the baseline.
        // `StaleBoth` is the label for a from-nothing evaluation (neither fingerprint matched a
        // stored value), keeping the metric honest about the amount of work done.
        PriorRecord::Absent | PriorRecord::Corrupt => Decision::Eval {
            freshness: Freshness::StaleBoth,
        },
    }
}

/// Row 3: the next record for an argMax-stale event. Keeps the matched set, stamp, and both
/// fingerprints; advances the dedup offset and `last_seen_ms`. Always a write — the `last_seen`
/// advance is load-bearing for TTL, and recording the offset closes the replay window even though
/// the event lost argMax.
pub fn apply_stale(prior: &PersonRecord, event: Stamp, dedup: DedupCoords) -> PersonRecord {
    let mut next = prior.clone();
    next.record_for(dedup.origin.as_ref(), dedup.sp, dedup.so);
    next.last_seen_ms = next.last_seen_ms.max(event.ms);
    next
}

/// Row 4a: the next record when both fingerprints match. Adopts the event stamp (so a later
/// out-of-order event between the old and new stamps cannot wrongly win argMax), advances the dedup
/// offset and `last_seen_ms`, and keeps the matched set and fingerprints. No transitions.
pub fn apply_skip_eval(prior: &PersonRecord, event: Stamp, dedup: DedupCoords) -> PersonRecord {
    let mut next = prior.clone();
    next.stamp = event;
    next.record_for(dedup.origin.as_ref(), dedup.sp, dedup.so);
    next.last_seen_ms = next.last_seen_ms.max(event.ms);
    next
}

/// Row 4b: the next record and the person transitions after a HogVM evaluation produced `true_set`
/// (`T`) against `catalog` (`person_conditions_ordered`, sorted).
///
/// The prior matched set `S` is read from `prior` (`prior.matched`) so the transition source and the
/// stored record cannot drift. The stored matched set becomes `T ∪ (S \ catalog)`: the freshly-TRUE
/// hashes plus the retained orphans (hashes that were TRUE but whose condition is no longer in the
/// catalog). Keeping the orphans in the stored set is what makes a catalog re-add not re-`Enter` —
/// the hash never left `S`.
///
/// Transitions come ONLY from [`MatchedSet::diff`] between `S` and `T`. The record adopts the event
/// stamp, both fingerprints, and the advanced dedup + `last_seen`.
pub fn apply_eval(
    true_set: MatchedSet,
    catalog: &[[u8; 16]],
    prior: &PersonRecord,
    event: Stamp,
    dedup: DedupCoords,
    props_fp: PropsFingerprint,
    catalog_fp: CatalogFingerprint,
) -> (PersonRecord, Vec<([u8; 16], TransitionKind)>) {
    debug_assert_sorted(catalog);
    let transitions: Vec<_> = prior.matched.diff(&true_set, catalog).collect();

    // The stored set keeps orphans (in S but not in the catalog) so a later catalog re-add does not
    // re-Enter. `T` already holds the currently-TRUE hashes; add the orphans and re-canonicalize.
    let orphans = prior
        .matched
        .iter()
        .copied()
        .filter(|hash| catalog.binary_search(hash).is_err());
    let stored: MatchedSet = true_set.iter().copied().chain(orphans).collect();

    let mut next = prior.clone();
    next.stamp = event;
    next.props_fingerprint = props_fp;
    next.catalog_fingerprint = catalog_fp;
    next.matched = stored;
    next.record_for(dedup.origin.as_ref(), dedup.sp, dedup.so);
    next.last_seen_ms = next.last_seen_ms.max(event.ms);
    (next, transitions)
}

// --- Binary codec v1 ---

/// The on-disk format version. A decode of any other value is a typed error, so an incompatible
/// value layout can never be misread as this one. Visible to the TTL compaction filter
/// ([`crate::store::ttl_filter`]) so its version guard shares this codec's constant.
pub(crate) const FORMAT_VERSION: u8 = 1;

/// Reserved flag byte; nonzero is a typed error so a future flag can be added without silently
/// misinterpreting an old reader.
const FLAGS: u8 = 0;

/// Byte offset of `last_seen_ms`. The TTL compaction filter ([`crate::store::ttl_filter`]) reads only
/// this field, at this fixed offset, without a full decode, so it must never move. Visible to that
/// filter so the offset has a single source of truth.
pub(crate) const LAST_SEEN_MS_OFFSET: usize = 2;

/// A failure decoding a [`PersonRecord`]. Total: every malformed input maps to one of these, never a
/// panic.
#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum PersonRecordCodecError {
    #[error("person record buffer too short: needed {needed} more bytes at {section}")]
    ShortBuffer {
        section: &'static str,
        needed: usize,
    },
    #[error("person record format version {found} is not {expected}")]
    BadVersion { found: u8, expected: u8 },
    #[error("person record flags {found:#04x} are not zero (reserved)")]
    NonZeroFlags { found: u8 },
    #[error("person record {section} is not sorted-distinct")]
    NotSorted { section: &'static str },
    #[error("person record has {trailing} trailing bytes")]
    TrailingBytes { trailing: usize },
}

/// Serialize a record into the canonical v1 layout. Infallible: `BTreeMap` iteration is sorted and
/// [`MatchedSet`] is sorted by construction, so equal logical records encode byte-identically.
///
/// Layout (all integers big-endian, all length-prefixed sections `u32` count then fixed entries):
/// ```text
/// off 0   u8   format_version = 1
///     1   u8   flags = 0
///     2   i64  last_seen_ms
///    10   i64  stamp.ms
///    18   i64  stamp.offset
///    26   16B  props_fingerprint (raw digest-prefix bytes)
///    42   16B  catalog_fingerprint
///    58   u32 N, N × 16B                    matched (sorted, distinct)
///    ..   u32 M, M × (i32 partition, i64 offset)          applied_offsets (sorted by partition)
///    ..   u32 K, K × (uuid 16B, u32 C, C × (i32, i64))    redirect_dedup (sorted by uuid)
/// ```
fn encode(record: &PersonRecord) -> Vec<u8> {
    let mut out = Vec::with_capacity(58 + 4 + record.matched.len() * 16);
    out.push(FORMAT_VERSION);
    out.push(FLAGS);
    // `last_seen_ms` must land at the fixed offset the TTL filter reads without a full decode.
    debug_assert_eq!(out.len(), LAST_SEEN_MS_OFFSET);
    out.extend_from_slice(&record.last_seen_ms.to_be_bytes());
    out.extend_from_slice(&record.stamp.ms.to_be_bytes());
    out.extend_from_slice(&record.stamp.offset.to_be_bytes());
    out.extend_from_slice(&record.props_fingerprint.to_bytes());
    out.extend_from_slice(&record.catalog_fingerprint.to_bytes());

    write_u32(&mut out, record.matched.len());
    for hash in record.matched.iter() {
        out.extend_from_slice(hash);
    }

    encode_applied_offsets(&mut out, &record.applied_offsets);

    write_u32(&mut out, record.redirect_dedup.len());
    for (ancestor, offsets) in &record.redirect_dedup {
        out.extend_from_slice(ancestor.as_bytes());
        encode_applied_offsets(&mut out, offsets);
    }

    out
}

/// Deserialize a record. Total: any short buffer at any boundary, a bad version, nonzero flags, an
/// unsorted/duplicate section, or trailing bytes yields a typed error. Never panics.
fn decode(bytes: &[u8]) -> Result<PersonRecord, PersonRecordCodecError> {
    let mut cur = Cursor::new(bytes);

    let version = cur.take_u8("version")?;
    if version != FORMAT_VERSION {
        return Err(PersonRecordCodecError::BadVersion {
            found: version,
            expected: FORMAT_VERSION,
        });
    }
    let flags = cur.take_u8("flags")?;
    if flags != FLAGS {
        return Err(PersonRecordCodecError::NonZeroFlags { found: flags });
    }

    let last_seen_ms = cur.take_i64("last_seen_ms")?;
    let stamp = Stamp {
        ms: cur.take_i64("stamp.ms")?,
        offset: cur.take_i64("stamp.offset")?,
    };
    let props_fingerprint = PropsFingerprint::from_bytes(cur.take_16("props_fingerprint")?);
    let catalog_fingerprint = CatalogFingerprint::from_bytes(cur.take_16("catalog_fingerprint")?);

    let matched_count = cur.take_u32("matched.count")? as usize;
    let mut matched = Vec::with_capacity(matched_count.min(1024));
    for _ in 0..matched_count {
        matched.push(cur.take_16("matched.entry")?);
    }
    if !is_strictly_sorted(&matched) {
        return Err(PersonRecordCodecError::NotSorted { section: "matched" });
    }

    let applied_offsets = decode_applied_offsets(&mut cur, "applied_offsets")?;

    let redirect_count = cur.take_u32("redirect_dedup.count")? as usize;
    let mut redirect_dedup: BTreeMap<Uuid, AppliedOffsets> = BTreeMap::new();
    let mut prev_ancestor: Option<Uuid> = None;
    for _ in 0..redirect_count {
        let ancestor = Uuid::from_bytes(cur.take_16("redirect_dedup.uuid")?);
        // Strictly ascending by uuid ⇒ canonical, and distinct keys (a `BTreeMap` would otherwise
        // silently collapse a duplicate, hiding a corrupt buffer).
        if prev_ancestor.is_some_and(|prev| ancestor <= prev) {
            return Err(PersonRecordCodecError::NotSorted {
                section: "redirect_dedup",
            });
        }
        prev_ancestor = Some(ancestor);
        let offsets = decode_applied_offsets(&mut cur, "redirect_dedup.offsets")?;
        redirect_dedup.insert(ancestor, offsets);
    }

    if !cur.is_exhausted() {
        return Err(PersonRecordCodecError::TrailingBytes {
            trailing: cur.remaining(),
        });
    }

    Ok(PersonRecord {
        last_seen_ms,
        stamp,
        props_fingerprint,
        catalog_fingerprint,
        matched: MatchedSet::from_sorted_distinct(matched),
        applied_offsets,
        redirect_dedup,
    })
}

/// Encode an [`AppliedOffsets`] as `u32` count then `(i32 partition, i64 offset)` entries, in the
/// map's already-sorted partition order.
fn encode_applied_offsets(out: &mut Vec<u8>, offsets: &AppliedOffsets) {
    let entries = offsets.entries();
    write_u32(out, entries.len());
    for (partition, offset) in entries {
        out.extend_from_slice(&partition.to_be_bytes());
        out.extend_from_slice(&offset.to_be_bytes());
    }
}

/// Decode an [`AppliedOffsets`], verifying the partitions are strictly ascending (canonical).
fn decode_applied_offsets(
    cur: &mut Cursor<'_>,
    section: &'static str,
) -> Result<AppliedOffsets, PersonRecordCodecError> {
    let count = cur.take_u32(section)? as usize;
    let mut entries: Vec<(i32, i64)> = Vec::with_capacity(count.min(1024));
    let mut prev: Option<i32> = None;
    for _ in 0..count {
        let partition = cur.take_i32(section)?;
        let offset = cur.take_i64(section)?;
        if prev.is_some_and(|p| partition <= p) {
            return Err(PersonRecordCodecError::NotSorted { section });
        }
        prev = Some(partition);
        entries.push((partition, offset));
    }
    Ok(AppliedOffsets::from_sorted_entries(entries))
}

fn write_u32(out: &mut Vec<u8>, value: usize) {
    // A person's matched-set / offset counts are far below u32::MAX; the cast is safe in practice
    // and any overflow would surface as a too-large count the decoder rejects on a short buffer.
    debug_assert!(value <= u32::MAX as usize, "section count exceeds u32");
    out.extend_from_slice(&(value as u32).to_be_bytes());
}

fn is_strictly_sorted(hashes: &[[u8; 16]]) -> bool {
    hashes.windows(2).all(|w| w[0] < w[1])
}

/// Debug-time guard for the `catalog` slices [`MatchedSet::diff`] and [`apply_eval`] binary-search
/// over: an unsorted catalog would silently suppress `Left` transitions.
fn debug_assert_sorted(catalog: &[[u8; 16]]) {
    debug_assert!(
        catalog.windows(2).all(|w| w[0] <= w[1]),
        "catalog slice must be sorted for binary search",
    );
}

/// A forward-only reader over the record buffer that turns every out-of-bounds read into a typed
/// [`PersonRecordCodecError::ShortBuffer`] rather than a panic.
struct Cursor<'a> {
    bytes: &'a [u8],
    pos: usize,
}

impl<'a> Cursor<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, pos: 0 }
    }

    fn take(
        &mut self,
        n: usize,
        section: &'static str,
    ) -> Result<&'a [u8], PersonRecordCodecError> {
        let end = self.pos.checked_add(n);
        match end {
            Some(end) if end <= self.bytes.len() => {
                let slice = &self.bytes[self.pos..end];
                self.pos = end;
                Ok(slice)
            }
            _ => Err(PersonRecordCodecError::ShortBuffer {
                section,
                needed: n.saturating_sub(self.bytes.len().saturating_sub(self.pos)),
            }),
        }
    }

    fn take_u8(&mut self, section: &'static str) -> Result<u8, PersonRecordCodecError> {
        Ok(self.take(1, section)?[0])
    }

    fn take_u32(&mut self, section: &'static str) -> Result<u32, PersonRecordCodecError> {
        Ok(u32::from_be_bytes(array(self.take(4, section)?)))
    }

    fn take_i32(&mut self, section: &'static str) -> Result<i32, PersonRecordCodecError> {
        Ok(i32::from_be_bytes(array(self.take(4, section)?)))
    }

    fn take_i64(&mut self, section: &'static str) -> Result<i64, PersonRecordCodecError> {
        Ok(i64::from_be_bytes(array(self.take(8, section)?)))
    }

    fn take_16(&mut self, section: &'static str) -> Result<[u8; 16], PersonRecordCodecError> {
        Ok(array(self.take(16, section)?))
    }

    fn remaining(&self) -> usize {
        self.bytes.len() - self.pos
    }

    fn is_exhausted(&self) -> bool {
        self.pos == self.bytes.len()
    }
}

/// Copy a slice of the exact length into a fixed array. The caller only passes slices produced by
/// [`Cursor::take`], which already guarantees the length, so the `try_into` cannot fail.
fn array<const N: usize>(slice: &[u8]) -> [u8; N] {
    slice.try_into().expect("cursor slice is exactly N bytes")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hash(byte: u8) -> [u8; 16] {
        [byte; 16]
    }

    fn uuid(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    fn applied(entries: &[(i32, i64)]) -> AppliedOffsets {
        let mut applied = AppliedOffsets::default();
        for &(partition, offset) in entries {
            applied.record(partition, offset);
        }
        applied
    }

    fn sample_record() -> PersonRecord {
        let mut redirect = BTreeMap::new();
        redirect.insert(uuid(0xA11CE), applied(&[(9, 42)]));
        PersonRecord {
            last_seen_ms: 1_700_000_000_000,
            stamp: Stamp::new(1_700_000_000_123, 99),
            props_fingerprint: PropsFingerprint(0x1122_3344_5566_7788_99AA_BBCC_DDEE_FF00),
            catalog_fingerprint: CatalogFingerprint(0x0FED_CBA9_8765_4321_1234_5678_9ABC_DEF0),
            matched: MatchedSet::from_iter([hash(0x11), hash(0x22)]),
            applied_offsets: applied(&[(3, 100), (7, 5)]),
            redirect_dedup: redirect,
        }
    }

    #[test]
    fn stamp_orders_by_ms_then_offset_and_min_is_the_floor() {
        assert!(Stamp::new(1, 0) < Stamp::new(1, 1));
        assert!(Stamp::new(1, 999) < Stamp::new(2, 0));
        assert!(Stamp::MIN < Stamp::new(i64::MIN + 1, i64::MIN));
        assert!(Stamp::MIN < Stamp::new(i64::MIN, i64::MIN + 1));
        // Equality is not "fresh": an equal stamp is stale under the `<=` rule decide() applies.
        assert_eq!(Stamp::new(5, 5), Stamp::new(5, 5));
    }

    #[test]
    fn props_fingerprint_matches_the_person_memo_derivation_and_round_trips() {
        // The digest-prefix bytes are the little-endian of the u128, so encode is exactly those bytes.
        let fp = PropsFingerprint::of(r#"{"plan":"pro"}"#);
        assert_eq!(PropsFingerprint::from_bytes(fp.to_bytes()), fp);
        assert_eq!(PropsFingerprint::of("x"), PropsFingerprint::of("x"));
        assert_ne!(PropsFingerprint::of("x"), PropsFingerprint::of("y"));

        let expected = {
            let digest = Sha256::digest(b"x");
            u128::from_le_bytes(digest[..16].try_into().unwrap())
        };
        assert_eq!(PropsFingerprint::of("x").0, expected);
    }

    #[test]
    fn catalog_fingerprint_is_order_stable_and_sensitive() {
        let a = CatalogFingerprint::of_sorted(&[hash(1), hash(2), hash(3)]);
        let b = CatalogFingerprint::of_sorted(&[hash(1), hash(2), hash(3)]);
        assert_eq!(a, b, "same sorted conditions ⇒ same fingerprint");

        let removed = CatalogFingerprint::of_sorted(&[hash(1), hash(2)]);
        assert_ne!(a, removed, "removing a condition changes the fingerprint");

        let added = CatalogFingerprint::of_sorted(&[hash(1), hash(2), hash(3), hash(4)]);
        assert_ne!(a, added, "adding a condition changes the fingerprint");

        // Empty input is a stable constant (the SHA-256 of nothing), distinct from any non-empty set.
        let empty_a = CatalogFingerprint::of_sorted(&[]);
        let empty_b = CatalogFingerprint::of_sorted(&[]);
        assert_eq!(empty_a, empty_b);
        assert_ne!(empty_a, a);
    }

    #[test]
    fn matched_set_sorts_dedups_and_binary_searches() {
        let set = MatchedSet::from_iter([hash(3), hash(1), hash(3), hash(2), hash(1)]);
        assert_eq!(set.len(), 3, "duplicates collapse");
        assert!(set.contains(&hash(1)) && set.contains(&hash(2)) && set.contains(&hash(3)));
        assert!(!set.contains(&hash(4)));
        // Sorted ascending.
        let collected: Vec<_> = set.iter().copied().collect();
        assert_eq!(collected, vec![hash(1), hash(2), hash(3)]);
    }

    #[test]
    fn matched_set_diff_enters_leaves_and_reports_both() {
        let catalog = [hash(1), hash(2), hash(3)];
        let s = MatchedSet::from_iter([hash(1), hash(2)]);
        let t = MatchedSet::from_iter([hash(2), hash(3)]);
        let mut transitions: Vec<_> = s.diff(&t, &catalog).collect();
        transitions.sort_by_key(|(h, _)| *h);
        assert_eq!(
            transitions,
            vec![
                (hash(1), TransitionKind::Left),
                (hash(3), TransitionKind::Entered),
            ],
        );
    }

    #[test]
    fn matched_set_diff_none_when_unchanged() {
        let catalog = [hash(1), hash(2)];
        let s = MatchedSet::from_iter([hash(1), hash(2)]);
        let t = MatchedSet::from_iter([hash(1), hash(2)]);
        assert_eq!(s.diff(&t, &catalog).count(), 0);
    }

    #[test]
    fn matched_set_diff_retains_orphans_across_catalog_remove_readd_and_genuine_leave() {
        // S has a hash whose condition was removed from the catalog.
        let s = MatchedSet::from_iter([hash(0xAA)]);

        // Catalog lacks 0xAA and T lacks it ⇒ NO Left (retained orphan, not a departure).
        let catalog_removed: [[u8; 16]; 0] = [];
        let t_absent = MatchedSet::empty();
        assert_eq!(
            s.diff(&t_absent, &catalog_removed).count(),
            0,
            "an orphaned hash (condition removed) must not emit Left",
        );

        // Catalog regains 0xAA and T regains it ⇒ no duplicate Entered, because the stored set kept
        // the hash the whole time (this is the S-side view: 0xAA is still in S).
        let catalog_readded = [hash(0xAA)];
        let t_present = MatchedSet::from_iter([hash(0xAA)]);
        assert_eq!(
            s.diff(&t_present, &catalog_readded).count(),
            0,
            "re-adding a retained hash must not re-Enter",
        );

        // Catalog regains 0xAA but T does NOT ⇒ Left fires now (the hash genuinely departed).
        let left: Vec<_> = s.diff(&t_absent, &catalog_readded).collect();
        assert_eq!(left, vec![(hash(0xAA), TransitionKind::Left)]);
    }

    // --- decision core ---

    fn present(record: PersonRecord) -> PriorRecord {
        PriorRecord::Present(record)
    }

    fn coords() -> DedupCoords {
        DedupCoords::new(None, 5, 100)
    }

    #[test]
    fn decide_replay_skips_everything() {
        let mut record = sample_record();
        record.applied_offsets = applied(&[(5, 100)]);
        let decision = decide(
            &present(record.clone()),
            Stamp::new(record.stamp.ms + 1_000, 0),
            DedupCoords::new(None, 5, 100),
            record.props_fingerprint,
            record.catalog_fingerprint,
        );
        assert_eq!(decision, Decision::Replay, "offset 100 <= applied 100");
    }

    #[test]
    fn decide_stale_on_equal_or_older_stamp() {
        let record = sample_record();
        // Equal stamp: stale (the `<=` rule).
        assert_eq!(
            decide(
                &present(record.clone()),
                record.stamp,
                DedupCoords::new(None, 5, 1_000),
                record.props_fingerprint,
                record.catalog_fingerprint,
            ),
            Decision::Stale,
        );
        // Strictly older ms: stale.
        assert_eq!(
            decide(
                &present(record.clone()),
                Stamp::new(record.stamp.ms - 1, i64::MAX),
                DedupCoords::new(None, 5, 1_000),
                record.props_fingerprint,
                record.catalog_fingerprint,
            ),
            Decision::Stale,
        );
    }

    #[test]
    fn decide_skip_eval_when_fresh_and_both_fingerprints_match() {
        let record = sample_record();
        let decision = decide(
            &present(record.clone()),
            Stamp::new(record.stamp.ms + 1, 0),
            DedupCoords::new(None, 5, 1_000),
            record.props_fingerprint,
            record.catalog_fingerprint,
        );
        assert_eq!(decision, Decision::SkipEval);
    }

    #[test]
    fn decide_eval_labels_the_mismatch_axis() {
        let record = sample_record();
        let fresh = Stamp::new(record.stamp.ms + 1, 0);
        let other_props = PropsFingerprint(record.props_fingerprint.0 ^ 1);
        let other_catalog = CatalogFingerprint(record.catalog_fingerprint.0 ^ 1);

        assert_eq!(
            decide(
                &present(record.clone()),
                fresh,
                DedupCoords::new(None, 5, 1_000),
                other_props,
                record.catalog_fingerprint,
            ),
            Decision::Eval {
                freshness: Freshness::StaleProps
            },
        );
        assert_eq!(
            decide(
                &present(record.clone()),
                fresh,
                DedupCoords::new(None, 5, 1_000),
                record.props_fingerprint,
                other_catalog,
            ),
            Decision::Eval {
                freshness: Freshness::StaleCatalog
            },
        );
        assert_eq!(
            decide(
                &present(record.clone()),
                fresh,
                DedupCoords::new(None, 5, 1_000),
                other_props,
                other_catalog,
            ),
            Decision::Eval {
                freshness: Freshness::StaleBoth
            },
        );
    }

    #[test]
    fn decide_absent_and_corrupt_always_evaluate_never_skip() {
        let props = PropsFingerprint::of("p");
        let catalog = CatalogFingerprint::of_sorted(&[hash(1)]);
        for prior in [PriorRecord::Absent, PriorRecord::Corrupt] {
            assert_eq!(
                decide(&prior, Stamp::new(10, 0), coords(), props, catalog),
                Decision::Eval {
                    freshness: Freshness::StaleBoth
                },
                "an absent/corrupt prior must evaluate, never skip",
            );
        }
    }

    #[test]
    fn decide_check_order_replay_precedes_staleness() {
        // A replay of an old offset that is ALSO argMax-stale must classify Replay, not Stale — the
        // replay check is first, so a duplicate delivery writes nothing at all.
        let mut record = sample_record();
        record.applied_offsets = applied(&[(5, 100)]);
        let decision = decide(
            &present(record.clone()),
            Stamp::new(record.stamp.ms - 5, 0), // also stale
            DedupCoords::new(None, 5, 100),     // and a replay
            record.props_fingerprint,
            record.catalog_fingerprint,
        );
        assert_eq!(decision, Decision::Replay);
    }

    #[test]
    fn apply_stale_advances_dedup_and_last_seen_but_keeps_everything_else() {
        let mut prior = sample_record();
        prior.last_seen_ms = 1_000;
        prior.applied_offsets = applied(&[(5, 10)]);
        let event = Stamp::new(500, 7); // older than the stamp, newer last_seen
        let next = apply_stale(&prior, Stamp::new(2_000, 7), DedupCoords::new(None, 5, 20));
        let _ = event;
        assert_eq!(next.stamp, prior.stamp, "stamp unchanged by a stale event");
        assert_eq!(next.matched, prior.matched, "matched set unchanged");
        assert_eq!(
            next.props_fingerprint, prior.props_fingerprint,
            "fingerprints unchanged",
        );
        assert_eq!(
            next.last_seen_ms, 2_000,
            "last_seen advances to the event ms"
        );
        assert!(
            next.applied_offsets.is_replay(5, 20),
            "the stale event still records its offset (row 2 precedes 3)",
        );
    }

    #[test]
    fn apply_stale_never_regresses_last_seen() {
        let mut prior = sample_record();
        prior.last_seen_ms = 5_000;
        let next = apply_stale(&prior, Stamp::new(1_000, 0), coords());
        assert_eq!(
            next.last_seen_ms, 5_000,
            "an older event never lowers last_seen"
        );
    }

    #[test]
    fn apply_skip_eval_adopts_the_stamp_and_advances_dedup_and_last_seen() {
        let mut prior = sample_record();
        prior.last_seen_ms = 1_000;
        let event = Stamp::new(9_000, 3);
        let next = apply_skip_eval(&prior, event, DedupCoords::new(None, 5, 20));
        assert_eq!(
            next.stamp, event,
            "the fresh stamp is adopted (load-bearing for argMax)"
        );
        assert_eq!(
            next.matched, prior.matched,
            "no eval ⇒ matched set unchanged"
        );
        assert_eq!(next.last_seen_ms, 9_000);
        assert!(next.applied_offsets.is_replay(5, 20));
    }

    #[test]
    fn apply_eval_diffs_transitions_retains_orphans_and_adopts_stamp_and_fps() {
        let catalog = [hash(1), hash(2)]; // hash(0xAA) is an orphan (in prior, not in catalog)
        let mut prior = sample_record();
        prior.matched = MatchedSet::from_iter([hash(1), hash(0xAA)]);
        prior.last_seen_ms = 1_000;
        let event = Stamp::new(9_000, 3);
        let new_props = PropsFingerprint(0xDEAD);
        let new_catalog = CatalogFingerprint(0xBEEF);

        let true_set = MatchedSet::from_iter([hash(2)]); // 1 leaves, 2 enters
        let (next, transitions) = apply_eval(
            true_set,
            &catalog,
            &prior,
            event,
            DedupCoords::new(None, 5, 20),
            new_props,
            new_catalog,
        );

        let mut sorted = transitions.clone();
        sorted.sort_by_key(|(h, _)| *h);
        assert_eq!(
            sorted,
            vec![
                (hash(1), TransitionKind::Left),
                (hash(2), TransitionKind::Entered),
            ],
            "0xAA is an orphan: no Left for it",
        );
        // Stored set is T ∪ (S \ catalog) = {2} ∪ {0xAA}.
        assert!(next.matched.contains(&hash(2)));
        assert!(
            next.matched.contains(&hash(0xAA)),
            "the orphan is retained in the stored set so a catalog re-add does not re-Enter",
        );
        assert!(!next.matched.contains(&hash(1)), "the left hash is dropped");
        assert_eq!(next.stamp, event);
        assert_eq!(next.props_fingerprint, new_props);
        assert_eq!(next.catalog_fingerprint, new_catalog);
        assert_eq!(next.last_seen_ms, 9_000);
        assert!(next.applied_offsets.is_replay(5, 20));
    }

    #[test]
    fn apply_eval_identical_true_set_yields_no_transitions_but_still_adopts_stamp_and_fps() {
        let catalog = [hash(1), hash(2)];
        let mut prior = sample_record();
        prior.matched = MatchedSet::from_iter([hash(1), hash(2)]);
        let event = Stamp::new(9_000, 3);
        let new_props = PropsFingerprint(0xF00D);
        let new_catalog = CatalogFingerprint(0xC0DE);
        let (next, transitions) = apply_eval(
            MatchedSet::from_iter([hash(1), hash(2)]),
            &catalog,
            &prior,
            event,
            coords(),
            new_props,
            new_catalog,
        );
        assert!(transitions.is_empty(), "T == S ⇒ zero transitions");
        assert_eq!(next.stamp, event, "but the stamp is still adopted");
        assert_eq!(next.props_fingerprint, new_props);
        assert_eq!(next.catalog_fingerprint, new_catalog);
    }

    // --- dedup carrier / absorb ---

    #[test]
    fn dedup_carrier_extracts_only_offsets() {
        let record = sample_record();
        let carrier = record.dedup_carrier();
        assert_eq!(carrier.applied_offsets, record.applied_offsets);
        assert_eq!(carrier.redirect_dedup, record.redirect_dedup);
    }

    #[test]
    fn absorb_ancestor_keys_old_person_and_carries_grandparents() {
        let grandparent = uuid(0x6172);
        let p_old = uuid(0xA11CE);
        let mut carrier = PersonDedup {
            applied_offsets: applied(&[(5, 100)]),
            redirect_dedup: BTreeMap::from([(grandparent, applied(&[(9, 42)]))]),
        };
        // A pre-existing ancestor on P_new's side must survive.
        carrier.redirect_dedup.entry(grandparent).or_default();

        let mut record = sample_record();
        record.redirect_dedup.clear();
        record.absorb_ancestor(p_old, &carrier);

        assert!(
            record.redirect_dedup[&p_old].is_replay(5, 100),
            "P_old becomes an ancestor under its own uuid",
        );
        assert!(
            record.redirect_dedup[&grandparent].is_replay(9, 42),
            "the grandparent carries forward under its own origin, keyed not unioned",
        );
        assert!(
            !record.applied_offsets.is_replay(5, 100),
            "the ancestor's offsets never fold into the main map",
        );
    }

    #[test]
    fn is_replay_and_record_for_share_the_row_level_routing() {
        let mut record = sample_record();
        record.applied_offsets = AppliedOffsets::default();
        record.redirect_dedup.clear();
        let ancestor = uuid(0xA11CE);

        record.record_for(None, 5, 100);
        assert!(record.is_replay_for(None, 5, 100));
        assert!(
            record.redirect_dedup.is_empty(),
            "a direct event touches only the main map"
        );

        record.record_for(Some(&ancestor), 5, 200);
        assert!(record.is_replay_for(Some(&ancestor), 5, 200));
        assert!(
            !record.is_replay_for(None, 5, 150),
            "recording into the ancestor map must not advance the main map",
        );
    }

    // --- freshness labels ---

    #[test]
    fn freshness_truth_table_and_labels() {
        assert_eq!(Freshness::of(true, true), Freshness::Fresh);
        assert_eq!(Freshness::of(false, true), Freshness::StaleProps);
        assert_eq!(Freshness::of(true, false), Freshness::StaleCatalog);
        assert_eq!(Freshness::of(false, false), Freshness::StaleBoth);
        assert_eq!(Freshness::Fresh.as_str(), "fresh");
        assert_eq!(Freshness::StaleProps.as_str(), "stale_props");
        assert_eq!(Freshness::StaleCatalog.as_str(), "stale_catalog");
        assert_eq!(Freshness::StaleBoth.as_str(), "stale_both");
    }

    // --- codec ---

    #[test]
    fn record_round_trips_through_the_codec() {
        let record = sample_record();
        assert_eq!(PersonRecord::decode(&record.encode()).unwrap(), record);
    }

    #[test]
    fn empty_record_round_trips() {
        let record = PersonRecord {
            last_seen_ms: 0,
            stamp: Stamp::MIN,
            props_fingerprint: PropsFingerprint(0),
            catalog_fingerprint: CatalogFingerprint(0),
            matched: MatchedSet::empty(),
            applied_offsets: AppliedOffsets::default(),
            redirect_dedup: BTreeMap::new(),
        };
        assert_eq!(PersonRecord::decode(&record.encode()).unwrap(), record);
    }

    #[test]
    fn encoding_is_canonical_across_insertion_orders() {
        // Build the "same" record two ways: different matched-hash insertion order, different
        // ancestor insertion order. The canonical codec must produce identical bytes.
        let build = |matched_order: [u8; 3], ancestors: &[(u128, i32, i64)]| {
            let mut redirect = BTreeMap::new();
            for &(u, p, o) in ancestors {
                redirect.insert(uuid(u), applied(&[(p, o)]));
            }
            PersonRecord {
                last_seen_ms: 42,
                stamp: Stamp::new(7, 3),
                props_fingerprint: PropsFingerprint(1),
                catalog_fingerprint: CatalogFingerprint(2),
                matched: MatchedSet::from_iter(matched_order.map(hash)),
                applied_offsets: applied(&[(2, 9), (0, 1)]),
                redirect_dedup: redirect,
            }
        };
        let a = build([3, 1, 2], &[(20, 1, 1), (10, 2, 2)]);
        let b = build([2, 3, 1], &[(10, 2, 2), (20, 1, 1)]);
        assert_eq!(a, b, "logically equal");
        assert_eq!(a.encode(), b.encode(), "and byte-identical");
    }

    #[test]
    fn last_seen_ms_lives_at_the_fixed_ttl_offset() {
        // The TTL compaction filter (Slice C) reads only `last_seen_ms`, at this fixed byte offset,
        // without a full decode. Pin it: byte 0 is the version, byte 1 the flags, then the i64 at 2.
        let mut record = sample_record();
        record.last_seen_ms = 0x0102_0304_0506_0708;
        let bytes = record.encode();
        assert_eq!(&bytes[0..2], &[FORMAT_VERSION, FLAGS]);
        assert_eq!(
            i64::from_be_bytes(
                bytes[LAST_SEEN_MS_OFFSET..LAST_SEEN_MS_OFFSET + 8]
                    .try_into()
                    .unwrap()
            ),
            0x0102_0304_0506_0708,
            "the TTL filter's fixed offset must decode last_seen_ms",
        );
    }

    #[test]
    fn golden_bytes_pin_the_wire_format() {
        // A small record: last_seen=1, stamp=(2,3), props_fp=0x04 (LE u128 ⇒ byte 0 = 0x04),
        // catalog_fp=0x05, one matched hash (all 0xAA), two applied offsets, one ancestor with one
        // offset. Hand-written so any accidental reordering of the layout is caught.
        let mut redirect = BTreeMap::new();
        redirect.insert(uuid(0), applied(&[(0x0000_0007, 0x0000_0000_0000_0008)]));
        let record = PersonRecord {
            last_seen_ms: 1,
            stamp: Stamp::new(2, 3),
            props_fingerprint: PropsFingerprint(4),
            catalog_fingerprint: CatalogFingerprint(5),
            matched: MatchedSet::from_iter([[0xAA; 16]]),
            applied_offsets: applied(&[
                (0x0000_0001, 0x0000_0000_0000_0064),
                (0x0000_0002, 0x03E8),
            ]),
            redirect_dedup: redirect,
        };

        let mut expected = Vec::new();
        expected.push(1u8); // format_version
        expected.push(0u8); // flags
        expected.extend_from_slice(&1i64.to_be_bytes()); // last_seen_ms
        expected.extend_from_slice(&2i64.to_be_bytes()); // stamp.ms
        expected.extend_from_slice(&3i64.to_be_bytes()); // stamp.offset
        expected.extend_from_slice(&4u128.to_le_bytes()); // props_fingerprint (LE ⇒ digest bytes)
        expected.extend_from_slice(&5u128.to_le_bytes()); // catalog_fingerprint
        expected.extend_from_slice(&1u32.to_be_bytes()); // matched count
        expected.extend_from_slice(&[0xAA; 16]); // matched[0]
        expected.extend_from_slice(&2u32.to_be_bytes()); // applied count
        expected.extend_from_slice(&1i32.to_be_bytes()); // applied[0].partition
        expected.extend_from_slice(&100i64.to_be_bytes()); // applied[0].offset
        expected.extend_from_slice(&2i32.to_be_bytes()); // applied[1].partition
        expected.extend_from_slice(&1000i64.to_be_bytes()); // applied[1].offset
        expected.extend_from_slice(&1u32.to_be_bytes()); // redirect count
        expected.extend_from_slice(uuid(0).as_bytes()); // ancestor uuid
        expected.extend_from_slice(&1u32.to_be_bytes()); // ancestor offset count
        expected.extend_from_slice(&7i32.to_be_bytes()); // ancestor[0].partition
        expected.extend_from_slice(&8i64.to_be_bytes()); // ancestor[0].offset

        assert_eq!(record.encode(), expected);
        // And it survives a decode.
        assert_eq!(PersonRecord::decode(&expected).unwrap(), record);
    }

    #[test]
    fn decode_truncation_at_every_boundary_errs_never_panics() {
        let bytes = sample_record().encode();
        for k in 0..bytes.len() {
            let result = PersonRecord::decode(&bytes[..k]);
            assert!(
                result.is_err(),
                "a buffer truncated to {k} of {} bytes must fail to decode",
                bytes.len(),
            );
        }
        // The full buffer decodes.
        assert!(PersonRecord::decode(&bytes).is_ok());
    }

    #[test]
    fn decode_rejects_a_bad_version() {
        let mut bytes = sample_record().encode();
        bytes[0] = 2;
        assert_eq!(
            PersonRecord::decode(&bytes),
            Err(PersonRecordCodecError::BadVersion {
                found: 2,
                expected: 1,
            }),
        );
    }

    #[test]
    fn decode_rejects_nonzero_flags() {
        let mut bytes = sample_record().encode();
        bytes[1] = 0x80;
        assert_eq!(
            PersonRecord::decode(&bytes),
            Err(PersonRecordCodecError::NonZeroFlags { found: 0x80 }),
        );
    }

    #[test]
    fn decode_rejects_trailing_bytes() {
        let mut bytes = sample_record().encode();
        bytes.push(0);
        assert_eq!(
            PersonRecord::decode(&bytes),
            Err(PersonRecordCodecError::TrailingBytes { trailing: 1 }),
        );
    }

    #[test]
    fn decode_rejects_an_unsorted_matched_section() {
        // Hand-build a record with two matched hashes in descending order.
        let mut bytes = Vec::new();
        bytes.push(1u8);
        bytes.push(0u8);
        bytes.extend_from_slice(&0i64.to_be_bytes()); // last_seen
        bytes.extend_from_slice(&0i64.to_be_bytes()); // stamp.ms
        bytes.extend_from_slice(&0i64.to_be_bytes()); // stamp.offset
        bytes.extend_from_slice(&[0u8; 16]); // props_fp
        bytes.extend_from_slice(&[0u8; 16]); // catalog_fp
        bytes.extend_from_slice(&2u32.to_be_bytes()); // matched count = 2
        bytes.extend_from_slice(&[0xBB; 16]); // matched[0] (larger)
        bytes.extend_from_slice(&[0xAA; 16]); // matched[1] (smaller ⇒ unsorted)
        bytes.extend_from_slice(&0u32.to_be_bytes()); // applied count
        bytes.extend_from_slice(&0u32.to_be_bytes()); // redirect count
        assert_eq!(
            PersonRecord::decode(&bytes),
            Err(PersonRecordCodecError::NotSorted { section: "matched" }),
        );
    }

    #[test]
    fn decode_rejects_unsorted_applied_offsets() {
        let mut bytes = Vec::new();
        bytes.push(1u8);
        bytes.push(0u8);
        bytes.extend_from_slice(&0i64.to_be_bytes());
        bytes.extend_from_slice(&0i64.to_be_bytes());
        bytes.extend_from_slice(&0i64.to_be_bytes());
        bytes.extend_from_slice(&[0u8; 16]);
        bytes.extend_from_slice(&[0u8; 16]);
        bytes.extend_from_slice(&0u32.to_be_bytes()); // matched count = 0
        bytes.extend_from_slice(&2u32.to_be_bytes()); // applied count = 2
        bytes.extend_from_slice(&5i32.to_be_bytes()); // partition 5
        bytes.extend_from_slice(&0i64.to_be_bytes());
        bytes.extend_from_slice(&3i32.to_be_bytes()); // partition 3 (< 5 ⇒ unsorted)
        bytes.extend_from_slice(&0i64.to_be_bytes());
        bytes.extend_from_slice(&0u32.to_be_bytes()); // redirect count
        assert_eq!(
            PersonRecord::decode(&bytes),
            Err(PersonRecordCodecError::NotSorted {
                section: "applied_offsets"
            }),
        );
    }

    #[test]
    fn decode_rejects_unsorted_redirect_ancestors() {
        let build_offsets = |out: &mut Vec<u8>| {
            out.extend_from_slice(&1u32.to_be_bytes());
            out.extend_from_slice(&0i32.to_be_bytes());
            out.extend_from_slice(&0i64.to_be_bytes());
        };
        let mut bytes = Vec::new();
        bytes.push(1u8);
        bytes.push(0u8);
        bytes.extend_from_slice(&0i64.to_be_bytes());
        bytes.extend_from_slice(&0i64.to_be_bytes());
        bytes.extend_from_slice(&0i64.to_be_bytes());
        bytes.extend_from_slice(&[0u8; 16]);
        bytes.extend_from_slice(&[0u8; 16]);
        bytes.extend_from_slice(&0u32.to_be_bytes()); // matched
        bytes.extend_from_slice(&0u32.to_be_bytes()); // applied
        bytes.extend_from_slice(&2u32.to_be_bytes()); // redirect count = 2
        bytes.extend_from_slice(uuid(5).as_bytes()); // ancestor 5
        build_offsets(&mut bytes);
        bytes.extend_from_slice(uuid(3).as_bytes()); // ancestor 3 (< 5 ⇒ unsorted)
        build_offsets(&mut bytes);
        assert_eq!(
            PersonRecord::decode(&bytes),
            Err(PersonRecordCodecError::NotSorted {
                section: "redirect_dedup"
            }),
        );
    }
}
