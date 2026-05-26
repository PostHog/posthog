//! HogVM-backed error tracking rules.
//!
//! This crate owns rule DTOs and bytecode evaluation. Persistence stays behind
//! repository traits so runtime crates can decide where rules are loaded from
//! and how invalid rules are disabled.

pub mod assignment;
pub mod grouping;
pub mod suppression;

pub use assignment::{
    evaluate_assignment_rules, Assignee, Assignment, AssignmentIssue, AssignmentRule,
    AssignmentRuleDisabledData, AssignmentRuleRepository, NewAssignment,
};
pub use grouping::{
    evaluate_grouping_rules, GroupingRule, GroupingRuleDisabledData, GroupingRuleRepository,
};
pub use suppression::{
    evaluate_suppression_rules, SuppressionRule, SuppressionRuleDisabledData,
    SuppressionRuleRepository,
};

const ASSIGNMENT_RULES_DISABLED: &str = "cymbal_assignment_rules_disabled";
const ASSIGNMENT_RULES_FOUND: &str = "cymbal_assignment_rules_found";
const ASSIGNMENT_RULES_PROCESSING_TIME: &str = "cymbal_assignment_rules_processing_time";
const ASSIGNMENT_RULES_TRIED: &str = "cymbal_assignment_rules_tried";
const AUTO_ASSIGNMENTS: &str = "cymbal_auto_assignments";
const CUSTOM_GROUPED_EVENTS: &str = "cymbal_custom_grouped_events";
const GROUPING_RULES_DISABLED: &str = "cymbal_grouping_rules_disabled";
const GROUPING_RULES_FOUND: &str = "cymbal_grouping_rules_found";
const GROUPING_RULES_PROCESSING_TIME: &str = "cymbal_grouping_rules_processing_time";
const GROUPING_RULES_TRIED: &str = "cymbal_grouping_rules_tried";
const RULE_SUPPRESSED_EVENTS: &str = "cymbal_rule_suppressed_events";
const SUPPRESSION_RULES_DISABLED: &str = "cymbal_suppression_rules_disabled";
const SUPPRESSION_RULES_TRIED: &str = "cymbal_suppression_rules_tried";
