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
    /// Person conditions were evaluated and didn't match, AND one or more group
    /// conditions were skipped because the caller didn't provide the required group
    /// type. Serializes as `no_condition_match` for backward compatibility — the
    /// enriched description carries the extra signal about skipped groups.
    #[strum(serialize = "no_condition_match_groups_not_evaluated")]
    NoConditionMatchGroupsNotEvaluated,
    #[strum(serialize = "holdout_condition_value")]
    HoldoutConditionValue,
    #[strum(serialize = "flag_disabled")]
    FlagDisabled,
    #[strum(serialize = "missing_dependency")]
    MissingDependency,
}

impl FeatureFlagMatchReason {
    pub fn score(&self) -> i32 {
        // Higher scores win when multiple conditions report different non-matching reasons.
        // The intent is to surface the most informative reason for the caller:
        // a real evaluation result outranks a "this condition wasn't applicable to you"
        // signal. NoGroupType sits below NoConditionMatch and OutOfRolloutBound so that
        // mixed-targeting flags don't bury a person-condition's actual result behind a
        // skipped group condition.
        match self {
            FeatureFlagMatchReason::SuperConditionValue => 6,
            FeatureFlagMatchReason::HoldoutConditionValue => 5,
            FeatureFlagMatchReason::ConditionMatch => 4,
            FeatureFlagMatchReason::OutOfRolloutBound => 3,
            FeatureFlagMatchReason::NoConditionMatch => 2,
            FeatureFlagMatchReason::NoConditionMatchGroupsNotEvaluated => 2,
            FeatureFlagMatchReason::NoGroupType => 1,
            FeatureFlagMatchReason::FlagDisabled => 0,
            FeatureFlagMatchReason::MissingDependency => -1,
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
                FeatureFlagMatchReason::NoConditionMatchGroupsNotEvaluated => "no_condition_match",
                FeatureFlagMatchReason::OutOfRolloutBound => "out_of_rollout_bound",
                FeatureFlagMatchReason::NoGroupType => "no_group_type",
                FeatureFlagMatchReason::HoldoutConditionValue => "holdout_condition_value",
                FeatureFlagMatchReason::FlagDisabled => "flag_disabled",
                FeatureFlagMatchReason::MissingDependency => "missing_dependency",
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
            FeatureFlagMatchReason::MissingDependency, // -1
            FeatureFlagMatchReason::FlagDisabled,      // 0
            FeatureFlagMatchReason::NoGroupType,       // 1
            FeatureFlagMatchReason::NoConditionMatch,  // 2
            FeatureFlagMatchReason::NoConditionMatchGroupsNotEvaluated, // 2 (same tier)
            FeatureFlagMatchReason::OutOfRolloutBound, // 3
            FeatureFlagMatchReason::ConditionMatch,    // 4
            FeatureFlagMatchReason::HoldoutConditionValue, // 5
            FeatureFlagMatchReason::SuperConditionValue, // 6
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
            FeatureFlagMatchReason::NoConditionMatchGroupsNotEvaluated.to_string(),
            "no_condition_match"
        );
        assert_eq!(
            FeatureFlagMatchReason::FlagDisabled.to_string(),
            "flag_disabled"
        );
        assert_eq!(
            FeatureFlagMatchReason::HoldoutConditionValue.to_string(),
            "holdout_condition_value"
        );
        assert_eq!(
            FeatureFlagMatchReason::MissingDependency.to_string(),
            "missing_dependency"
        );
    }
}
