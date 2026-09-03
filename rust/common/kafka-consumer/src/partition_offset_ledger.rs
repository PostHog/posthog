use std::collections::VecDeque;
use std::fmt;

use crate::charge::Charge;
use crate::types::Offset;

#[derive(Debug)]
struct Slot {
    complete: bool,
    charge: Charge,
}

/// Work that does not belong to the ledger's window. The ledger checks each
/// offset as it applies it, so on an error the window holds the offsets
/// applied before the offending one; the owner discards the ledger rather
/// than reasoning about that state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LedgerError {
    /// A charge delivered an offset that is not above every offset already
    /// recorded.
    OffsetNotAboveWindow { offset: Offset, next: Offset },
    /// A completion arrived before any delivery was charged.
    CompletionBeforeDelivery { offset: Offset },
    /// A completion for an offset `take_frontier` already consumed.
    CompletionBelowWindow { offset: Offset, base: Offset },
    /// A completion for an offset the window never charged.
    CompletionUncharged { offset: Offset },
    /// A completion for an offset completed before.
    CompletedTwice { offset: Offset },
}

impl LedgerError {
    /// A stable label for metrics.
    pub fn kind(&self) -> &'static str {
        match self {
            LedgerError::OffsetNotAboveWindow { .. } => "offset_not_above_window",
            LedgerError::CompletionBeforeDelivery { .. } => "completion_before_delivery",
            LedgerError::CompletionBelowWindow { .. } => "completion_below_window",
            LedgerError::CompletionUncharged { .. } => "completion_uncharged",
            LedgerError::CompletedTwice { .. } => "completed_twice",
        }
    }
}

impl fmt::Display for LedgerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            LedgerError::OffsetNotAboveWindow { offset, next } => {
                write!(
                    f,
                    "offset {offset} delivered but not above the window's next offset {next}"
                )
            }
            LedgerError::CompletionBeforeDelivery { offset } => {
                write!(f, "offset {offset} completed before any delivery")
            }
            LedgerError::CompletionBelowWindow { offset, base } => {
                write!(f, "offset {offset} completed below the window base {base}")
            }
            LedgerError::CompletionUncharged { offset } => {
                write!(f, "offset {offset} completed but never charged")
            }
            LedgerError::CompletedTwice { offset } => write!(f, "offset {offset} completed twice"),
        }
    }
}

impl std::error::Error for LedgerError {}

/// A consumed contiguous prefix: its commit-ready frontier and the charge it
/// covers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TakenFrontier {
    pub offset: Offset,
    pub charge: Charge,
}

/// Per-partition offset accounting: record offsets as they are delivered,
/// complete them in any order, and read the frontier in Kafka's
/// committed-offset representation. Observing the frontier never changes it;
/// a commit point consumes it with `take_frontier`.
///
/// Charge every record the poll delivers, including records the caller drops
/// without processing: an omitted offset is indistinguishable from an offset
/// Kafka never delivered, and the frontier commits past it as if it held no
/// message.
///
/// A ledger lives for one partition assignment: create it on assign, drop it
/// on revoke. Kafka redelivers a partition from its committed offset after a
/// rebalance, so a ledger kept across assignments sees the redelivery as
/// duplicate delivery and rejects it. Completions from a previous
/// assignment's in-flight work must be discarded before they reach the new
/// ledger; it never charged those offsets and rejects them too. A rejection
/// is a [`LedgerError`]: the ledger never panics, so an owner holding it
/// under a lock stays usable.
#[derive(Debug)]
pub struct PartitionOffsetLedger {
    /// The partition generation this ledger was founded under. The owner
    /// compares it with the stamp on incoming work to drop work from an
    /// earlier assignment.
    generation: u64,
    /// The offset of `slots[0]`; `None` until the first delivery.
    base_offset: Option<Offset>,
    /// Number of completed slots at the front of the window, kept current on
    /// every completion so `frontier` stays O(1).
    completed_prefix_len: usize,
    /// A dense sliding window over one contiguous offset range: `charge`
    /// appends at the back, `take_frontier` pops the front, and `complete`
    /// indexes by offset minus `base_offset`. Every operation is amortized constant
    /// time per offset.
    slots: VecDeque<Slot>,
}

impl PartitionOffsetLedger {
    pub fn new(generation: u64) -> Self {
        Self {
            generation,
            base_offset: None,
            completed_prefix_len: 0,
            slots: VecDeque::new(),
        }
    }

    /// The partition generation this ledger was founded under.
    pub fn generation(&self) -> u64 {
        self.generation
    }

    /// Record offsets in delivery order and return their total charge. An
    /// offset gap (transaction control records) never blocks the frontier and
    /// carries no charge.
    ///
    /// Fails when an offset is not above every offset already recorded.
    /// Duplicate or out-of-order delivery is a caller bug, and recording it
    /// would corrupt the commit accounting.
    pub fn charge(
        &mut self,
        offset_charges: impl IntoIterator<Item = (Offset, Charge)>,
    ) -> Result<Charge, LedgerError> {
        let mut total = Charge::ZERO;
        for (offset, charge) in offset_charges {
            let base_offset = *self.base_offset.get_or_insert(offset);
            let next_offset = base_offset + self.slots.len();
            if offset < next_offset {
                return Err(LedgerError::OffsetNotAboveWindow {
                    offset,
                    next: next_offset,
                });
            }
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
        Ok(total)
    }

    /// Mark delivered offsets complete in any order.
    ///
    /// Fails when an offset was never charged, was completed before, or was
    /// already consumed by `take_frontier`. Each case means the completion
    /// does not belong to this ledger's window, and marking it would corrupt
    /// the commit accounting.
    pub fn complete(
        &mut self,
        offsets: impl IntoIterator<Item = Offset>,
    ) -> Result<(), LedgerError> {
        for offset in offsets {
            let Some(base_offset) = self.base_offset else {
                return Err(LedgerError::CompletionBeforeDelivery { offset });
            };
            let slot_index = usize::try_from(offset - base_offset).map_err(|_| {
                LedgerError::CompletionBelowWindow {
                    offset,
                    base: base_offset,
                }
            })?;
            let slot = self
                .slots
                .get_mut(slot_index)
                .ok_or(LedgerError::CompletionUncharged { offset })?;
            if slot.complete {
                return Err(LedgerError::CompletedTwice { offset });
            }
            slot.complete = true;
        }
        while self
            .slots
            .get(self.completed_prefix_len)
            .is_some_and(|slot| slot.complete)
        {
            self.completed_prefix_len += 1;
        }
        Ok(())
    }

    /// The next offset to read: one past the highest contiguous completed
    /// offset, in Kafka's committed-offset representation, so a commit uses
    /// it verbatim. `None` before the first completion.
    pub fn frontier(&self) -> Option<Offset> {
        let base_offset = self.base_offset?;
        (self.completed_prefix_len > 0).then(|| base_offset + self.completed_prefix_len)
    }

    /// Take the frontier and the charge of everything below it, forgetting
    /// that span. Kept separate from `complete` so that reading the frontier
    /// has no side effects and only commit points consume it.
    pub fn take_frontier(&mut self) -> Option<TakenFrontier> {
        let frontier_offset = self.frontier()?;
        let charge = self
            .slots
            .drain(..self.completed_prefix_len)
            .map(|slot| slot.charge)
            .sum();
        self.base_offset = Some(frontier_offset);
        self.completed_prefix_len = 0;
        Some(TakenFrontier {
            offset: frontier_offset,
            charge,
        })
    }

    /// Offsets the window still holds: charged and not yet drained by
    /// `take_frontier`.
    pub fn depth(&self) -> usize {
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
        let mut ledger = PartitionOffsetLedger::new(1);
        ledger.charge([charge(0), charge(1), charge(2)]).unwrap();
        ledger.complete([Offset(2)]).unwrap();
        assert_eq!(ledger.frontier(), None);
        assert_eq!(ledger.take_frontier(), None);
        ledger.complete([Offset(0), Offset(1)]).unwrap();
        assert_eq!(ledger.frontier(), Some(Offset(3)));
    }

    #[test]
    fn a_partial_take_keeps_the_remainder_completable() {
        let mut ledger = PartitionOffsetLedger::new(1);
        ledger.charge([charge(0), charge(1), charge(2)]).unwrap();
        ledger.complete([Offset(0)]).unwrap();
        let taken = ledger.take_frontier().unwrap();
        assert_eq!(taken.offset, Offset(1));
        assert_eq!(taken.charge.events, 1);
        assert_eq!(ledger.depth(), 2);
        ledger.complete([Offset(1), Offset(2)]).unwrap();
        assert_eq!(ledger.frontier(), Some(Offset(3)));
        assert_eq!(ledger.take_frontier().unwrap().charge.events, 2);
    }

    #[test]
    fn duplicate_delivery_is_rejected() {
        let mut ledger = PartitionOffsetLedger::new(1);
        ledger.charge([charge(0), charge(1)]).unwrap();
        assert_eq!(
            ledger.charge([charge(1)]),
            Err(LedgerError::OffsetNotAboveWindow {
                offset: Offset(1),
                next: Offset(2),
            })
        );
    }

    #[test]
    fn completion_before_any_delivery_is_rejected() {
        let mut ledger = PartitionOffsetLedger::new(1);
        assert_eq!(
            ledger.complete([Offset(0)]),
            Err(LedgerError::CompletionBeforeDelivery { offset: Offset(0) })
        );
    }

    #[test]
    fn double_completion_is_rejected() {
        let mut ledger = PartitionOffsetLedger::new(1);
        ledger.charge([charge(0)]).unwrap();
        ledger.complete([Offset(0)]).unwrap();
        assert_eq!(
            ledger.complete([Offset(0)]),
            Err(LedgerError::CompletedTwice { offset: Offset(0) })
        );
    }

    #[test]
    fn completing_an_undelivered_offset_is_rejected() {
        let mut ledger = PartitionOffsetLedger::new(1);
        ledger.charge([charge(0)]).unwrap();
        assert_eq!(
            ledger.complete([Offset(5)]),
            Err(LedgerError::CompletionUncharged { offset: Offset(5) })
        );
    }

    #[test]
    fn completing_below_the_window_after_a_take_is_rejected() {
        let mut ledger = PartitionOffsetLedger::new(1);
        ledger.charge([charge(0), charge(1)]).unwrap();
        ledger.complete([Offset(0)]).unwrap();
        ledger.take_frontier().unwrap();
        assert_eq!(
            ledger.complete([Offset(0)]),
            Err(LedgerError::CompletionBelowWindow {
                offset: Offset(0),
                base: Offset(1),
            })
        );
    }

    #[test]
    fn frontier_is_idempotent_and_take_drains_it() {
        let mut ledger = PartitionOffsetLedger::new(1);
        ledger.charge([charge(0), charge(1)]).unwrap();
        ledger.complete([Offset(0), Offset(1)]).unwrap();
        assert_eq!(ledger.frontier(), Some(Offset(2)));
        assert_eq!(ledger.frontier(), Some(Offset(2)));
        assert_eq!(ledger.take_frontier().unwrap().charge.events, 2);
        assert_eq!(ledger.depth(), 0);
    }

    #[test]
    fn delivery_gaps_do_not_block_delivered_offsets() {
        let mut ledger = PartitionOffsetLedger::new(1);
        ledger.charge([charge(0), charge(3)]).unwrap();
        ledger.complete([Offset(0), Offset(3)]).unwrap();
        assert_eq!(ledger.frontier(), Some(Offset(4)));
    }

    #[test]
    fn gap_filler_carries_no_charge_and_the_frontier_walks_over_it() {
        let mut ledger = PartitionOffsetLedger::new(1);
        ledger.charge([charge(0), charge(3)]).unwrap();
        ledger.complete([Offset(0)]).unwrap();
        assert_eq!(ledger.frontier(), Some(Offset(3)));
        ledger.complete([Offset(3)]).unwrap();
        let taken = ledger.take_frontier().unwrap();
        assert_eq!(taken.offset, Offset(4));
        assert_eq!(taken.charge.events, 2);
    }

    #[test]
    fn the_window_slides_across_take_frontier() {
        let mut ledger = PartitionOffsetLedger::new(1);
        ledger.charge([charge(0), charge(1)]).unwrap();
        ledger.complete([Offset(0), Offset(1)]).unwrap();
        ledger.take_frontier().unwrap();
        ledger.charge([charge(2)]).unwrap();
        ledger.complete([Offset(2)]).unwrap();
        assert_eq!(ledger.frontier(), Some(Offset(3)));
        assert_eq!(ledger.take_frontier().unwrap().charge.events, 1);
    }
}
