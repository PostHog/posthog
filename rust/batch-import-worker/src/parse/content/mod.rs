use std::sync::Arc;

use mixpanel::MixpanelContentConfig;
use serde::{Deserialize, Serialize};

use crate::cache::{GroupCache, IdentifyCache};

pub mod amplitude;
pub mod captured;
pub mod mixpanel;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum ContentType {
    Mixpanel(MixpanelContentConfig), // From a mixpanel export
    Amplitude,
    Captured, // Each json object structured as if it was going to be sent to the capture endpoint
}

// All /extra/ information needed to go from any input format to an InternallyCapturedEvent,
// e.g. team_id
#[derive(Debug, Clone)]
pub struct TransformContext {
    pub team_id: i32,
    pub token: String,
    pub job_id: uuid::Uuid,
    pub identify_cache: Arc<dyn IdentifyCache>,
    pub group_cache: Arc<dyn GroupCache>,
    pub import_events: bool,
    pub generate_identify_events: bool,
    pub generate_group_identify_events: bool,
}

/// Ids that ingestion refuses to merge on, compared case-insensitively.
/// Mirrors the illegal-id lists in `nodejs/src/common/persons/person-utils.ts`.
const ILLEGAL_DISTINCT_IDS: &[&str] = &[
    "anonymous",
    "guest",
    "distinctid",
    "distinct_id",
    "id",
    "not_authenticated",
    "email",
    "undefined",
    "true",
    "false",
    "[object object]",
    "nan",
    "none",
    "null",
    "0",
    "$posthog_cookieless",
];

/// Tokens that mark an id as a serialized missing value even with a prefix or
/// suffix, e.g. `member_null` or `user-undefined`.
const PLACEHOLDER_TOKENS: &[&str] = &["null", "undefined"];

/// Whether `id` is a placeholder rather than a real user identifier. Source
/// exports often write a missing value as text, and using it as a distinct id
/// merges every device behind it into one person.
pub fn is_placeholder_distinct_id(id: &str) -> bool {
    let trimmed = id.trim().trim_matches(|c| c == '"' || c == '\'');
    if trimmed.is_empty() {
        return true;
    }
    let lower = trimmed.to_lowercase();
    if ILLEGAL_DISTINCT_IDS.contains(&lower.as_str()) || lower.contains("[object object]") {
        return true;
    }
    lower
        .split(|c: char| !c.is_alphanumeric())
        .any(|token| PLACEHOLDER_TOKENS.contains(&token))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_placeholder_distinct_id() {
        for id in [
            "",
            "  ",
            "null",
            "NULL",
            "\"undefined\"",
            "member_null",
            "member_undefined",
            "user-null-1",
            "Undefined:42",
            "user_[object Object]",
            "anonymous",
            "0",
        ] {
            assert!(
                is_placeholder_distinct_id(id),
                "{id:?} should be a placeholder"
            );
        }
        for id in [
            "user123",
            "nullable_user",
            "annulled",
            "member_42",
            "jane@example.com",
            "00000000-0000-0000-0000-000000000001",
            "10",
        ] {
            assert!(
                !is_placeholder_distinct_id(id),
                "{id:?} should not be a placeholder"
            );
        }
    }
}
