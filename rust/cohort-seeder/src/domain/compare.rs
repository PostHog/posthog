//! The shadow compare's tile diff: a sorted-merge over two scans' tile vectors, pure and
//! deletable with the compare layer. Depends on `aggregate`'s output shape only.

use std::cmp::Ordering;
use std::fmt;

use cohort_core::seed::SeedTile;
use uuid::Uuid;

use super::ids::ConditionHash;

/// Cap on retained exemplars, counted per class: enough to characterize one, small enough to log.
///
/// Per class rather than shared, because a shared cap fills in merge order and can silence a whole
/// class. Every class needs its own examples to be triaged at all, and the one that appears once is
/// as likely to be the informative one as the one that appears ten thousand times.
pub const MAX_EXEMPLARS_PER_CLASS: usize = 8;

/// Which arm produced a divergent pair, and so which of the three totals counts it.
///
/// The classes describe one pair each. None of them is benign on its own: [`TileDiff::is_match`]
/// rejects all three, so any of them raises `result="diff"`. Nor does a cause map onto a class —
/// a row the wide arm skipped for a malformed blob lands in `Extra` when the pair has no other
/// matching row in the chunk, in `CountDiffers` when it has one, and nowhere at all when the row
/// matches no condition. Read the class as a shape and the skip counters as the cause.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DivergenceClass {
    /// The legacy arm produced the pair and the projected arm did not.
    Missing,
    /// The projected arm produced the pair and the legacy arm did not.
    Extra,
    /// Both arms produced the pair with different counts.
    CountDiffers,
}

impl DivergenceClass {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Missing => "missing",
            Self::Extra => "extra",
            Self::CountDiffers => "count_differs",
        }
    }
}

/// One `(person, condition)` pair the two arms disagree on. A `0` count means that arm
/// produced no tile for the pair.
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct Divergence {
    pub class: DivergenceClass,
    pub person: Uuid,
    pub hash: ConditionHash,
    pub projected: u32,
    pub legacy: u32,
}

/// Hand-written because this is what an operator reads out of the divergence log, and
/// [`ConditionHash`]'s derived `Debug` renders its sixteen bytes as decimal integers — a form
/// nobody can grep for or paste into the chunk ledger. Its `Display` is the ASCII hash.
impl fmt::Debug for Divergence {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "{} person={} hash={} projected={} legacy={}",
            self.class.as_str(),
            self.person,
            self.hash,
            self.projected,
            self.legacy
        )
    }
}

/// Per-class totals plus at most [`MAX_EXEMPLARS_PER_CLASS`] exemplars of each, in
/// `(person, hash)` order.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct TileDiff {
    /// Pairs the legacy arm produced and the projected arm did not.
    pub missing: u64,
    /// Pairs the projected arm produced and the legacy arm did not.
    pub extra: u64,
    pub count_differs: u64,
    pub exemplars: Vec<Divergence>,
}

impl TileDiff {
    pub fn is_match(&self) -> bool {
        self.missing == 0 && self.extra == 0 && self.count_differs == 0
    }

    fn only_in_projected(&mut self, tile: &SeedTile) {
        self.extra += 1;
        self.keep(divergence(DivergenceClass::Extra, tile, tile.count(), 0));
    }

    fn only_in_legacy(&mut self, tile: &SeedTile) {
        self.missing += 1;
        self.keep(divergence(DivergenceClass::Missing, tile, 0, tile.count()));
    }

    fn counts_differ(&mut self, projected: &SeedTile, legacy: &SeedTile) {
        self.count_differs += 1;
        self.keep(divergence(
            DivergenceClass::CountDiffers,
            projected,
            projected.count(),
            legacy.count(),
        ));
    }

    /// The totals are exact whatever the cap does, so a chunk that diverged thousands of times
    /// still reports how many — the exemplars only have to characterize each class's shape.
    fn keep(&mut self, divergence: Divergence) {
        let kept = self
            .exemplars
            .iter()
            .filter(|other| other.class == divergence.class)
            .count();
        if kept < MAX_EXEMPLARS_PER_CLASS {
            self.exemplars.push(divergence);
        }
    }
}

/// Diff two tile vectors from the same chunk scanned twice. Both inputs are `into_tiles`
/// outputs, sorted by `(person_id, condition_hash)` by construction.
///
/// Every field the two arms build from shared arguments is identical, which leaves the count. The
/// key is the exception: `person_id` comes from the unfenced `person_distinct_id_overrides` join,
/// so a merge landing between the arms re-keys a row and shows up here as a paired `Missing` and
/// `Extra` for one condition under two persons. That pair is override drift, not a projection
/// defect, and it does not reproduce on a re-scan.
pub fn diff_tiles(projected: &[SeedTile], legacy: &[SeedTile]) -> TileDiff {
    let mut diff = TileDiff::default();
    let (mut left, mut right) = (0, 0);
    loop {
        match (projected.get(left), legacy.get(right)) {
            (None, None) => return diff,
            (Some(tile), None) => {
                diff.only_in_projected(tile);
                left += 1;
            }
            (None, Some(tile)) => {
                diff.only_in_legacy(tile);
                right += 1;
            }
            (Some(projected_tile), Some(legacy_tile)) => {
                match key(projected_tile).cmp(&key(legacy_tile)) {
                    Ordering::Less => {
                        diff.only_in_projected(projected_tile);
                        left += 1;
                    }
                    Ordering::Greater => {
                        diff.only_in_legacy(legacy_tile);
                        right += 1;
                    }
                    Ordering::Equal => {
                        if projected_tile.count() != legacy_tile.count() {
                            diff.counts_differ(projected_tile, legacy_tile);
                        }
                        left += 1;
                        right += 1;
                    }
                }
            }
        }
    }
}

/// The merge key, which is also `into_tiles`' sort key — the whole merge is only correct while the
/// two agree, which `aggregate`'s own tests pin.
fn key(tile: &SeedTile) -> (Uuid, ConditionHash) {
    (tile.person_id(), tile.condition_hash())
}

fn divergence(class: DivergenceClass, tile: &SeedTile, projected: u32, legacy: u32) -> Divergence {
    Divergence {
        class,
        person: tile.person_id(),
        hash: tile.condition_hash(),
        projected,
        legacy,
    }
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroU32;

    use cohort_core::filters::TeamId;

    use super::*;
    use crate::domain::{ClaimEpoch, RunId, SChunkMs};

    const HASH_A: &str = "aaaaaaaaaaaaaaaa";
    const HASH_B: &str = "bbbbbbbbbbbbbbbb";
    const HASH_C: &str = "cccccccccccccccc";

    /// Every field but the key and the count is built from arguments both arms share, so the
    /// builder fixes them: a difference the diff reported in one of them would be a bug in the
    /// test, not a finding.
    fn tile(person: u128, hash: &str, count: u32) -> SeedTile {
        SeedTile::new(
            TeamId(2),
            Uuid::from_u128(person),
            ConditionHash::parse(hash).unwrap(),
            NonZeroU32::new(count).expect("a tile's count is non-zero by construction"),
            20_000,
            SChunkMs(1_700_000_000_000),
            RunId(Uuid::nil()),
            ClaimEpoch(1),
        )
    }

    fn exemplar(
        class: DivergenceClass,
        person: u128,
        hash: &str,
        counts: (u32, u32),
    ) -> Divergence {
        Divergence {
            class,
            person: Uuid::from_u128(person),
            hash: ConditionHash::parse(hash).unwrap(),
            projected: counts.0,
            legacy: counts.1,
        }
    }

    #[test]
    fn arms_that_agree_report_a_match_and_no_exemplars() {
        for (projected, legacy) in [
            (Vec::new(), Vec::new()),
            (
                vec![tile(1, HASH_A, 2), tile(1, HASH_B, 1), tile(2, HASH_A, 7)],
                vec![tile(1, HASH_A, 2), tile(1, HASH_B, 1), tile(2, HASH_A, 7)],
            ),
        ] {
            let diff = diff_tiles(&projected, &legacy);
            assert!(diff.is_match(), "{diff:?}");
            assert_eq!(diff.exemplars, Vec::new());
        }
    }

    /// The tail case is the merge's classic bug: once the projected side is exhausted, the rest of
    /// the legacy side must still be walked rather than dropped.
    #[test]
    fn legacy_only_pairs_at_head_middle_and_tail_are_missing() {
        let projected = [tile(1, HASH_B, 1), tile(2, HASH_A, 1)];
        let legacy = [
            tile(1, HASH_A, 4),
            tile(1, HASH_B, 1),
            tile(1, HASH_C, 5),
            tile(2, HASH_A, 1),
            tile(3, HASH_A, 6),
        ];
        let diff = diff_tiles(&projected, &legacy);
        assert!(!diff.is_match());
        assert_eq!((diff.missing, diff.extra, diff.count_differs), (3, 0, 0));
        assert_eq!(
            diff.exemplars,
            vec![
                exemplar(DivergenceClass::Missing, 1, HASH_A, (0, 4)),
                exemplar(DivergenceClass::Missing, 1, HASH_C, (0, 5)),
                exemplar(DivergenceClass::Missing, 3, HASH_A, (0, 6)),
            ]
        );
    }

    #[test]
    fn projected_only_pairs_are_extra() {
        let projected = [tile(1, HASH_A, 3), tile(1, HASH_B, 1), tile(2, HASH_A, 9)];
        let legacy = [tile(1, HASH_B, 1)];
        let diff = diff_tiles(&projected, &legacy);
        assert!(!diff.is_match());
        assert_eq!((diff.missing, diff.extra, diff.count_differs), (0, 2, 0));
        assert_eq!(
            diff.exemplars,
            vec![
                exemplar(DivergenceClass::Extra, 1, HASH_A, (3, 0)),
                exemplar(DivergenceClass::Extra, 2, HASH_A, (9, 0)),
            ]
        );
    }

    #[test]
    fn a_shared_pair_with_unequal_counts_carries_both_readings() {
        let diff = diff_tiles(&[tile(1, HASH_A, 3)], &[tile(1, HASH_A, 5)]);
        assert!(!diff.is_match());
        assert_eq!((diff.missing, diff.extra, diff.count_differs), (0, 0, 1));
        assert_eq!(
            diff.exemplars,
            vec![exemplar(DivergenceClass::CountDiffers, 1, HASH_A, (3, 5))]
        );
    }

    /// A merge keyed on the person alone would pair person 1's `HASH_C` with its `HASH_B` and call
    /// it a count difference, hiding one lost pair and one gained one behind a single class.
    #[test]
    fn the_merge_advances_on_the_hash_within_one_person() {
        let projected = [tile(1, HASH_A, 1), tile(1, HASH_C, 2), tile(2, HASH_B, 1)];
        let legacy = [tile(1, HASH_A, 1), tile(1, HASH_B, 4), tile(2, HASH_B, 1)];
        let diff = diff_tiles(&projected, &legacy);
        assert_eq!((diff.missing, diff.extra, diff.count_differs), (1, 1, 0));
        assert_eq!(
            diff.exemplars,
            vec![
                exemplar(DivergenceClass::Missing, 1, HASH_B, (0, 4)),
                exemplar(DivergenceClass::Extra, 1, HASH_C, (2, 0)),
            ]
        );
    }

    /// The alarming class arrives last here, behind more benign ones than a shared cap would hold.
    #[test]
    fn the_exemplar_cap_keeps_every_class_and_leaves_the_totals_exact() {
        let over = MAX_EXEMPLARS_PER_CLASS + 5;
        let projected = (1..=over)
            .map(|person| tile(person as u128, HASH_A, 1))
            .collect::<Vec<_>>();
        let legacy = [tile(over as u128 + 1, HASH_A, 4)];
        let diff = diff_tiles(&projected, &legacy);

        assert_eq!((diff.missing, diff.extra), (1, over as u64));
        assert_eq!(
            diff.exemplars
                .iter()
                .filter(|d| d.class == DivergenceClass::Extra)
                .count(),
            MAX_EXEMPLARS_PER_CLASS
        );
        assert_eq!(
            diff.exemplars
                .iter()
                .filter(|d| d.class == DivergenceClass::Missing)
                .collect::<Vec<_>>(),
            vec![&exemplar(
                DivergenceClass::Missing,
                over as u128 + 1,
                HASH_A,
                (0, 4)
            )]
        );
    }

    /// The log line is the feature's only per-pair output, so its rendering is a contract: a
    /// derived `Debug` prints the hash as sixteen decimal integers.
    #[test]
    fn an_exemplar_renders_its_hash_as_the_ascii_operators_search_for() {
        assert_eq!(
            format!(
                "{:?}",
                exemplar(DivergenceClass::Missing, 1, HASH_A, (0, 4))
            ),
            "missing person=00000000-0000-0000-0000-000000000001 \
             hash=aaaaaaaaaaaaaaaa projected=0 legacy=4"
        );
    }
}
