use std::num::NonZeroU64;

use common_kafka_consumer::Charge;

#[derive(Debug, Clone, Copy)]
struct Threshold {
    events: Option<u64>,
    bytes: Option<u64>,
}

impl Threshold {
    fn reached(&self, charge: Charge) -> bool {
        self.events.is_some_and(|limit| charge.events >= limit)
            || self.bytes.is_some_and(|limit| charge.bytes >= limit)
    }

    fn scaled(&self, fraction: f64) -> Self {
        let scale = |limit: u64| ((limit as f64 * fraction) as u64).clamp(1, limit);
        Self {
            events: self.events.map(scale),
            bytes: self.bytes.map(scale),
        }
    }
}

#[derive(Debug, Clone, Copy)]
struct Limits {
    pause_at: Threshold,
    resume_at: Threshold,
}

#[derive(Debug, Clone, Copy)]
pub struct BudgetLimits {
    limits: Option<Limits>,
}

impl BudgetLimits {
    pub fn unset() -> Self {
        Self { limits: None }
    }

    /// With neither axis set the budget is unset.
    pub fn new(
        events: Option<NonZeroU64>,
        bytes: Option<NonZeroU64>,
        low_watermark: f64,
    ) -> Result<Self, String> {
        if !(low_watermark > 0.0 && low_watermark <= 1.0) {
            return Err(format!(
                "the low watermark must be above 0 and at most 1, got {low_watermark}"
            ));
        }
        if events.is_none() && bytes.is_none() {
            return Ok(Self::unset());
        }
        let pause_at = Threshold {
            events: events.map(NonZeroU64::get),
            bytes: bytes.map(NonZeroU64::get),
        };
        Ok(Self {
            limits: Some(Limits {
                pause_at,
                resume_at: pause_at.scaled(low_watermark),
            }),
        })
    }

    pub fn is_set(&self) -> bool {
        self.limits.is_some()
    }

    pub(crate) fn pauses(&self, uncommitted: Charge) -> bool {
        self.limits
            .is_some_and(|limits| limits.pause_at.reached(uncommitted))
    }

    pub(crate) fn resumes(&self, uncommitted: Charge) -> bool {
        self.limits
            .is_none_or(|limits| !limits.resume_at.reached(uncommitted))
    }
}

#[cfg(test)]
mod tests {
    use rstest::rstest;

    use super::*;

    fn limits(events: u64, bytes: u64, low_watermark: f64) -> BudgetLimits {
        BudgetLimits::new(
            NonZeroU64::new(events),
            NonZeroU64::new(bytes),
            low_watermark,
        )
        .expect("valid limits")
    }

    fn charge(events: u64, bytes: u64) -> Charge {
        Charge { events, bytes }
    }

    struct Observed {
        uncommitted: Charge,
        expected: bool,
    }

    #[rstest]
    #[case::below_both_limits(Observed { uncommitted: charge(9, 999), expected: false })]
    #[case::at_the_event_limit(Observed { uncommitted: charge(10, 0), expected: true })]
    #[case::at_the_byte_limit(Observed { uncommitted: charge(0, 1000), expected: true })]
    fn a_partition_pauses_when_either_axis_reaches_its_limit(#[case] observed: Observed) {
        assert_eq!(
            limits(10, 1000, 0.8).pauses(observed.uncommitted),
            observed.expected
        );
    }

    #[rstest]
    #[case::between_the_watermark_and_the_limit(Observed { uncommitted: charge(9, 0), expected: false })]
    #[case::at_the_watermark(Observed { uncommitted: charge(8, 0), expected: false })]
    #[case::one_axis_still_at_the_watermark(Observed { uncommitted: charge(7, 800), expected: false })]
    #[case::under_the_watermark_on_both_axes(Observed { uncommitted: charge(7, 799), expected: true })]
    fn a_partition_resumes_under_the_watermark_on_every_axis(#[case] observed: Observed) {
        assert_eq!(
            limits(10, 1000, 0.8).resumes(observed.uncommitted),
            observed.expected
        );
    }

    #[test]
    fn a_full_watermark_resumes_only_below_the_limit() {
        let limits = limits(10, 0, 1.0);

        assert!(limits.pauses(charge(10, 0)));
        assert!(!limits.resumes(charge(10, 0)));
        assert!(limits.resumes(charge(9, 0)));
    }

    #[test]
    fn a_limit_above_float_precision_resumes_only_below_the_limit() {
        let limit = (1 << 53) + 3;
        let limits = limits(limit, 0, 1.0);

        assert!(limits.pauses(charge(limit, 0)));
        assert!(!limits.resumes(charge(limit, 0)));
    }

    #[rstest]
    #[case::events(limits(1, 0, 0.8), charge(1, 0))]
    #[case::bytes(limits(0, 1, 0.8), charge(0, 1))]
    fn a_limit_of_one_resumes_once_fully_refunded(
        #[case] limits: BudgetLimits,
        #[case] at_the_limit: Charge,
    ) {
        assert!(limits.pauses(at_the_limit));
        assert!(limits.resumes(Charge::ZERO));
    }

    #[test]
    fn unset_limits_never_pause() {
        let limits = BudgetLimits::new(None, None, 0.8).expect("unset is valid");
        assert!(!limits.is_set());
        assert!(!limits.pauses(charge(u64::MAX, u64::MAX)));
    }

    #[rstest]
    #[case::zero(0.0)]
    #[case::above_one(1.5)]
    #[case::negative(-0.5)]
    #[case::nan(f64::NAN)]
    fn a_watermark_outside_the_unit_interval_is_rejected(#[case] low_watermark: f64) {
        assert!(BudgetLimits::new(NonZeroU64::new(10), None, low_watermark).is_err());
    }
}
