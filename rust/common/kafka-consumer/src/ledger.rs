use std::collections::VecDeque;

use crate::charge::Charge;
use crate::types::Offset;

#[derive(Debug)]
struct Slot {
    done: bool,
    charge: Charge,
}

/// A partition's offset accounting: a dense ring over one contiguous offset
/// range. Polls deliver offsets in order, so appending keeps the ring dense;
/// completion arrives in any order and only the frontier — the highest
/// contiguous completed offset — is ordered.
#[derive(Debug, Default)]
pub struct OffsetLedger {
    /// The offset of `slots[0]`; `None` until the first delivery.
    base: Option<i64>,
    /// Highest contiguous completed offset; `None` until the first advance.
    frontier: Option<i64>,
    slots: VecDeque<Slot>,
}

impl OffsetLedger {
    pub fn new() -> OffsetLedger {
        OffsetLedger::default()
    }

    /// Record one poll's offsets, in offset order. An offset gap (transaction
    /// control records) gets pre-done zero-charge filler so the frontier walks
    /// over it and the index math stays honest. Returns the poll's debit.
    pub fn add_pending(&mut self, msgs: impl IntoIterator<Item = (Offset, Charge)>) -> Charge {
        let mut total = Charge::ZERO;
        for (offset, charge) in msgs {
            let base = *self.base.get_or_insert(offset.0);
            let next = base + self.slots.len() as i64;
            assert!(
                offset.0 >= next,
                "poll delivered offset {} below the ring's end {next}",
                offset.0
            );
            for _ in next..offset.0 {
                self.slots.push_back(Slot {
                    done: true,
                    charge: Charge::ZERO,
                });
            }
            self.slots.push_back(Slot {
                done: false,
                charge,
            });
            total += charge;
        }
        total
    }

    /// Mark a group's offsets done — any subset of the ring, in any order
    /// across requests — then pop the done prefix in the same call. Returns
    /// the new frontier and the charge of exactly the span it walked over, or
    /// `None` when the front is still in flight and nothing advanced.
    pub fn complete(&mut self, offsets: &[Offset]) -> Option<(Offset, Charge)> {
        let base = self.base.expect("completion before any delivery");
        for o in offsets {
            let index = usize::try_from(o.0 - base).expect("completion below the frontier");
            let slot = &mut self.slots[index];
            assert!(!slot.done, "offset {o} completed twice");
            slot.done = true;
        }

        let mut charge = Charge::ZERO;
        while self.slots.front().is_some_and(|s| s.done) {
            charge += self.slots.pop_front().expect("front checked").charge;
            let base = self.base.as_mut().expect("base set above");
            self.frontier = Some(*base);
            *base += 1;
        }
        // Zero-charge filler is only ever popped together with a real slot
        // (it is pre-done, so the frontier never rests just below it), so a
        // zero charge means nothing advanced.
        (!charge.is_zero()).then(|| (Offset(self.frontier.expect("advanced")), charge))
    }

    /// Highest contiguous completed offset; `None` until the first advance.
    pub fn frontier(&self) -> Option<Offset> {
        self.frontier.map(Offset)
    }

    pub fn has_pending(&self) -> bool {
        !self.slots.is_empty()
    }

    /// Everything the frontier never walked over — including done work
    /// stranded above a gap, which was never refunded and replays like the
    /// rest.
    pub fn pending_charge(&self) -> Charge {
        self.slots.iter().map(|s| s.charge).sum()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ev(n: u64) -> Charge {
        Charge {
            events: n,
            bytes: n * 10,
        }
    }

    fn deliver(ledger: &mut OffsetLedger, offsets: impl IntoIterator<Item = i64>) -> Charge {
        ledger.add_pending(offsets.into_iter().map(|o| (Offset(o), ev(1))))
    }

    #[test]
    fn out_of_order_completion_holds_the_frontier_until_the_gap_fills() {
        let mut ledger = OffsetLedger::new();
        deliver(&mut ledger, 0..=6);

        // A later request's offsets settle first: done above the gap, no advance.
        assert_eq!(ledger.complete(&[Offset(4), Offset(5), Offset(6)]), None);
        assert_eq!(ledger.frontier(), None);

        // The earlier work lands: one advance walks over all of it.
        let (frontier, charge) = ledger
            .complete(&[Offset(0), Offset(1), Offset(2), Offset(3)])
            .expect("the gap filled");
        assert_eq!(frontier, Offset(6));
        assert_eq!(charge, ev(7));
        assert!(!ledger.has_pending());
    }

    #[test]
    fn offset_gaps_get_pre_done_zero_charge_filler() {
        let mut ledger = OffsetLedger::new();
        // Transaction control records at offsets 2 and 3 are never delivered.
        let charged = deliver(&mut ledger, [0, 1, 4]);
        assert_eq!(charged, ev(3));

        let (frontier, charge) = ledger.complete(&[Offset(0), Offset(1)]).expect("advance");
        assert_eq!(frontier, Offset(3), "the frontier walks over the filler");
        assert_eq!(charge, ev(2), "filler carries no charge");

        let (frontier, charge) = ledger.complete(&[Offset(4)]).expect("advance");
        assert_eq!(frontier, Offset(4));
        assert_eq!(charge, ev(1));
    }

    #[test]
    fn refund_is_exactly_the_span_the_frontier_walked_over() {
        let mut ledger = OffsetLedger::new();
        deliver(&mut ledger, 0..=3);

        let (_, first) = ledger.complete(&[Offset(0)]).expect("advance");
        assert_eq!(ledger.complete(&[Offset(2)]), None, "no advance, no refund");
        let (_, second) = ledger.complete(&[Offset(1)]).expect("advance");
        let (_, third) = ledger.complete(&[Offset(3)]).expect("advance");
        assert_eq!(first + second + third, ev(4), "every charge refunded once");
    }

    #[test]
    fn pending_charge_includes_done_work_stranded_above_a_gap() {
        let mut ledger = OffsetLedger::new();
        deliver(&mut ledger, 0..=2);

        assert_eq!(ledger.complete(&[Offset(1), Offset(2)]), None);
        // Offsets 1 and 2 are done but the frontier never walked over them:
        // they were never refunded and replay like the rest on a drain.
        assert_eq!(ledger.pending_charge(), ev(3));
    }

    #[test]
    fn later_polls_append_to_the_same_ring() {
        let mut ledger = OffsetLedger::new();
        deliver(&mut ledger, 0..=1);
        deliver(&mut ledger, 2..=3);

        let (frontier, charge) = ledger
            .complete(&[Offset(0), Offset(1), Offset(2), Offset(3)])
            .expect("advance");
        assert_eq!(frontier, Offset(3));
        assert_eq!(charge, ev(4));
    }
}
