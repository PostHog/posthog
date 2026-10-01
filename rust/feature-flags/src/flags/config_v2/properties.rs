use std::fmt;

use serde_json::Value;

use super::{
    closed, object, required, string, ParseError, MAX_PREDICATES, PROPERTY_FIELDS, TARGETING_FIELDS,
};
use crate::properties::property_matching::to_semver_representation;
use crate::properties::property_models::{
    CompiledRegex, OperatorType, ESTIMATED_COMPILED_REGEX_BYTES,
};
use crate::properties::relative_date::parse_relative_date_parts;
use crate::utils::json_size::estimate_json_heap_size;

#[derive(Clone)]
pub struct PersonPredicate {
    pub key: String,
    pub value: Option<Value>,
    pub operator: OperatorType,
    pub negation: bool,
    pub compiled_regex: Option<CompiledRegex>,
}

impl fmt::Debug for PersonPredicate {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("PersonPredicate")
            .field("operator", &self.operator)
            .finish_non_exhaustive()
    }
}

pub(super) fn parse_targeting(value: &Value) -> Result<Vec<PersonPredicate>, ParseError> {
    let targeting = object(value, "targeting")?;
    closed(targeting, TARGETING_FIELDS, "targeting")?;
    let properties = required(targeting, "properties")?
        .as_array()
        .ok_or(ParseError::Malformed("properties"))?;
    if properties.len() > MAX_PREDICATES {
        return Err(ParseError::LimitExceeded("properties"));
    }
    properties.iter().map(PersonPredicate::parse).collect()
}

impl PersonPredicate {
    fn parse(value: &Value) -> Result<Self, ParseError> {
        let property = object(value, "property")?;
        closed(property, PROPERTY_FIELDS, "property")?;
        match string(property, "type")? {
            "person" => {}
            "cohort" | "group" | "flag" => return Err(ParseError::Unsupported("property.type")),
            _ => return Err(ParseError::Malformed("property.type")),
        }
        let key = string(property, "key")?;
        if key.is_empty() {
            return Err(ParseError::Malformed("property.key"));
        }
        let operator = match property.get("operator") {
            None | Some(Value::Null) => OperatorType::Exact,
            Some(value) => {
                let operator: OperatorType = serde_json::from_value(value.clone())
                    .map_err(|_| ParseError::Malformed("property.operator"))?;
                // The legacy enum accepts aliases and cohort-only operators.
                if serde_json::to_value(operator).ok().as_ref() != Some(value)
                    || matches!(
                        operator,
                        OperatorType::Between
                            | OperatorType::NotBetween
                            | OperatorType::In
                            | OperatorType::NotIn
                            | OperatorType::FlagEvaluatesTo
                    )
                {
                    return Err(ParseError::Malformed("property.operator"));
                }
                operator
            }
        };
        if property
            .get("group_type_index")
            .is_some_and(|v| !v.is_null())
        {
            return Err(ParseError::Malformed("property.group_type_index"));
        }
        let negation = match property.get("negation") {
            None | Some(Value::Null) => false,
            Some(Value::Bool(value)) => *value,
            _ => return Err(ParseError::Malformed("property.negation")),
        };
        for field in ["cohort_name", "label"] {
            if property
                .get(field)
                .is_some_and(|v| !v.is_null() && !v.is_string())
            {
                return Err(ParseError::Malformed("property.presentation"));
            }
        }
        if let Some(names) = property.get("group_key_names").filter(|v| !v.is_null()) {
            if !names
                .as_object()
                .is_some_and(|names| names.values().all(Value::is_string))
            {
                return Err(ParseError::Malformed("property.group_key_names"));
            }
        }
        let value = property.get("value").filter(|value| !value.is_null());
        validate_value(operator, value)?;
        // An invalid pattern is a deferred evaluation error, not a parse error.
        let compiled_regex =
            matches!(operator, OperatorType::Regex | OperatorType::NotRegex).then(|| {
                value
                    .and_then(Value::as_str)
                    .map_or(CompiledRegex::InvalidPattern, CompiledRegex::new)
            });
        Ok(Self {
            key: key.to_owned(),
            value: value.cloned(),
            operator,
            negation,
            compiled_regex,
        })
    }

    pub(super) fn estimated_heap_bytes(&self) -> usize {
        self.key.capacity()
            + self.value.as_ref().map_or(0, estimate_json_heap_size)
            + if matches!(self.compiled_regex, Some(CompiledRegex::Compiled(_))) {
                ESTIMATED_COMPILED_REGEX_BYTES
            } else {
                0
            }
    }
}

fn validate_value(operator: OperatorType, value: Option<&Value>) -> Result<(), ParseError> {
    use OperatorType::{
        Between, EndsWith, Exact, FlagEvaluatesTo, Gt, Gte, Icontains, IcontainsMulti, In,
        IsDateAfter, IsDateBefore, IsDateExact, IsNot, IsNotSet, IsSet, Lt, Lte, NotBetween,
        NotEndsWith, NotIcontains, NotIcontainsMulti, NotIn, NotRegex, NotStartsWith, Regex,
        SemverCaret, SemverEq, SemverGt, SemverGte, SemverLt, SemverLte, SemverNeq, SemverTilde,
        SemverWildcard, StartsWith,
    };
    let valid = match operator {
        Regex | NotRegex | Icontains | NotIcontains | StartsWith | NotStartsWith | EndsWith
        | NotEndsWith => value.is_some_and(Value::is_string),
        Gt | Gte | Lt | Lte => {
            value.is_some_and(|v| v.is_string() || v.as_f64().is_some_and(f64::is_finite))
        }
        IcontainsMulti | NotIcontainsMulti => value.is_some_and(Value::is_array),
        SemverGt | SemverGte | SemverLt | SemverLte | SemverEq | SemverNeq | SemverTilde
        | SemverCaret | SemverWildcard => value.and_then(Value::as_str).is_some_and(|s| {
            // The writer requires numeric components before the prerelease suffix;
            // the evaluator's broader version normalization cannot replace that check.
            let s = if operator == SemverWildcard {
                s.trim_end_matches(['.', '*'])
            } else {
                s
            };
            s.split('-')
                .next()
                .unwrap_or_default()
                .split('.')
                .take(3)
                .all(|part| part.trim().parse::<u64>().is_ok())
                && to_semver_representation(&Value::String(s.to_owned())).is_some()
        }),
        IsDateExact | IsDateAfter | IsDateBefore => {
            value.and_then(Value::as_str).is_some_and(|s| {
                dateparser::parse(s).is_ok() || parse_relative_date_parts(s).is_some()
            })
        }
        Exact | IsNot | IsSet | IsNotSet => true,
        Between | NotBetween | In | NotIn | FlagEvaluatesTo => false,
    };
    if valid {
        Ok(())
    } else {
        Err(ParseError::Malformed("property.value"))
    }
}
