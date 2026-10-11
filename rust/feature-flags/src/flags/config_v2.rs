use std::collections::HashSet;
use std::fmt;

use once_cell::sync::Lazy;
use serde_json::value::RawValue;
use serde_json::{Map, Value};
use uuid::Uuid;

use crate::flags::flag_group_type_mapping::GroupTypeIndex;
use crate::utils::json_size::estimate_json_heap_size;

mod properties;
mod raw;
pub use properties::{Predicate, Subject};
pub(crate) use raw::validate_raw_document;

pub static MAX_CONFIG_BYTES: Lazy<usize> = Lazy::new(|| {
    std::env::var("MAX_FEATURE_FLAG_FILTER_SIZE_BYTES")
        .map(|value| {
            value
                .parse()
                .expect("MAX_FEATURE_FLAG_FILTER_SIZE_BYTES must be a nonnegative integer")
        })
        .unwrap_or(512 * 1024)
});
pub const MAX_RULES: usize = 100;
pub const MAX_PREDICATES: usize = 100;
pub const MAX_SEED_LENGTH: usize = 400;
pub const MAX_SAFE_INTEGER: f64 = 9_007_199_254_740_991.0;
pub const MAX_OBJECT_DEPTH: usize = 20;
pub const CONFIG_FIELDS: &[&str] = &[
    "version",
    "return_type",
    "default_value",
    "rules",
    "aggregation_group_type_index",
];
pub const TARGETED_RELEASE_FIELDS: &[&str] = &[
    "id",
    "rule_type",
    "targeting",
    "description",
    "metadata",
    "value",
];
pub const PERCENTAGE_ROLLOUT_FIELDS: &[&str] = &[
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
];
pub const EXPERIMENT_FIELDS: &[&str] = &[
    "id",
    "rule_type",
    "targeting",
    "description",
    "metadata",
    "experiment_id",
    "paused",
    "rollout_percentage",
    "on_rollout_miss",
    "assignment_algorithm",
    "seed",
    "assign_by",
    "variants",
    "holdout",
];
pub const VARIANT_FIELDS: &[&str] = &["key", "weight", "value"];
pub const HOLDOUT_FIELDS: &[&str] = &["id", "seed", "exclusion_percentage"];
pub const MIN_VARIANTS: usize = 2;
pub const MAX_VARIANTS: usize = 20;
pub const TARGETING_FIELDS: &[&str] = &["properties"];
pub const PROPERTY_FIELDS: &[&str] = &[
    "key",
    "type",
    "value",
    "operator",
    "negation",
    "group_type_index",
    "cohort_name",
    "group_key_names",
    "label",
];

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
    pub default_value: Option<Value>,
    pub rules: Vec<Rule>,
    /// The group type rules assign by, or `None` for persons. The parser does not admit it yet.
    pub aggregation_group_type_index: Option<GroupTypeIndex>,
}

#[derive(Clone)]
pub struct Rule {
    pub id: Uuid,
    pub targeting: Vec<Predicate>,
    pub outcome: Outcome,
}

#[derive(Clone)]
pub enum Outcome {
    TargetedRelease {
        value: Value,
    },
    PercentageRollout {
        value: Value,
        rollout_percentage: f64,
        on_rollout_miss: RolloutMiss,
        seed: String,
    },
    /// An experiment rule without an experiment: a weighted variant split. A rule linked to an
    /// Experiment row is unsupported.
    Experiment {
        paused: bool,
        rollout_percentage: f64,
        on_rollout_miss: RolloutMiss,
        seed: String,
        variants: Vec<Variant>,
        holdout: Option<Holdout>,
    },
}

#[derive(Clone)]
pub struct Variant {
    pub key: String,
    pub weight: f64,
    pub value: Value,
}

/// A rule-local holdout; its seed lives on the rule rather than on a shared holdout row.
#[derive(Clone)]
pub struct Holdout {
    pub seed: String,
    pub exclusion_percentage: f64,
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
            Self::Experiment { .. } => "Experiment { .. }",
        })
    }
}

impl Config {
    pub(super) fn parse(document: &Map<String, Value>) -> Result<Self, ParseError> {
        closed(document, CONFIG_FIELDS, "filters")?;
        let return_type = match string(document, "return_type")? {
            "boolean" => ReturnType::Boolean,
            "string" => ReturnType::String,
            "number" => ReturnType::Number,
            "object" => ReturnType::Object,
            _ => return Err(ParseError::Malformed("return_type")),
        };
        if let Some(group) = document.get("aggregation_group_type_index") {
            if !is_integer(group) {
                return Err(ParseError::Malformed("aggregation_group_type_index"));
            }
            return Err(ParseError::Unsupported("aggregation_group_type_index"));
        }
        let default_value = match required(document, "default_value")? {
            Value::Null => None,
            value if return_type.accepts(value) => Some(value.clone()),
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
                let rule = Rule::parse(value, return_type)?;
                if !seen.insert(rule.id) {
                    return Err(ParseError::Malformed("rule.id"));
                }
                Ok(rule)
            })
            .collect::<Result<_, _>>()?;
        Ok(Self {
            default_value,
            rules,
            aggregation_group_type_index: None,
        })
    }

    #[doc(hidden)]
    pub fn estimated_heap_bytes(&self) -> usize {
        self.default_value
            .as_ref()
            .map_or(0, estimate_json_heap_size)
            + self.rules.capacity() * std::mem::size_of::<Rule>()
            + self
                .rules
                .iter()
                .map(Rule::estimated_heap_bytes)
                .sum::<usize>()
    }
}

impl Rule {
    fn parse(value: &Value, return_type: ReturnType) -> Result<Self, ParseError> {
        let rule = object(value, "rule")?;
        let rule_type = string(rule, "rule_type")?;
        let fields: &[&str] = match rule_type {
            "targeted_release" => TARGETED_RELEASE_FIELDS,
            "percentage_rollout" => PERCENTAGE_ROLLOUT_FIELDS,
            // A linked experiment needs its Experiment row, which this reader does not load.
            "experiment" if rule.get("experiment_id").is_some_and(is_integer) => {
                return Err(ParseError::Unsupported("experiment_id"))
            }
            "experiment" => EXPERIMENT_FIELDS,
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
        let outcome = match rule_type {
            "targeted_release" => Outcome::TargetedRelease {
                value: typed_value(rule, return_type)?,
            },
            "percentage_rollout" => {
                let (rollout_percentage, on_rollout_miss, seed) = rollout(rule)?;
                Outcome::PercentageRollout {
                    value: typed_value(rule, return_type)?,
                    rollout_percentage,
                    on_rollout_miss,
                    seed,
                }
            }
            _ => {
                if !required(rule, "experiment_id")?.is_null() {
                    return Err(ParseError::Malformed("experiment_id"));
                }
                let paused = required(rule, "paused")?
                    .as_bool()
                    .ok_or(ParseError::Malformed("paused"))?;
                let (rollout_percentage, on_rollout_miss, seed) = rollout(rule)?;
                Outcome::Experiment {
                    paused,
                    rollout_percentage,
                    on_rollout_miss,
                    seed,
                    variants: variants(required(rule, "variants")?, return_type)?,
                    holdout: rule.get("holdout").map(holdout).transpose()?,
                }
            }
        };
        Ok(Self {
            id,
            targeting,
            outcome,
        })
    }

    fn estimated_heap_bytes(&self) -> usize {
        self.targeting.capacity() * std::mem::size_of::<Predicate>()
            + self
                .targeting
                .iter()
                .map(Predicate::estimated_heap_bytes)
                .sum::<usize>()
            + match &self.outcome {
                Outcome::PercentageRollout { seed, value, .. } => {
                    seed.capacity() + estimate_json_heap_size(value)
                }
                Outcome::TargetedRelease { value } => estimate_json_heap_size(value),
                Outcome::Experiment {
                    seed,
                    variants,
                    holdout,
                    ..
                } => {
                    seed.capacity()
                        + variants.capacity() * std::mem::size_of::<Variant>()
                        + variants
                            .iter()
                            .map(|v| v.key.capacity() + estimate_json_heap_size(&v.value))
                            .sum::<usize>()
                        + holdout.as_ref().map_or(0, |h| h.seed.capacity())
                }
            }
    }
}

fn typed_value(object: &Map<String, Value>, return_type: ReturnType) -> Result<Value, ParseError> {
    let value = required(object, "value")?;
    if !return_type.accepts(value) {
        return Err(ParseError::Malformed("value"));
    }
    Ok(value.clone())
}

fn rollout(rule: &Map<String, Value>) -> Result<(f64, RolloutMiss, String), ParseError> {
    if string(rule, "assignment_algorithm")? != "sha1_60_v1" {
        return Err(ParseError::Malformed("assignment_algorithm"));
    }
    if rule
        .get("assign_by")
        .is_some_and(|v| v.as_str() != Some("person"))
    {
        return Err(ParseError::Malformed("assign_by"));
    }
    let on_rollout_miss = match string(rule, "on_rollout_miss")? {
        "continue" => RolloutMiss::Continue,
        "return_default" => RolloutMiss::ReturnDefault,
        _ => return Err(ParseError::Malformed("on_rollout_miss")),
    };
    Ok((
        percentage(rule, "rollout_percentage")?,
        on_rollout_miss,
        seed(rule)?,
    ))
}

fn seed(object: &Map<String, Value>) -> Result<String, ParseError> {
    let seed = string(object, "seed")?;
    if !(1..=MAX_SEED_LENGTH).contains(&seed.chars().count()) {
        return Err(ParseError::Malformed("seed"));
    }
    Ok(seed.to_owned())
}

/// Weights are checked to two decimal places by the raw scan, so whole hundredths sum exactly.
fn variants(value: &Value, return_type: ReturnType) -> Result<Vec<Variant>, ParseError> {
    let items = value.as_array().ok_or(ParseError::Malformed("variants"))?;
    if items.len() > MAX_VARIANTS {
        return Err(ParseError::LimitExceeded("variants"));
    }
    if items.len() < MIN_VARIANTS {
        return Err(ParseError::Malformed("variants"));
    }
    let mut keys = HashSet::with_capacity(items.len());
    let mut hundredths = 0;
    let mut variants = Vec::with_capacity(items.len());
    for item in items {
        let variant = object(item, "variant")?;
        closed(variant, VARIANT_FIELDS, "variant")?;
        let key = string(variant, "key")?;
        if key.is_empty()
            || !key
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
            || !keys.insert(key)
        {
            return Err(ParseError::Malformed("variant.key"));
        }
        let weight = percentage(variant, "weight")?;
        hundredths += (weight * 100.0).round() as u32;
        variants.push(Variant {
            key: key.to_owned(),
            weight,
            value: typed_value(variant, return_type)?,
        });
    }
    if hundredths != 10_000 {
        return Err(ParseError::Malformed("variants"));
    }
    Ok(variants)
}

fn holdout(value: &Value) -> Result<Holdout, ParseError> {
    let holdout = object(value, "holdout")?;
    closed(holdout, HOLDOUT_FIELDS, "holdout")?;
    // A rule without an experiment carries only a rule-local holdout; a shared row is a linked experiment's.
    if !required(holdout, "id")?.is_null() {
        return Err(ParseError::Malformed("holdout.id"));
    }
    Ok(Holdout {
        seed: seed(holdout)?,
        exclusion_percentage: percentage(holdout, "exclusion_percentage")?,
    })
}

fn is_integer(value: &Value) -> bool {
    value
        .as_f64()
        .is_some_and(|n| n.is_finite() && n.fract() == 0.0)
}

#[derive(Clone, Copy)]
enum ReturnType {
    Boolean,
    String,
    Number,
    Object,
}

impl ReturnType {
    /// Whether `value` is a non-null value of this type; a null default is handled by the caller.
    fn accepts(self, value: &Value) -> bool {
        match self {
            Self::Boolean => value.is_boolean(),
            Self::String => value.as_str().is_some_and(|s| !s.is_empty()),
            Self::Number => is_safe_number(value),
            Self::Object => value.is_object() && is_nested_value(value, 1),
        }
    }
}

fn is_safe_number(value: &Value) -> bool {
    value
        .as_f64()
        .is_some_and(|n| (-MAX_SAFE_INTEGER..=MAX_SAFE_INTEGER).contains(&n))
}

/// Depth counts object and array containers, with the returned object at level 1.
fn is_nested_value(value: &Value, depth: usize) -> bool {
    match value {
        Value::Object(map) => {
            depth <= MAX_OBJECT_DEPTH && map.values().all(|v| is_nested_value(v, depth + 1))
        }
        Value::Array(items) => {
            depth <= MAX_OBJECT_DEPTH && items.iter().all(|v| is_nested_value(v, depth + 1))
        }
        Value::Number(_) => is_safe_number(value),
        Value::Null | Value::Bool(_) | Value::String(_) => true,
    }
}

fn percentage(object: &Map<String, Value>, field: &'static str) -> Result<f64, ParseError> {
    let error = ParseError::Malformed(field);
    let Value::Number(number) = required(object, field)? else {
        return Err(error);
    };
    let numeric = number.as_f64().ok_or(error)?;
    if !numeric.is_finite() || !(0.0..=100.0).contains(&numeric) {
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
