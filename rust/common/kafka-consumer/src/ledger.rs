use std::collections::VecDeque;

use crate::charge::Charge;
use crate::types::Offset;

#[derive(Debug)]
struct Slot {
    offset: Offset,
    charge: Charge,
    complete: bool,
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
    slots: VecDeque<Slot>,
}

impl OffsetLedger {
    pub fn new() -> Self {
        Self::default()
    }

    /// Record offsets in delivery order and return their total charge.
    pub fn charge(&mut self, offsets: impl IntoIterator<Item = (Offset, Charge)>) -> Charge {
        let mut total = Charge::ZERO;
        for (offset, charge) in offsets {
            if let Some(last) = self.slots.back() {
                assert!(
                    offset > last.offset,
                    "offset {offset} was not delivered in order"
                );
            }
            self.slots.push_back(Slot {
                offset,
                charge,
                complete: false,
            });
            total += charge;
        }
        total
    }

    /// Mark delivered offsets complete in any order.
    pub fn complete(&mut self, offsets: &[Offset]) {
        for offset in offsets {
            let slot = self
                .slots
                .iter_mut()
                .find(|slot| slot.offset == *offset)
                .expect("completion for an uncharged offset");
            assert!(!slot.complete, "offset {offset} completed twice");
            slot.complete = true;
        }
    }

    /// Highest complete delivered offset before the first incomplete slot.
    pub fn frontier(&self) -> Option<Offset> {
        self.slots
            .iter()
            .take_while(|slot| slot.complete)
            .last()
            .map(|slot| slot.offset)
    }

    /// Consume the contiguous completed prefix previously observable through
    /// `frontier`. This is intentionally separate from `complete` for shadow
    /// comparisons against the current commit path.
    pub fn take_frontier(&mut self) -> Option<TakenFrontier> {
        let mut charge = Charge::ZERO;
        let mut offset = None;
        while self.slots.front().is_some_and(|slot| slot.complete) {
            let slot = self.slots.pop_front().expect("front checked");
            charge += slot.charge;
            offset = Some(slot.offset);
        }
        offset.map(|offset| TakenFrontier { offset, charge })
    }

    pub fn len(&self) -> usize {
        self.slots.len()
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
}
