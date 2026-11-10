use super::ledger::ClientCount;

#[derive(Debug, Clone, Copy)]
pub struct LoopRule {
    pub short_limit: u64,
    pub day_limit: u64,
}

impl Default for LoopRule {
    fn default() -> Self {
        Self {
            short_limit: 20,
            day_limit: 100,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LoopDecision {
    pub collapsed: bool,
    /// The client's count for the issue in the short window, including this event.
    pub short_count: Option<u64>,
    /// The issue tracks the maximum number of clients, so this client has no daily count.
    pub client_cap_reached: bool,
}

impl LoopRule {
    /// Decide for the event at `position` (from 1) among the events that one
    /// client sent for one issue in the batch. `before` is the client's counts before the batch.
    pub fn evaluate(&self, before: ClientCount, position: u64) -> LoopDecision {
        let short_count = before.short_window.map(|count| count + position);
        let day_count = before.day.map(|count| count + position);
        LoopDecision {
            collapsed: short_count.is_some_and(|count| count > self.short_limit)
                || day_count.is_some_and(|count| count > self.day_limit),
            short_count,
            client_cap_reached: before.day.is_none(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn collapses_past_either_limit_and_never_without_a_count() {
        let rule = LoopRule {
            short_limit: 2,
            day_limit: 5,
        };
        let counted = |day, short_window| ClientCount {
            day: Some(day),
            short_window: Some(short_window),
        };
        assert!(!rule.evaluate(counted(0, 0), 2).collapsed);
        assert!(rule.evaluate(counted(0, 0), 3).collapsed);
        assert!(!rule.evaluate(counted(4, 0), 1).collapsed);
        assert!(rule.evaluate(counted(5, 0), 1).collapsed);

        let capped = rule.evaluate(
            ClientCount {
                day: None,
                short_window: None,
            },
            1_000,
        );
        assert!(!capped.collapsed);
        assert!(capped.client_cap_reached);
        assert_eq!(capped.short_count, None);
    }
}
