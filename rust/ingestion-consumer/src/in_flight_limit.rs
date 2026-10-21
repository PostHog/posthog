use std::num::NonZeroU64;

use common_kafka_consumer::Charge;

/// The events and bytes a pod may hold polled and not yet completed.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct InFlightLimits {
    events: Option<u64>,
    bytes: Option<u64>,
}

impl InFlightLimits {
    pub fn unset() -> Self {
        Self::default()
    }

    pub fn new(events: Option<NonZeroU64>, bytes: Option<NonZeroU64>) -> Self {
        Self {
            events: events.map(NonZeroU64::get),
            bytes: bytes.map(NonZeroU64::get),
        }
    }

    pub fn is_set(&self) -> bool {
        self.events.is_some() || self.bytes.is_some()
    }

    pub(crate) fn reached(&self, held: Charge) -> bool {
        self.events.is_some_and(|limit| held.events >= limit)
            || self.bytes.is_some_and(|limit| held.bytes >= limit)
    }
}
