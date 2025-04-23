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
    // TODO: Probably need a default for value?
    // incase operators like is_set, is_not_set are used
    // not guaranteed to have a value, if say created via api
    pub value: Option<serde_json::Value>,
    pub operator: Option<OperatorType>,
    #[serde(rename = "type")]
    // TODO: worth making a enum here to differentiate between cohort and person filters?
    pub prop_type: String,
    pub negation: Option<bool>,
    pub group_type_index: Option<i32>,
}
