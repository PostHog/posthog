use std::iter::Sum;
use std::ops::{Add, AddAssign, SubAssign};

/// A message's cost against the budget: one value, two axes, because the
/// budget caps both (whichever binds). Component-wise monoid, nothing more.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct Charge {
    pub events: u64,
    pub bytes: u64,
}

impl Charge {
    pub const ZERO: Charge = Charge {
        events: 0,
        bytes: 0,
    };

    pub fn is_zero(&self) -> bool {
        *self == Charge::ZERO
    }
}

impl Add for Charge {
    type Output = Charge;

    fn add(self, rhs: Charge) -> Charge {
        Charge {
            events: self.events + rhs.events,
            bytes: self.bytes + rhs.bytes,
        }
    }
}

impl AddAssign for Charge {
    fn add_assign(&mut self, rhs: Charge) {
        self.events += rhs.events;
        self.bytes += rhs.bytes;
    }
}

impl SubAssign for Charge {
    fn sub_assign(&mut self, rhs: Charge) {
        self.events -= rhs.events;
        self.bytes -= rhs.bytes;
    }
}

impl Sum for Charge {
    fn sum<I: Iterator<Item = Charge>>(iter: I) -> Charge {
        iter.fold(Charge::ZERO, |acc, c| acc + c)
    }
}

/// The `B` accounting: charged at poll, refunded at commit and at a drain's
/// end. `used` is Σ charged − Σ refunded, exactly; only the gate reads the
/// axes.
///
/// The gate has two watermarks. It closes when `used` reaches `cap` on either
/// axis and reopens only when `used` is back at or under `low` on both. The
/// poll gate is rdkafka pause/resume, and a pause purges the fetch queue that
/// a resume then refetches, so a gate that flipped on every refund across a
/// single threshold would refetch on every crossing.
#[derive(Debug)]
pub struct Budget {
    used: Charge,
    cap: Charge,
    low: Charge,
    closed: bool,
}

impl Budget {
    /// Default low watermark: 80% of the cap on each axis.
    pub const DEFAULT_LOW_RATIO: f64 = 0.8;

    pub fn new(cap: Charge) -> Budget {
        Budget::with_low_ratio(cap, Budget::DEFAULT_LOW_RATIO)
    }

    pub fn with_low_ratio(cap: Charge, ratio: f64) -> Budget {
        let ratio = ratio.clamp(0.0, 1.0);
        Budget::with_low(
            cap,
            Charge {
                events: (cap.events as f64 * ratio) as u64,
                bytes: (cap.bytes as f64 * ratio) as u64,
            },
        )
    }

    pub fn with_low(cap: Charge, low: Charge) -> Budget {
        Budget {
            used: Charge::ZERO,
            cap,
            low: Charge {
                events: low.events.min(cap.events),
                bytes: low.bytes.min(cap.bytes),
            },
            closed: false,
        }
    }

    pub fn charge(&mut self, c: Charge) {
        self.used += c;
        if self.used.events >= self.cap.events || self.used.bytes >= self.cap.bytes {
            self.closed = true;
        }
    }

    pub fn refund(&mut self, c: Charge) {
        self.used -= c;
        if self.used.events <= self.low.events && self.used.bytes <= self.low.bytes {
            self.closed = false;
        }
    }

    /// Whether the loop may poll.
    pub fn gate_open(&self) -> bool {
        !self.closed
    }

    pub fn used(&self) -> Charge {
        self.used
    }

    pub fn cap(&self) -> Charge {
        self.cap
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn charge(events: u64, bytes: u64) -> Charge {
        Charge { events, bytes }
    }

    #[test]
    fn either_axis_closes_the_gate() {
        let mut budget = Budget::with_low(charge(10, 100), charge(10, 100));
        assert!(budget.gate_open());

        budget.charge(charge(10, 1));
        assert!(!budget.gate_open());

        budget.refund(charge(1, 0));
        assert!(budget.gate_open());

        budget.charge(charge(0, 99));
        assert!(!budget.gate_open());
    }

    #[test]
    fn a_refund_between_low_and_cap_keeps_the_gate_closed() {
        let mut budget = Budget::with_low(charge(10, 100), charge(8, 80));
        budget.charge(charge(10, 50));
        assert!(!budget.gate_open());

        budget.refund(charge(1, 0));
        assert!(!budget.gate_open(), "9 events is above low (8)");

        budget.refund(charge(1, 0));
        assert!(budget.gate_open(), "8 events is at low on both axes");
    }

    #[test]
    fn reopening_needs_both_axes_at_or_under_low() {
        let mut budget = Budget::with_low(charge(10, 100), charge(8, 80));
        budget.charge(charge(10, 100));
        budget.refund(charge(5, 0));
        assert!(!budget.gate_open(), "bytes still at cap");
        budget.refund(charge(0, 20));
        assert!(budget.gate_open());
    }

    #[test]
    fn low_ratio_derives_the_watermark_per_axis() {
        let budget = Budget::with_low_ratio(charge(100, 1000), 0.5);
        assert_eq!(budget.low, charge(50, 500));
        let clamped = Budget::with_low_ratio(charge(100, 1000), 7.0);
        assert_eq!(clamped.low, charge(100, 1000));
    }
}
