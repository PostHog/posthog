//! Attribution for slices the offset ledger rejected. The ledger counts a
//! rejection where it happens; the consumer logs it here, because only the
//! consumer still holds the slice the ledger consumed.

use common_kafka_consumer::{Charge, Offset, Rejection, TopicPartition};
use tracing::warn;

use crate::order_sentinel::OffsetSpan;

#[derive(Debug, Clone, Copy)]
pub(crate) enum RejectedSlice {
    /// Exactly the offsets the charge submitted to the ledger.
    Charged {
        first: Option<i64>,
        last: Option<i64>,
        offsets: usize,
    },
    /// The batch's delivered span for the partition, not the settled slice.
    /// A generation change mid-batch drops the old generation's charges but
    /// leaves the span whole, so the span can cover offsets the settlement
    /// never submitted. The settled offsets are an iterator the happy path
    /// does not collect, so the span is the closest description available.
    /// The error names the offending offset.
    Settled { first: i64, last: i64 },
}

impl RejectedSlice {
    pub(crate) fn charged(charges: &[(Offset, Charge)]) -> Self {
        Self::Charged {
            first: charges.first().map(|(offset, _)| offset.0),
            last: charges.last().map(|(offset, _)| offset.0),
            offsets: charges.len(),
        }
    }

    pub(crate) fn settled(span: &OffsetSpan) -> Self {
        Self::Settled {
            first: span.first,
            last: span.last,
        }
    }
}

/// Log one charge or settlement the ledger rejected. A stale slice is
/// expected around a rebalance and stays quiet; a violation is a bug in the
/// accounting and names the slice. Callers must build `slice` inside their
/// error arm so the happy path pays nothing for it.
pub(crate) fn warn_rejection(
    stage: &'static str,
    topic_partition: &TopicPartition,
    rejection: Rejection,
    slice: RejectedSlice,
) {
    let Rejection::Violation {
        error,
        stamp,
        generation,
        held,
    } = rejection
    else {
        return;
    };
    // A tracing field name is fixed at the call site, so each variant needs
    // its own `warn!`.
    match slice {
        RejectedSlice::Charged {
            first,
            last,
            offsets,
        } => warn!(
            stage,
            topic = %topic_partition.topic,
            partition = topic_partition.partition,
            error = %error,
            kind = error.kind(),
            batch_generation = stamp,
            ledger_generation = generation,
            depth = held.offsets,
            slice_first = ?first,
            slice_last = ?last,
            slice_offsets = offsets,
            "Offset ledger rejected a slice and reset its partition"
        ),
        RejectedSlice::Settled { first, last } => warn!(
            stage,
            topic = %topic_partition.topic,
            partition = topic_partition.partition,
            error = %error,
            kind = error.kind(),
            batch_generation = stamp,
            ledger_generation = generation,
            depth = held.offsets,
            batch_first = first,
            batch_last = last,
            "Offset ledger rejected a slice and reset its partition"
        ),
    }
}
