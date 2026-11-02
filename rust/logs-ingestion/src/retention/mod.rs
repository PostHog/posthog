//! Port of `nodejs/src/logs/retention/`: `compile-retention-rules.ts`, `evaluate-retention.ts`,
//! `retention-stage.ts` and `retention-expired-stage.ts`.

pub mod compile;
pub mod evaluate;
pub mod expired;
pub mod stage;

pub use compile::{compile_retention_rule_set, RetentionRuleRow, MAX_ENABLED_RETENTION_RULES};
pub use evaluate::{
    evaluate_retention_days, is_valid_retention_days, safe_evaluate_retention_days,
    CompiledRetentionRule, CompiledRetentionRuleSet, DEFAULT_RETENTION_DAYS, MAX_RETENTION_DAYS,
    RETENTION_MONTH_DAYS,
};
pub use expired::{
    can_hold_expired_row, is_expired, make_retention_expired_stage, RETENTION_EXPIRED_STAGE_NAME,
};
pub use stage::{make_retention_stage, RETENTION_STAGE_NAME};
