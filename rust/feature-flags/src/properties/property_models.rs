use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OperatorType {
    Exact,
    IsNot,
    Icontains,
    NotIcontains,
    Regex,
    NotRegex,
    Gt,
    Lt,
    Gte,
    Lte,
    IsSet,
    IsNotSet,
    IsDateExact,
    IsDateAfter,
    IsDateBefore,
    In,
    NotIn,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct PropertyFilter {
    pub key: String,
    // NB: if a property filter is of type is_set or is_not_set, the value isn't used, and if it's a filter made by the API, the value is None.
    pub value: Option<serde_json::Value>,
    pub operator: Option<OperatorType>,
    #[serde(rename = "type")]
    // TODO: worth making a enum here to differentiate between cohort and person filters?
    pub prop_type: String,
    pub negation: Option<bool>,
    pub group_type_index: Option<i32>,
}
