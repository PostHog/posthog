use tracing::warn;

use crate::charge_limit::ChargeLimit;
use crate::config::{CompletionGranularity, Polling};
use crate::partition_budget::BudgetLimits;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Selected {
    Capped { max_in_flight_polls: usize },
    Continuous { in_flight: ChargeLimit },
}

/// Continuous polling needs `group` granularity, because at `poll` a commit
/// waits for the whole oldest poll. It needs a budget and an in-flight limit,
/// because without the admission cap they are the only bounds. Without all
/// three the capped strategy runs, so a lane rolled back to `poll` needs no
/// second setting changed.
pub(crate) fn select(
    polling: Polling,
    granularity: CompletionGranularity,
    budget: &BudgetLimits,
    in_flight: ChargeLimit,
    max_in_flight_polls: usize,
) -> Selected {
    let capped = Selected::Capped {
        max_in_flight_polls,
    };
    if polling == Polling::Capped {
        return capped;
    }
    let missing: Vec<&str> = [
        (
            granularity != CompletionGranularity::Group,
            "CONSUMER_COMPLETION_GRANULARITY=group",
        ),
        (!budget.is_set(), "a partition budget"),
        (!in_flight.is_set(), "an in-flight limit"),
    ]
    .into_iter()
    .filter_map(|(missing, requirement)| missing.then_some(requirement))
    .collect();
    if missing.is_empty() {
        return Selected::Continuous { in_flight };
    }
    warn!(
        missing = missing.join(", "),
        "Running the capped polling strategy: continuous polling needs all its requirements"
    );
    capped
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroU64;

    use super::*;

    struct SelectCase {
        granularity: CompletionGranularity,
        budget_set: bool,
        in_flight_set: bool,
        expected_continuous: bool,
    }

    #[rstest::rstest]
    #[case::all_requirements(SelectCase { granularity: CompletionGranularity::Group, budget_set: true, in_flight_set: true, expected_continuous: true })]
    #[case::poll_granularity(SelectCase { granularity: CompletionGranularity::Poll, budget_set: true, in_flight_set: true, expected_continuous: false })]
    #[case::no_budget(SelectCase { granularity: CompletionGranularity::Group, budget_set: false, in_flight_set: true, expected_continuous: false })]
    #[case::no_in_flight_limit(SelectCase { granularity: CompletionGranularity::Group, budget_set: true, in_flight_set: false, expected_continuous: false })]
    fn continuous_polling_runs_only_with_all_its_requirements(#[case] case: SelectCase) {
        let budget = if case.budget_set {
            BudgetLimits::new(NonZeroU64::new(100), None, 0.8).unwrap()
        } else {
            BudgetLimits::unset()
        };
        let in_flight = if case.in_flight_set {
            ChargeLimit::new(NonZeroU64::new(1_000), None)
        } else {
            ChargeLimit::unset()
        };

        let selected = select(Polling::Continuous, case.granularity, &budget, in_flight, 4);

        let expected = if case.expected_continuous {
            Selected::Continuous { in_flight }
        } else {
            Selected::Capped {
                max_in_flight_polls: 4,
            }
        };
        assert_eq!(selected, expected);
    }
}
