use serde::{Deserialize, Serialize};

// Keep in sync with FEATURE_FLAG_SUPPORTED_OPERATORS in posthog/api/feature_flag.py
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OperatorType {
    Exact,
    IsNot,
    Icontains,
    NotIcontains,
    IcontainsMulti,
    NotIcontainsMulti,
    Regex,
    NotRegex,
    Gt,
    Lt,
    Gte,
    Lte,
    SemverGt,
    SemverGte,
    SemverLt,
    SemverLte,
    SemverEq,
    SemverNeq,
    SemverTilde,
    SemverCaret,
    SemverWildcard,
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

/// Pre-compiled regex state for Regex/NotRegex operators.
/// Populated by `prepare_regex()` at flag-load time.
/// Clone is cheap: fancy_regex::Regex uses Arc<Prog> internally.
#[derive(Clone)]
pub enum CompiledRegex {
    /// Pattern compiled successfully — use this for matching.
    Compiled(fancy_regex::Regex),
    /// Pattern failed to compile — always returns Ok(false), no re-compilation needed.
    InvalidPattern,
}

impl std::fmt::Debug for CompiledRegex {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Compiled(re) => write!(f, "CompiledRegex(/{}/)", re.as_str()),
            Self::InvalidPattern => write!(f, "CompiledRegex(invalid)"),
        }
    }
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
    /// Pre-compiled regex for Regex/NotRegex operators.
    /// `None` means `prepare_regex()` was not called (fallback to on-the-fly compilation).
    /// `Some(Compiled(_))` holds the pre-compiled regex.
    /// `Some(InvalidPattern)` means the pattern failed to compile — returns false immediately.
    #[serde(skip)]
    pub compiled_regex: Option<CompiledRegex>,
}
