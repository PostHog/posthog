use std::fmt;

use serde_json::Value;

use super::{closed, object, required, string, ParseError};
use crate::properties::property_matching::to_semver_representation;
use crate::properties::property_models::OperatorType;
use crate::utils::json_size::estimate_json_size;

#[derive(Clone)]
pub struct PersonPredicate {
    pub key: String,
    pub value: Option<Value>,
    pub operator: OperatorType,
    pub negation: bool,
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
    closed(targeting, &["properties"], "targeting")?;
    let properties = required(targeting, "properties")?
        .as_array()
        .ok_or(ParseError::Malformed("properties"))?;
    if properties.len() > 100 {
        return Err(ParseError::LimitExceeded("properties"));
    }
    properties.iter().map(PersonPredicate::parse).collect()
}

impl PersonPredicate {
    fn parse(value: &Value) -> Result<Self, ParseError> {
        let property = object(value, "property")?;
        closed(
            property,
            &[
                "key",
                "type",
                "value",
                "operator",
                "negation",
                "group_type_index",
                "cohort_name",
                "group_key_names",
                "label",
            ],
            "property",
        )?;
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
        Ok(Self {
            key: key.to_owned(),
            value: value.cloned(),
            operator,
            negation,
        })
    }

    pub(super) fn estimated_heap_bytes(&self) -> usize {
        self.key.capacity() + self.value.as_ref().map_or(0, estimate_json_size)
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
            let s = if operator == SemverWildcard {
                s.trim_end_matches(['.', '*'])
            } else {
                s
            };
            to_semver_representation(&Value::String(s.to_owned())).is_some()
        }),
        IsDateExact | IsDateAfter | IsDateBefore => value
            .and_then(Value::as_str)
            .is_some_and(|s| dateparser::parse(s).is_ok() || relative_date_shape(s)),
        Exact | IsNot | IsSet | IsNotSet => true,
        Between | NotBetween | In | NotIn | FlagEvaluatesTo => false,
    };
    if valid {
        Ok(())
    } else {
        Err(ParseError::Malformed("property.value"))
    }
}

fn relative_date_shape(value: &str) -> bool {
    let Some((unit, number)) = value.as_bytes().split_last() else {
        return false;
    };
    matches!(unit, b'h' | b'd' | b'w' | b'm' | b'y')
        && std::str::from_utf8(number).ok().is_some_and(|n| {
            let n = n.strip_prefix('-').unwrap_or(n);
            !n.is_empty()
                && n.bytes().all(|b| b.is_ascii_digit())
                && n.parse::<u32>().is_ok_and(|n| n < 10_000)
        })
}
