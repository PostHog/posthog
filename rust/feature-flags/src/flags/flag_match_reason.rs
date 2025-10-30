use std::cmp::Ordering;
use strum::EnumString;

#[derive(Debug, Clone, PartialEq, Eq, EnumString)]
pub enum FeatureFlagMatchReason {
    #[strum(serialize = "super_condition_value")]
    SuperConditionValue,
    #[strum(serialize = "condition_match")]
    ConditionMatch,
    #[strum(serialize = "no_condition_match")]
    NoConditionMatch,
    #[strum(serialize = "out_of_rollout_bound")]
    OutOfRolloutBound,
    #[strum(serialize = "no_group_type")]
    NoGroupType,
    #[strum(serialize = "holdout_condition_value")]
    HoldoutConditionValue,
    #[strum(serialize = "flag_disabled")]
    FlagDisabled,
}

impl FeatureFlagMatchReason {
    pub fn score(&self) -> i32 {
        match self {
            FeatureFlagMatchReason::SuperConditionValue => 5,
            FeatureFlagMatchReason::HoldoutConditionValue => 4,
            FeatureFlagMatchReason::ConditionMatch => 3,
            FeatureFlagMatchReason::NoGroupType => 2,
            FeatureFlagMatchReason::OutOfRolloutBound => 1,
            FeatureFlagMatchReason::NoConditionMatch => 0,
            FeatureFlagMatchReason::FlagDisabled => 0,
        }
    }
}

impl PartialOrd for FeatureFlagMatchReason {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for FeatureFlagMatchReason {
    fn cmp(&self, other: &Self) -> Ordering {
        self.score().cmp(&other.score())
    }
}

impl std::fmt::Display for FeatureFlagMatchReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "{}",
            match self {
                FeatureFlagMatchReason::SuperConditionValue => "super_condition_value",
                FeatureFlagMatchReason::ConditionMatch => "condition_match",
                FeatureFlagMatchReason::NoConditionMatch => "no_condition_match",
                FeatureFlagMatchReason::OutOfRolloutBound => "out_of_rollout_bound",
                FeatureFlagMatchReason::NoGroupType => "no_group_type",
                FeatureFlagMatchReason::HoldoutConditionValue => "holdout_condition_value",
                FeatureFlagMatchReason::FlagDisabled => "flag_disabled",
            }
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ordering() {
        let reasons = vec![
            FeatureFlagMatchReason::NoConditionMatch,
            FeatureFlagMatchReason::OutOfRolloutBound,
            FeatureFlagMatchReason::NoGroupType,
            FeatureFlagMatchReason::ConditionMatch,
            FeatureFlagMatchReason::SuperConditionValue,
            FeatureFlagMatchReason::FlagDisabled,
        ];

        let mut sorted_reasons = reasons.clone();
        sorted_reasons.sort();

        assert_eq!(sorted_reasons, reasons);
    }

    #[test]
    fn test_display() {
        assert_eq!(
            FeatureFlagMatchReason::SuperConditionValue.to_string(),
            "super_condition_value"
        );
        assert_eq!(
            FeatureFlagMatchReason::ConditionMatch.to_string(),
            "condition_match"
        );
        assert_eq!(
            FeatureFlagMatchReason::NoConditionMatch.to_string(),
            "no_condition_match"
        );
        assert_eq!(
            FeatureFlagMatchReason::OutOfRolloutBound.to_string(),
            "out_of_rollout_bound"
        );
        assert_eq!(
            FeatureFlagMatchReason::NoGroupType.to_string(),
            "no_group_type"
        );
        assert_eq!(
            FeatureFlagMatchReason::FlagDisabled.to_string(),
            "flag_disabled"
        );
    }
}
