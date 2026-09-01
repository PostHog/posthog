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

/// Per-partition delivered-offset ledger. Completion only marks slots; commit
/// paths explicitly consume the contiguous prefix after observing it.
#[derive(Debug, Default)]
pub struct OffsetLedger {
    /// The offset of `slots[0]`; `None` until the first delivery.
    base: Option<i64>,
    /// Number of completed slots at the front of the window, kept current on
    /// every completion so `frontier` stays O(1).
    prefix: usize,
    /// A dense sliding window over one contiguous offset range: `charge`
    /// appends at the back, `take_frontier` pops the front, and `complete`
    /// indexes by offset minus `base`. Every operation is amortized constant
    /// time per offset.
    slots: VecDeque<Slot>,
}

impl OffsetLedger {
    pub fn new() -> Self {
        Self::default()
    }

    /// Record offsets in delivery order and return their total charge. An
    /// offset gap (transaction control records) gets pre-completed zero-charge
    /// filler slots, so the window stays dense and the frontier walks over the
    /// gap.
    pub fn charge(&mut self, offsets: impl IntoIterator<Item = (Offset, Charge)>) -> Charge {
        let mut total = Charge::ZERO;
        for (offset, charge) in offsets {
            let base = *self.base.get_or_insert(offset.0);
            let end = base + self.slots.len() as i64;
            assert!(
                offset.0 >= end,
                "offset {offset} was not delivered in order"
            );
            for _ in end..offset.0 {
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
    pub fn complete(&mut self, offsets: &[Offset]) {
        let base = self.base.expect("completion before any delivery");
        for offset in offsets {
            let index = usize::try_from(offset.0 - base).expect("completion below the window base");
            let slot = self
                .slots
                .get_mut(index)
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

    /// Highest contiguous completed offset. This can be a gap offset when
    /// filler ends the completed prefix; a commit one past it is still correct
    /// because a gap holds no messages.
    pub fn frontier(&self) -> Option<Offset> {
        let base = self.base?;
        (self.prefix > 0).then(|| Offset(base + self.prefix as i64 - 1))
    }

    /// Consume the contiguous completed prefix previously observable through
    /// `frontier`. This is intentionally separate from `complete` for shadow
    /// comparisons against the current commit path.
    pub fn take_frontier(&mut self) -> Option<TakenFrontier> {
        let offset = self.frontier()?;
        let charge = self
            .slots
            .drain(..self.prefix)
            .map(|slot| slot.charge)
            .sum();
        *self.base.as_mut().expect("frontier implies a base") += self.prefix as i64;
        self.prefix = 0;
        Some(TakenFrontier { offset, charge })
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
