use std::collections::VecDeque;

use crate::charge::Charge;
use crate::types::Offset;

#[derive(Debug)]
struct Slot {
    complete: bool,
    charge: Charge,
}

/// A consumed contiguous prefix and the charge it covers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TakenFrontier {
    pub offset: Offset,
    pub charge: Charge,
}

/// Per-partition offset accounting: record offsets as they are delivered,
/// complete them in any order, and read the highest offset that is safe to
/// commit. Observing the frontier never changes it; a commit point consumes
/// it with `take_frontier`.
///
/// A ledger lives for one partition assignment: create it on assign, drop it
/// on revoke. Kafka replays a partition from its committed offset after a
/// rebalance, so a ledger kept across assignments sees the replay as
/// duplicate delivery and panics. Completions from a previous assignment's
/// in-flight work must be discarded before they reach the new ledger; it
/// never charged those offsets and panics on them too (see the panic
/// contracts on `charge` and `complete`).
#[derive(Debug, Default)]
pub struct OffsetLedger {
    /// The offset of `slots[0]`; `None` until the first delivery.
    base_offset: Option<Offset>,
    /// Number of completed slots at the front of the window, kept current on
    /// every completion so `frontier` stays O(1).
    prefix: usize,
    /// A dense sliding window over one contiguous offset range: `charge`
    /// appends at the back, `take_frontier` pops the front, and `complete`
    /// indexes by offset minus `base_offset`. Every operation is amortized constant
    /// time per offset.
    slots: VecDeque<Slot>,
}

impl OffsetLedger {
    pub fn new() -> Self {
        Self::default()
    }

    /// Record offsets in delivery order and return their total charge. An
    /// offset gap (transaction control records) never blocks the frontier and
    /// carries no charge.
    ///
    /// # Panics
    ///
    /// When an offset is not above every offset already recorded. Duplicate
    /// or out-of-order delivery is a caller bug, and recording it would
    /// corrupt the commit accounting.
    pub fn charge(&mut self, offsets: impl IntoIterator<Item = (Offset, Charge)>) -> Charge {
        let mut total = Charge::ZERO;
        for (offset, charge) in offsets {
            let base_offset = *self.base_offset.get_or_insert(offset);
            let next_offset = base_offset + self.slots.len();
            assert!(
                offset >= next_offset,
                "offset {offset} delivered below the window's next offset {next_offset}"
            );
            // A gap becomes pre-completed zero-charge filler so the index
            // math stays aligned with offsets.
            for _ in 0..offset - next_offset {
                self.slots.push_back(Slot {
                    complete: true,
                    charge: Charge::ZERO,
                });
            }
            self.slots.push_back(Slot {
                complete: false,
                charge,
            });
            total += charge;
        }
        total
    }

    /// Mark delivered offsets complete in any order.
    ///
    /// # Panics
    ///
    /// When an offset was never charged, was completed before, or was already
    /// consumed by `take_frontier`. Each case means the completion does not
    /// belong to this ledger's window, and marking it would corrupt the
    /// commit accounting.
    pub fn complete(&mut self, offsets: &[Offset]) {
        let base_offset = self.base_offset.expect("completion before any delivery");
        for &offset in offsets {
            let slot_index =
                usize::try_from(offset - base_offset).expect("completion below the window base");
            let slot = self
                .slots
                .get_mut(slot_index)
                .expect("completion for an uncharged offset");
            assert!(!slot.complete, "offset {offset} completed twice");
            slot.complete = true;
        }
        while self
            .slots
            .get(self.prefix)
            .is_some_and(|slot| slot.complete)
        {
            self.prefix += 1;
        }
    }

    /// Highest offset with nothing incomplete at or below it, or `None`
    /// before the first completion. Committing one past it is always safe,
    /// even when a trailing gap makes this a gap offset.
    pub fn frontier(&self) -> Option<Offset> {
        let base_offset = self.base_offset?;
        (self.prefix > 0).then(|| base_offset + (self.prefix - 1))
    }

    /// Take the frontier and the charge of everything at or below it,
    /// forgetting that span. Kept separate from `complete` so that reading
    /// the frontier has no side effects and only commit points consume it.
    pub fn take_frontier(&mut self) -> Option<TakenFrontier> {
        let frontier_offset = self.frontier()?;
        let charge = self
            .slots
            .drain(..self.prefix)
            .map(|slot| slot.charge)
            .sum();
        self.base_offset = Some(frontier_offset + 1);
        self.prefix = 0;
        Some(TakenFrontier {
            offset: frontier_offset,
            charge,
        })
    }

    pub fn len(&self) -> usize {
        self.slots.len()
    }

    pub fn is_empty(&self) -> bool {
        self.slots.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn charge(offset: i64) -> (Offset, Charge) {
        (
            Offset(offset),
            Charge {
                events: 1,
                bytes: 10,
            },
        )
    }

    #[test]
    fn out_of_order_completion_does_not_move_the_frontier() {
        let mut ledger = OffsetLedger::new();
        ledger.charge([charge(0), charge(1), charge(2)]);
        ledger.complete(&[Offset(2)]);
        assert_eq!(ledger.frontier(), None);
        ledger.complete(&[Offset(0), Offset(1)]);
        assert_eq!(ledger.frontier(), Some(Offset(2)));
    }

    #[test]
    fn frontier_is_idempotent_and_take_drains_it() {
        let mut ledger = OffsetLedger::new();
        ledger.charge([charge(0), charge(1)]);
        ledger.complete(&[Offset(0), Offset(1)]);
        assert_eq!(ledger.frontier(), Some(Offset(1)));
        assert_eq!(ledger.frontier(), Some(Offset(1)));
        assert_eq!(ledger.take_frontier().unwrap().charge.events, 2);
        assert_eq!(ledger.len(), 0);
    }

    #[test]
    fn delivery_gaps_do_not_block_delivered_offsets() {
        let mut ledger = OffsetLedger::new();
        ledger.charge([charge(0), charge(3)]);
        ledger.complete(&[Offset(0), Offset(3)]);
        assert_eq!(ledger.frontier(), Some(Offset(3)));
    }

    #[test]
    fn gap_filler_carries_no_charge_and_the_frontier_walks_over_it() {
        let mut ledger = OffsetLedger::new();
        ledger.charge([charge(0), charge(3)]);
        ledger.complete(&[Offset(0)]);
        assert_eq!(ledger.frontier(), Some(Offset(2)));
        ledger.complete(&[Offset(3)]);
        let taken = ledger.take_frontier().unwrap();
        assert_eq!(taken.offset, Offset(3));
        assert_eq!(taken.charge.events, 2);
    }

    #[test]
    fn the_window_slides_across_take_frontier() {
        let mut ledger = OffsetLedger::new();
        ledger.charge([charge(0), charge(1)]);
        ledger.complete(&[Offset(0), Offset(1)]);
        ledger.take_frontier().unwrap();
        ledger.charge([charge(2)]);
        ledger.complete(&[Offset(2)]);
        assert_eq!(ledger.frontier(), Some(Offset(2)));
        assert_eq!(ledger.take_frontier().unwrap().charge.events, 1);
    }
}
