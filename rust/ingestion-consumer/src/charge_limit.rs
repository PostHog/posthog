use std::num::NonZeroU64;

use common_kafka_consumer::Charge;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ChargeLimit {
    events: Option<u64>,
    bytes: Option<u64>,
}

impl ChargeLimit {
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

    pub fn sets_both_axes(&self) -> bool {
        self.events.is_some() && self.bytes.is_some()
    }

    pub(crate) fn reached(&self, charge: Charge) -> bool {
        self.events.is_some_and(|limit| charge.events >= limit)
            || self.bytes.is_some_and(|limit| charge.bytes >= limit)
    }

    pub(crate) fn scaled(&self, fraction: f64) -> Self {
        let scale = |limit: u64| ((limit as f64 * fraction) as u64).clamp(1, limit);
        Self {
            events: self.events.map(scale),
            bytes: self.bytes.map(scale),
        }
    }
}
