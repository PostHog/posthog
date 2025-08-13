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
    FlagEvaluatesTo,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PropertyType {
    #[serde(rename = "person")]
    Person,
    #[serde(rename = "cohort")]
    Cohort,
    #[serde(rename = "group")]
    Group,
    // A flag property is compared to another flag evaluation result
    #[serde(rename = "flag")]
    Flag,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct PropertyFilter {
    pub key: String,
    // NB: if a property filter is of type is_set or is_not_set, the value isn't used, and if it's a filter made by the API, the value is None.
    pub value: Option<serde_json::Value>,
    pub operator: Option<OperatorType>,
    #[serde(rename = "type")]
    pub prop_type: PropertyType,
    pub negation: Option<bool>,
    pub group_type_index: Option<i32>,
}
