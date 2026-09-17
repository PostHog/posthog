use std::collections::HashSet;
use std::fmt;

use serde_json::value::RawValue;
use serde_json::{Map, Value};
use uuid::Uuid;

use crate::utils::json_size::estimate_json_map_size;

mod properties;
mod raw;
pub use properties::PersonPredicate;
pub(crate) use raw::{classify_number, validate_raw_percentages};

pub const MAX_CONFIG_BYTES: usize = 512 * 1024;
const MAX_RULES: usize = 100;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ParseError {
    Malformed(&'static str),
    Unsupported(&'static str),
    LimitExceeded(&'static str),
}

#[derive(Clone)]
pub struct NonV1Config {
    pub parsed_v2: Option<Result<Config, ParseError>>,
    pub(crate) document: Box<RawValue>,
}

impl fmt::Debug for NonV1Config {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("NonV1Config")
            .field("parsed_v2", &self.parsed_v2)
            .finish_non_exhaustive()
    }
}

impl NonV1Config {
    pub(crate) fn estimated_heap_bytes(&self) -> usize {
        std::mem::size_of::<Self>()
            + 2 * std::mem::size_of::<usize>()
            + self.document.get().len()
            + self
                .parsed_v2
                .as_ref()
                .and_then(|parsed| parsed.as_ref().ok())
                .map_or(0, Config::estimated_heap_bytes)
    }
}

#[derive(Clone)]
pub struct Config {
    pub default_value: Option<bool>,
    pub rules: Vec<Rule>,
}

#[derive(Clone)]
pub struct Rule {
    pub id: Uuid,
    pub targeting: Vec<PersonPredicate>,
    pub outcome: Outcome,
}

#[derive(Clone)]
pub enum Outcome {
    TargetedRelease {
        value: bool,
    },
    PercentageRollout {
        value: bool,
        rollout_percentage: f64,
        on_rollout_miss: RolloutMiss,
        seed: String,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RolloutMiss {
    Continue,
    ReturnDefault,
}

impl fmt::Debug for Config {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("V2Config")
            .field("rule_count", &self.rules.len())
            .finish_non_exhaustive()
    }
}

impl fmt::Debug for Rule {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("V2Rule")
            .field("predicate_count", &self.targeting.len())
            .field("outcome", &self.outcome)
            .finish_non_exhaustive()
    }
}

impl fmt::Debug for Outcome {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::TargetedRelease { .. } => "TargetedRelease { .. }",
            Self::PercentageRollout { .. } => "PercentageRollout { .. }",
        })
    }
}

impl Config {
    pub fn parse(document: &Map<String, Value>) -> Result<Self, ParseError> {
        // Match the existing writer's default document ceiling. Deployment-specific
        // writer limits can be lower; metadata remains part of the whole document.
        if estimate_json_map_size(document) + 2 > MAX_CONFIG_BYTES {
            return Err(ParseError::LimitExceeded("filters"));
        }
        if document.get("version").and_then(Value::as_f64) != Some(2.0) {
            return Err(ParseError::Malformed("version"));
        }
        closed(
            document,
            &[
                "version",
                "return_type",
                "default_value",
                "rules",
                "aggregation_group_type_index",
            ],
            "filters",
        )?;
        match string(document, "return_type")? {
            "boolean" => {}
            "string" | "number" | "object" => {
                return Err(ParseError::Unsupported("return_type"));
            }
            _ => return Err(ParseError::Malformed("return_type")),
        }
        if let Some(group) = document.get("aggregation_group_type_index") {
            if !group
                .as_f64()
                .is_some_and(|n| n.is_finite() && n.fract() == 0.0)
            {
                return Err(ParseError::Malformed("aggregation_group_type_index"));
            }
            return Err(ParseError::Unsupported("aggregation_group_type_index"));
        }
        let default_value = match required(document, "default_value")? {
            Value::Null => None,
            Value::Bool(value) => Some(*value),
            _ => return Err(ParseError::Malformed("default_value")),
        };
        let rules = required(document, "rules")?
            .as_array()
            .ok_or(ParseError::Malformed("rules"))?;
        if rules.len() > MAX_RULES {
            return Err(ParseError::LimitExceeded("rules"));
        }
        let mut seen = HashSet::with_capacity(rules.len());
        let rules = rules
            .iter()
            .map(|value| {
                let rule = Rule::parse(value)?;
                if !seen.insert(rule.id) {
                    return Err(ParseError::Malformed("rule.id"));
                }
                Ok(rule)
            })
            .collect::<Result<_, _>>()?;
        Ok(Self {
            default_value,
            rules,
        })
    }

    pub(crate) fn estimated_heap_bytes(&self) -> usize {
        self.rules.capacity() * std::mem::size_of::<Rule>()
            + self
                .rules
                .iter()
                .map(Rule::estimated_heap_bytes)
                .sum::<usize>()
    }
}

impl Rule {
    fn parse(value: &Value) -> Result<Self, ParseError> {
        let rule = object(value, "rule")?;
        let rule_type = string(rule, "rule_type")?;
        let fields: &[&str] = match rule_type {
            "targeted_release" => &[
                "id",
                "rule_type",
                "targeting",
                "description",
                "metadata",
                "value",
            ],
            "percentage_rollout" => &[
                "id",
                "rule_type",
                "targeting",
                "description",
                "metadata",
                "value",
                "rollout_percentage",
                "on_rollout_miss",
                "assignment_algorithm",
                "seed",
                "assign_by",
            ],
            "experiment" => return Err(ParseError::Unsupported("rule_type")),
            _ => return Err(ParseError::Malformed("rule_type")),
        };
        closed(rule, fields, "rule")?;
        let id = string(rule, "id")?;
        // UUID's general parser also accepts compact and URN forms; the wire does not.
        if id.len() != 36 || [8, 13, 18, 23].iter().any(|&i| id.as_bytes()[i] != b'-') {
            return Err(ParseError::Malformed("rule.id"));
        }
        let id = Uuid::parse_str(id).map_err(|_| ParseError::Malformed("rule.id"))?;
        if rule.get("description").is_some_and(|v| !v.is_string()) {
            return Err(ParseError::Malformed("description"));
        }
        if rule.get("metadata").is_some_and(|v| !v.is_object()) {
            return Err(ParseError::Malformed("metadata"));
        }
        let targeting = properties::parse_targeting(required(rule, "targeting")?)?;
        let value = required(rule, "value")?
            .as_bool()
            .ok_or(ParseError::Malformed("value"))?;
        let outcome = if rule_type == "targeted_release" {
            Outcome::TargetedRelease { value }
        } else {
            if string(rule, "assignment_algorithm")? != "sha1_60_v1" {
                return Err(ParseError::Malformed("assignment_algorithm"));
            }
            if rule
                .get("assign_by")
                .is_some_and(|v| v.as_str() != Some("person"))
            {
                return Err(ParseError::Malformed("assign_by"));
            }
            let seed = string(rule, "seed")?;
            if !(1..=400).contains(&seed.chars().count()) {
                return Err(ParseError::Malformed("seed"));
            }
            let on_rollout_miss = match string(rule, "on_rollout_miss")? {
                "continue" => RolloutMiss::Continue,
                "return_default" => RolloutMiss::ReturnDefault,
                _ => return Err(ParseError::Malformed("on_rollout_miss")),
            };
            Outcome::PercentageRollout {
                value,
                rollout_percentage: percentage(required(rule, "rollout_percentage")?)?,
                on_rollout_miss,
                seed: seed.to_owned(),
            }
        };
        Ok(Self {
            id,
            targeting,
            outcome,
        })
    }

    fn estimated_heap_bytes(&self) -> usize {
        self.targeting.capacity() * std::mem::size_of::<PersonPredicate>()
            + self
                .targeting
                .iter()
                .map(PersonPredicate::estimated_heap_bytes)
                .sum::<usize>()
            + match &self.outcome {
                Outcome::PercentageRollout { seed, .. } => seed.capacity(),
                Outcome::TargetedRelease { .. } => 0,
            }
    }
}

fn percentage(value: &Value) -> Result<f64, ParseError> {
    let error = ParseError::Malformed("rollout_percentage");
    let Value::Number(number) = value else {
        return Err(error);
    };
    let numeric = number.as_f64().ok_or(error)?;
    if !numeric.is_finite() || !(0.0..=100.0).contains(&numeric) {
        return Err(error);
    }
    if !raw::decimal_places_at_most(&number.to_string(), 2) {
        return Err(error);
    }
    Ok(numeric)
}

fn object<'a>(value: &'a Value, field: &'static str) -> Result<&'a Map<String, Value>, ParseError> {
    value.as_object().ok_or(ParseError::Malformed(field))
}

fn required<'a>(
    object: &'a Map<String, Value>,
    field: &'static str,
) -> Result<&'a Value, ParseError> {
    object.get(field).ok_or(ParseError::Malformed(field))
}

fn string<'a>(object: &'a Map<String, Value>, field: &'static str) -> Result<&'a str, ParseError> {
    required(object, field)?
        .as_str()
        .ok_or(ParseError::Malformed(field))
}

fn closed(
    object: &Map<String, Value>,
    fields: &[&str],
    field: &'static str,
) -> Result<(), ParseError> {
    if object.keys().any(|key| !fields.contains(&key.as_str())) {
        return Err(ParseError::Malformed(field));
    }
    Ok(())
}
