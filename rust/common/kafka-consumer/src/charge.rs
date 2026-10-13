use std::iter::Sum;
use std::ops::{Add, AddAssign, Sub, SubAssign};

/// A message's cost against later consumer admission budgets.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Charge {
    pub events: u64,
    pub bytes: u64,
}

impl Charge {
    pub const ZERO: Charge = Charge {
        events: 0,
        bytes: 0,
    };
}

impl Add for Charge {
    type Output = Charge;

    fn add(self, rhs: Charge) -> Self::Output {
        Charge {
            events: self.events + rhs.events,
            bytes: self.bytes + rhs.bytes,
        }
    }
}

impl AddAssign for Charge {
    fn add_assign(&mut self, rhs: Charge) {
        *self = *self + rhs;
    }
}

impl Sub for Charge {
    type Output = Charge;

    fn sub(self, rhs: Charge) -> Self::Output {
        Charge {
            events: self.events - rhs.events,
            bytes: self.bytes - rhs.bytes,
        }
    }
}

impl SubAssign for Charge {
    fn sub_assign(&mut self, rhs: Charge) {
        *self = *self - rhs;
    }
}

impl Sum for Charge {
    fn sum<I: Iterator<Item = Charge>>(iter: I) -> Self {
        iter.fold(Charge::ZERO, Add::add)
    }
}
