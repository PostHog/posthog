use std::collections::hash_map::Entry;
use std::collections::HashMap;
use std::fmt;

use chrono::{DateTime, Utc};
use chrono_tz::Tz;
use serde_json::Value;
use uuid::Uuid;

use super::config_v2::{Config, Outcome, RolloutMiss, Rule};
use super::flag_matching_utils::calculate_hash;
use super::flag_request::MAX_DISTINCT_ID_LEN;
use super::v1_bucketing::is_in_rollout;
use crate::api::errors::FlagError;
use crate::handler::canonical_log::truncate_chars;
use crate::properties::property_matching::{
    match_property_input, FlagMatchingError, PropertyMatchInput, PropertyMatchingContext,
};
use crate::properties::property_models::CompiledRegex;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RuleKind {
    TargetedRelease,
    PercentageRollout,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MatchedRule {
    pub id: Uuid,
    pub index: usize,
    pub kind: RuleKind,
}

/// `value` borrows the parsed JSON of the flag's return type from the configuration; `None`
/// is a null default.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Evaluation<'a> {
    TargetingMatch {
        value: &'a Value,
        rule: MatchedRule,
    },
    RolloutMiss {
        value: Option<&'a Value>,
        rule: MatchedRule,
    },
    NoRuleMatch {
        value: Option<&'a Value>,
    },
}

impl RuleKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::TargetedRelease => "targeted_release",
            Self::PercentageRollout => "percentage_rollout",
        }
    }
}

impl<'a> Evaluation<'a> {
    pub const fn code(self) -> &'static str {
        match self {
            Self::TargetingMatch { .. } => "targeting_match",
            Self::RolloutMiss { .. } => "rollout_miss",
            Self::NoRuleMatch { .. } => "no_rule_match",
        }
    }

    pub fn value(self) -> Option<&'a Value> {
        match self {
            Self::TargetingMatch { value, .. } => Some(value),
            Self::RolloutMiss { value, .. } | Self::NoRuleMatch { value } => value,
        }
    }

    pub fn rule(self) -> Option<MatchedRule> {
        match self {
            Self::TargetingMatch { rule, .. } | Self::RolloutMiss { rule, .. } => Some(rule),
            Self::NoRuleMatch { .. } => None,
        }
    }

    pub fn description(self) -> String {
        match self {
            Self::TargetingMatch { rule, .. } => format!("Matched rule {}", rule.index + 1),
            Self::RolloutMiss { rule, .. } => format!("Rule {} rollout miss", rule.index + 1),
            Self::NoRuleMatch { .. } => "No rule matched".to_string(),
        }
    }
}

/// The parts of an [`Evaluation`] the v3 record reads, owned so they outlive the configuration.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EvaluationDetail {
    pub code: &'static str,
    /// `Value::Null` is a null default.
    pub value: Value,
    pub rule: Option<MatchedRule>,
    pub description: String,
}

impl From<Evaluation<'_>> for EvaluationDetail {
    fn from(evaluation: Evaluation<'_>) -> Self {
        Self {
            code: evaluation.code(),
            value: evaluation.value().cloned().unwrap_or(Value::Null),
            rule: evaluation.rule(),
            description: evaluation.description(),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EvaluationError {
    MissingContext,
    InvalidProperty,
    InvalidRegex,
    Hash,
}

impl From<EvaluationError> for FlagError {
    fn from(error: EvaluationError) -> Self {
        FlagError::flag_evaluation(error)
    }
}

#[derive(Clone, Copy)]
pub enum PersonProperties<'a> {
    Complete(&'a HashMap<String, Value>),
    Partial(&'a HashMap<String, Value>),
    Unavailable,
}

pub struct EvaluationContext<'a> {
    // The service adapter supplies the person distinct ID, without device or continuity overrides.
    pub person_identifier: &'a str,
    pub properties: PersonProperties<'a>,
    pub timezone: Tz,
    pub use_explicit_exact_matching: bool,
    pub now: DateTime<Utc>,
}

impl fmt::Debug for EvaluationContext<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("EvaluationContext").finish_non_exhaustive()
    }
}

/// Borrows the reader's validated configuration. Admission and eligibility belong to the caller.
/// Cheap to build per request; compiled patterns live on the cached configuration.
pub struct Evaluator<'a> {
    config: &'a Config,
}

impl fmt::Debug for Evaluator<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("V2Evaluator")
            .field("rule_count", &self.config.rules.len())
            .finish_non_exhaustive()
    }
}

impl<'a> Evaluator<'a> {
    pub fn new(config: &'a Config) -> Self {
        Self { config }
    }

    pub fn evaluate(
        &self,
        context: &EvaluationContext<'_>,
    ) -> Result<Evaluation<'a>, EvaluationError> {
        self.evaluate_with_hash(context, |seed, subject| {
            calculate_hash(&format!("{seed}."), subject, "").map_err(|_| EvaluationError::Hash)
        })
    }

    /// Test seam for injecting hash values; not part of the supported API.
    #[doc(hidden)]
    pub fn evaluate_with_hash(
        &self,
        context: &EvaluationContext<'_>,
        mut hash: impl FnMut(&str, &str) -> Result<f64, EvaluationError>,
    ) -> Result<Evaluation<'a>, EvaluationError> {
        let subject = truncate_chars(context.person_identifier, MAX_DISTINCT_ID_LEN);
        let matching =
            PropertyMatchingContext::new(context.timezone, context.use_explicit_exact_matching)
                .at_time(context.now);
        // Unavailable properties fail only once a predicate is reached.
        let person_properties = match context.properties {
            PersonProperties::Complete(properties) => Some((properties, false)),
            PersonProperties::Partial(properties) => Some((properties, true)),
            PersonProperties::Unavailable => None,
        };
        let mut hashes = HashMap::new();
        for (index, rule) in self.config.rules.iter().enumerate() {
            if !rule_targets(rule, person_properties, matching)? {
                continue;
            }
            let matched_rule = |kind| MatchedRule {
                id: rule.id,
                index,
                kind,
            };
            let (kind, value) = match &rule.outcome {
                Outcome::TargetedRelease { value } => (RuleKind::TargetedRelease, value),
                Outcome::PercentageRollout {
                    value,
                    rollout_percentage,
                    on_rollout_miss,
                    seed,
                } => {
                    let included = !subject.is_empty()
                        && is_in_rollout(*rollout_percentage, || {
                            match hashes.entry(seed.as_str()) {
                                Entry::Occupied(entry) => Ok(*entry.get()),
                                Entry::Vacant(entry) => {
                                    hash(seed, subject).map(|value| *entry.insert(value))
                                }
                            }
                        })?;
                    if !included {
                        match on_rollout_miss {
                            RolloutMiss::Continue => continue,
                            RolloutMiss::ReturnDefault => {
                                return Ok(Evaluation::RolloutMiss {
                                    value: self.config.default_value.as_ref(),
                                    rule: matched_rule(RuleKind::PercentageRollout),
                                })
                            }
                        }
                    }
                    (RuleKind::PercentageRollout, value)
                }
            };
            return Ok(Evaluation::TargetingMatch {
                value,
                rule: matched_rule(kind),
            });
        }
        Ok(Evaluation::NoRuleMatch {
            value: self.config.default_value.as_ref(),
        })
    }
}

/// Whether every predicate of `rule` matches; a reached error fails the evaluation.
fn rule_targets(
    rule: &Rule,
    person_properties: Option<(&HashMap<String, Value>, bool)>,
    matching: PropertyMatchingContext,
) -> Result<bool, EvaluationError> {
    for predicate in &rule.targeting {
        let (properties, partial) = person_properties.ok_or(EvaluationError::MissingContext)?;
        if partial && !properties.contains_key(&predicate.key) {
            return Err(EvaluationError::MissingContext);
        }
        let regex = predicate.compiled_regex.as_ref();
        // An invalid pattern is not a conclusive false result that negation can invert.
        if matches!(regex, Some(CompiledRegex::InvalidPattern)) {
            return Err(EvaluationError::InvalidRegex);
        }
        let matched = match_property_input(
            PropertyMatchInput {
                key: &predicate.key,
                value: predicate.value.as_ref(),
                operator: predicate.operator,
                compiled_regex: regex,
            },
            properties,
            partial,
            matching,
        )
        .map_err(|error| match error {
            FlagMatchingError::MissingProperty(_)
            | FlagMatchingError::InconclusiveOperatorMatch => EvaluationError::MissingContext,
            FlagMatchingError::ValidationError(_) => EvaluationError::InvalidProperty,
            FlagMatchingError::InvalidRegexPattern => EvaluationError::InvalidRegex,
        })?;
        if matched == predicate.negation {
            return Ok(false);
        }
    }
    Ok(true)
}
