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
/// end. `used` is Σ charged − Σ refunded, exactly; only `under_cap` reads the
/// axes.
#[derive(Debug)]
pub struct Budget {
    used: Charge,
    cap: Charge,
}

impl Budget {
    pub fn new(cap: Charge) -> Budget {
        Budget {
            used: Charge::ZERO,
            cap,
        }
    }

    pub fn charge(&mut self, c: Charge) {
        self.used += c;
    }

    pub fn refund(&mut self, c: Charge) {
        self.used -= c;
    }

    pub fn under_cap(&self) -> bool {
        self.used.events < self.cap.events && self.used.bytes < self.cap.bytes
    }

    pub fn used(&self) -> Charge {
        self.used
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn either_axis_closes_the_gate() {
        let mut budget = Budget::new(Charge {
            events: 10,
            bytes: 100,
        });
        assert!(budget.under_cap());

        budget.charge(Charge {
            events: 10,
            bytes: 1,
        });
        assert!(!budget.under_cap());

        budget.refund(Charge {
            events: 1,
            bytes: 0,
        });
        assert!(budget.under_cap());

        budget.charge(Charge {
            events: 0,
            bytes: 99,
        });
        assert!(!budget.under_cap());
    }
}
