use std::collections::HashMap;
use std::fmt;

use chrono::{DateTime, Utc};
use chrono_tz::Tz;
use fancy_regex::RegexBuilder;
use serde_json::Value;
use uuid::Uuid;

use super::config_v2::{Config, Outcome, RolloutMiss};
use super::flag_matching_utils::calculate_hash;
use super::flag_request::MAX_DISTINCT_ID_LEN;
use crate::properties::property_matching::{
    match_property_input, FlagMatchingError, PropertyMatchInput, PropertyMatchingContext,
    REGEX_BACKTRACK_LIMIT,
};
use crate::properties::property_models::{CompiledRegex, OperatorType};

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

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Evaluation {
    TargetingMatch {
        value: bool,
        rule: MatchedRule,
    },
    RolloutMiss {
        value: Option<bool>,
        rule: MatchedRule,
    },
    NoRuleMatch {
        value: Option<bool>,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EvaluationError {
    MissingContext,
    InvalidProperty,
    InvalidRegex,
    Hash,
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
/// Keep this preparation alive across evaluations to reuse compiled patterns.
pub struct Evaluator<'a> {
    config: &'a Config,
    regexes: Vec<Vec<Option<CompiledRegex>>>,
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
        let regexes = config
            .rules
            .iter()
            .map(|rule| {
                rule.targeting
                    .iter()
                    .map(|predicate| {
                        if !matches!(
                            predicate.operator,
                            OperatorType::Regex | OperatorType::NotRegex
                        ) {
                            return None;
                        }
                        let pattern = predicate.value.as_ref().and_then(Value::as_str);
                        Some(
                            match pattern.and_then(|pattern| {
                                RegexBuilder::new(pattern)
                                    .backtrack_limit(REGEX_BACKTRACK_LIMIT)
                                    .build()
                                    .ok()
                            }) {
                                Some(regex) => CompiledRegex::Compiled(regex),
                                None => CompiledRegex::InvalidPattern,
                            },
                        )
                    })
                    .collect()
            })
            .collect();
        Self { config, regexes }
    }

    /// Uses the same per-pattern estimate as v1 preparation; compiled engine allocations are opaque.
    pub fn estimated_heap_bytes(&self) -> usize {
        self.regexes.capacity() * std::mem::size_of::<Vec<Option<CompiledRegex>>>()
            + self
                .regexes
                .iter()
                .map(|rule| {
                    rule.capacity() * std::mem::size_of::<Option<CompiledRegex>>()
                        + rule
                            .iter()
                            .filter(|regex| matches!(regex, Some(CompiledRegex::Compiled(_))))
                            .count()
                            * 2048
                })
                .sum::<usize>()
    }

    pub fn evaluate(&self, context: &EvaluationContext<'_>) -> Result<Evaluation, EvaluationError> {
        self.evaluate_with_hash(context, |seed, subject| {
            calculate_hash(&format!("{seed}."), subject, "").map_err(|_| EvaluationError::Hash)
        })
    }

    fn evaluate_with_hash(
        &self,
        context: &EvaluationContext<'_>,
        mut hash: impl FnMut(&str, &str) -> Result<f64, EvaluationError>,
    ) -> Result<Evaluation, EvaluationError> {
        let subject = truncate_subject(context.person_identifier);
        let matching =
            PropertyMatchingContext::new(context.timezone, context.use_explicit_exact_matching)
                .at_time(context.now);
        let mut hashes = HashMap::new();
        for (index, rule) in self.config.rules.iter().enumerate() {
            let mut matches = true;
            for (predicate, regex) in rule.targeting.iter().zip(&self.regexes[index]) {
                let (properties, partial) = match context.properties {
                    PersonProperties::Complete(properties) => (properties, false),
                    PersonProperties::Partial(properties) => (properties, true),
                    PersonProperties::Unavailable => return Err(EvaluationError::MissingContext),
                };
                if partial && !properties.contains_key(&predicate.key) {
                    return Err(EvaluationError::MissingContext);
                }
                // An invalid pattern is not a conclusive false result that negation can invert.
                if matches!(regex, Some(CompiledRegex::InvalidPattern)) {
                    return Err(EvaluationError::InvalidRegex);
                }
                let matched = match_property_input(
                    PropertyMatchInput {
                        key: &predicate.key,
                        value: predicate.value.as_ref(),
                        operator: predicate.operator,
                        compiled_regex: regex.as_ref(),
                    },
                    properties,
                    partial,
                    matching,
                )
                .map_err(|error| match error {
                    FlagMatchingError::MissingProperty(_)
                    | FlagMatchingError::InconclusiveOperatorMatch => {
                        EvaluationError::MissingContext
                    }
                    FlagMatchingError::ValidationError(_) => EvaluationError::InvalidProperty,
                    FlagMatchingError::InvalidRegexPattern => EvaluationError::InvalidRegex,
                })?;
                if matched == predicate.negation {
                    matches = false;
                    break;
                }
            }
            if !matches {
                continue;
            }
            let (kind, value) = match &rule.outcome {
                Outcome::TargetedRelease { value } => (RuleKind::TargetedRelease, *value),
                Outcome::PercentageRollout {
                    value,
                    rollout_percentage,
                    on_rollout_miss,
                    seed,
                } => {
                    let included = if subject.is_empty() {
                        false
                    } else if *rollout_percentage == 100.0 {
                        true
                    } else {
                        let hash = match hashes.get(seed.as_str()) {
                            Some(value) => *value,
                            None => {
                                let value = hash(seed, subject)?;
                                hashes.insert(seed.as_str(), value);
                                value
                            }
                        };
                        hash <= rollout_percentage / 100.0
                    };
                    if !included {
                        match on_rollout_miss {
                            RolloutMiss::Continue => continue,
                            RolloutMiss::ReturnDefault => {
                                return Ok(Evaluation::RolloutMiss {
                                    value: self.config.default_value,
                                    rule: MatchedRule {
                                        id: rule.id,
                                        index,
                                        kind: RuleKind::PercentageRollout,
                                    },
                                })
                            }
                        }
                    }
                    (RuleKind::PercentageRollout, *value)
                }
            };
            return Ok(Evaluation::TargetingMatch {
                value,
                rule: MatchedRule {
                    id: rule.id,
                    index,
                    kind,
                },
            });
        }
        Ok(Evaluation::NoRuleMatch {
            value: self.config.default_value,
        })
    }
}

fn truncate_subject(subject: &str) -> &str {
    let end = subject
        .char_indices()
        .nth(MAX_DISTINCT_ID_LEN)
        .map_or(subject.len(), |(index, _)| index);
    &subject[..end]
}

#[cfg(test)]
#[path = "evaluate_v2/tests.rs"]
mod tests;
