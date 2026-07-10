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

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PropertyType {
    #[default]
    #[serde(rename = "person")]
    Person,
    // Top-level columns on the persons table (e.g. created_at), not the JSON properties blob.
    #[serde(rename = "person_metadata")]
    PersonMetadata,
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

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
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
    /// Captures unknown JSONB keys so they survive the cache round-trip unchanged.
    /// Without this, runtime annotations like `cohort_name` and `group_key_names`
    /// would be silently dropped on round-trip and the Python `verify_flags_cache`
    /// verifier would report spurious `FIELD_MISMATCH` against the Django JSONB
    /// passthrough. Only unknown-key passthrough is guaranteed here — absent-vs-null
    /// normalization for known optional fields is handled by the Python verifier's
    /// `_strip_null_values` helper.
    /// See plans/verify-flags-cache-loose-comparison.md.
    #[serde(flatten)]
    pub extra: serde_json::Map<String, serde_json::Value>,
}

#[cfg(test)]
#[allow(clippy::needless_update)]
mod mock_impls {
    use super::*;
    use crate::utils::mock::Mock;

    impl Mock for PropertyFilter {
        fn mock() -> Self {
            PropertyFilter {
                key: "test_prop".to_string(),
                value: Some(serde_json::json!("test_value")),
                operator: Some(OperatorType::Exact),
                ..Default::default()
            }
        }
    }
}
