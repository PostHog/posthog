use std::borrow::Cow;
use std::collections::HashMap;

use crate::properties::property_models::{
    CompiledRegex, OperatorType, PropertyFilter, PropertyType,
};
use crate::properties::relative_date;
use chrono::{DateTime, NaiveDate, NaiveDateTime, Utc};
use chrono_tz::Tz;
use dateparser::parse as parse_date;
use fancy_regex::RegexBuilder;
use semver::{Version, VersionReq};
use serde_json::Value;

/// Regex backtrack limit to prevent ReDoS attacks.
/// 10k steps completes in ~1ms worst case, which is acceptable for a hot path.
pub(crate) const REGEX_BACKTRACK_LIMIT: usize = 10_000;

/// Prefix used when storing PersonMetadata field values (e.g. created_at) in the
/// person properties map. Avoids collision with user-set properties of the same name.
const PERSON_METADATA_KEY_PREFIX: &str = "__posthog_person_metadata__";

/// Top-level persons-table columns exposed as PersonMetadata filters. Must stay in sync
/// with `PERSON_METADATA_FIELDS` in `posthog/hogql/property.py` (the source of truth) and
/// with the injection match arm in `flag_matching_utils::apply_person_cohort_to_state`.
pub const PERSON_METADATA_FIELDS: &[&str] = &["created_at"];

/// Build the lookup key for a PersonMetadata field (e.g. created_at).
pub fn person_metadata_key(field: &str) -> String {
    format!("{}{}", PERSON_METADATA_KEY_PREFIX, field)
}

/// Resolve the lookup key for a property filter, applying the PersonMetadata prefix when
/// the filter targets a top-level persons-table column rather than the properties JSON.
///
/// Returns `Cow::Borrowed` for the common case (Person/Group/Event/Cohort/Flag) so the hot
/// `match_property` path doesn't allocate; only PersonMetadata filters allocate the prefixed key.
pub fn lookup_key_for(filter: &PropertyFilter) -> Cow<'_, str> {
    if filter.prop_type == PropertyType::PersonMetadata {
        Cow::Owned(person_metadata_key(&filter.key))
    } else {
        Cow::Borrowed(&filter.key)
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum FlagMatchingError {
    ValidationError(String),
    MissingProperty(String),
    InconclusiveOperatorMatch,
    InvalidRegexPattern,
}

pub fn to_string_representation(value: &Value) -> String {
    if value.is_string() {
        return value
            .as_str()
            .expect("string slice should always exist for string value")
            .to_string();
    }
    value.to_string()
}

pub fn to_f64_representation(value: &Value) -> Option<f64> {
    if value.is_number() {
        return value.as_f64();
    }
    to_string_representation(value).parse::<f64>().ok()
}

/// Strip 'v' prefix if present (e.g., "v1.2.3" -> "1.2.3")
fn normalize_version_string(version: &str) -> &str {
    version.strip_prefix('v').unwrap_or(version).trim()
}

/// Canonicalize a version string into strict `MAJOR.MINOR.PATCH` semver so the `semver`
/// crate can parse the shapes mobile SDKs actually emit. The crate rejects a missing patch
/// component and any leading zeros, so real versions like "3.10", "3.08", and "2.48" would
/// otherwise fail to parse and make version-gated flag conditions silently never match.
///
/// Two adjustments are made to the numeric core only, leaving any pre-release/build suffix
/// (e.g. "-alpha.1", "+build.7") untouched:
/// - pad a missing minor/patch component with 0 ("3" -> "3.0.0", "3.10" -> "3.10.0")
/// - strip leading zeros from numeric identifiers ("3.08" -> "3.8", "0" stays "0")
///
/// Non-numeric components are left as-is so genuinely invalid versions still fail to parse.
///
/// Note: this is intentionally more permissive than `STRICT_SEMVER_REGEX` in
/// `posthog/hogql/property.py`, which gates the ClickHouse `sortableSemver` path used for
/// insights/cohort analytics. Flag evaluation here cleanly returns `false` on a parse
/// failure (no ClickHouse array-ordering pitfall), so accepting these formats only turns
/// silent non-matches into correct matches.
fn canonicalize_version_string(version: &str) -> String {
    // Split off any pre-release ("-") or build ("+") suffix; the numeric core precedes it.
    let (core, suffix) = match version.find(|c: char| c == '-' || c == '+') {
        Some(idx) => version.split_at(idx),
        None => (version, ""),
    };

    let mut components: Vec<&str> = core
        .split('.')
        .map(|part| {
            if !part.is_empty() && part.bytes().all(|b| b.is_ascii_digit()) {
                let trimmed = part.trim_start_matches('0');
                if trimmed.is_empty() {
                    "0"
                } else {
                    trimmed
                }
            } else {
                part
            }
        })
        .collect();

    // Pad two-component versions ("3.10" -> "3.10.0") so strict semver parsing succeeds.
    while components.len() < 3 {
        components.push("0");
    }

    format!("{}{}", components.join("."), suffix)
}

pub fn to_semver_representation(value: &Value) -> Option<Version> {
    let version_string = to_string_representation(value);
    let normalized = normalize_version_string(&version_string);
    let canonical = canonicalize_version_string(normalized);
    // TODO: Build metadata (e.g., "1.0.0+build.1") is not currently supported because
    // our `sortableSemver` method in ClickHouse/HogQL doesn't support it yet.
    // For semver equality checks, use regular string equality operators instead.
    Version::parse(&canonical).ok()
}

pub fn match_property(
    property: &PropertyFilter,
    matching_property_values: &HashMap<String, Value>,
    partial_props: bool,
    team_timezone: Tz,
) -> Result<bool, FlagMatchingError> {
    let lookup_key = lookup_key_for(property);
    let key: &str = lookup_key.as_ref();

    // only looks for matches where key exists in override_property_values
    // doesn't support operator is_not_set with partial_props
    if partial_props && !matching_property_values.contains_key(key) {
        tracing::warn!("Missing property for matching: {}", property.key);
        return Err(FlagMatchingError::MissingProperty(format!(
            "can't match properties without a value. Missing property: {}",
            property.key
        )));
    }

    let operator = property.operator.unwrap_or(OperatorType::Exact);
    let match_value = matching_property_values.get(key);

    // first match operators that don't require a value
    match operator {
        OperatorType::IsSet => return Ok(matching_property_values.contains_key(key)),
        OperatorType::IsNotSet => {
            return if partial_props {
                if matching_property_values.contains_key(key) {
                    Ok(false)
                } else {
                    Err(FlagMatchingError::InconclusiveOperatorMatch)
                }
            } else {
                Ok(!matching_property_values.contains_key(key))
            }
        }
        _ => {}
    }

    // For all other operators, we need a value
    let value = match &property.value {
        Some(v) => v,
        None => return Ok(false), // No value means no match for value-requiring operators
    };

    match operator {
        OperatorType::Exact | OperatorType::IsNot => {
            let compute_exact_match = |value: &Value, override_value: &Value| -> bool {
                if is_truthy_or_falsy_property_value(value) {
                    // Do boolean handling, such that passing in "true" or "True" or "false" or "False" as matching value is equivalent
                    let (truthy_value, truthy_override_value) = (
                        is_truthy_property_value(value),
                        is_truthy_property_value(override_value),
                    );
                    return truthy_override_value.to_string().to_lowercase()
                        == truthy_value.to_string().to_lowercase();
                }

                if value.is_array() {
                    let target = to_string_representation(override_value).to_lowercase();
                    return value
                        .as_array()
                        .expect("expected array value")
                        .iter()
                        .any(|v| to_string_representation(v).to_lowercase() == target);
                }
                to_string_representation(value).to_lowercase()
                    == to_string_representation(override_value).to_lowercase()
            };

            if let Some(match_value) = match_value {
                if operator == OperatorType::Exact {
                    Ok(compute_exact_match(value, match_value))
                } else {
                    Ok(!compute_exact_match(value, match_value))
                }
            } else {
                // When value doesn't exist:
                // - for Exact: it's not a match (false)
                // - for IsNot: it is a match (true)
                Ok(operator == OperatorType::IsNot)
            }
        }
        // IsSet and IsNotSet are handled early (lines 69-83) and return before reaching this match
        OperatorType::IsSet | OperatorType::IsNotSet => {
            unreachable!("IsSet/IsNotSet operators are handled earlier in the function")
        }
        OperatorType::Icontains | OperatorType::NotIcontains => {
            if let Some(match_value) = match_value {
                // Using to_ascii_lowercase() since we only care about ASCII case insensitivity
                // This is more performant than to_lowercase() which handles full Unicode
                let is_contained = to_string_representation(match_value)
                    .to_ascii_lowercase()
                    .contains(&to_string_representation(value).to_ascii_lowercase());

                if operator == OperatorType::Icontains {
                    Ok(is_contained)
                } else {
                    Ok(!is_contained)
                }
            } else {
                // When value doesn't exist:
                // - for Icontains: it's not a match (false)
                // - for NotIcontains: it is a match (true)
                Ok(operator == OperatorType::NotIcontains)
            }
        }
        OperatorType::IcontainsMulti | OperatorType::NotIcontainsMulti => {
            if let Some(match_value) = match_value {
                let match_string = to_string_representation(match_value).to_ascii_lowercase();

                // Check if any of the search values is contained in the match value.
                // Handle both single values and arrays without materializing an
                // intermediate Vec — short-circuits the per-element lowercase work too.
                let any_contained = match value {
                    Value::Array(arr) => arr.iter().any(|v| {
                        match_string.contains(&to_string_representation(v).to_ascii_lowercase())
                    }),
                    single_value => match_string
                        .contains(&to_string_representation(single_value).to_ascii_lowercase()),
                };

                if operator == OperatorType::IcontainsMulti {
                    Ok(any_contained)
                } else {
                    Ok(!any_contained)
                }
            } else {
                // When value doesn't exist:
                // - for IcontainsMulti: it's not a match (false)
                // - for NotIcontainsMulti: it is a match (true)
                Ok(operator == OperatorType::NotIcontainsMulti)
            }
        }
        OperatorType::Regex | OperatorType::NotRegex => {
            if match_value.is_none() {
                // When value doesn't exist:
                // - for Regex: it's not a match (false)
                // - for NotRegex: it is a match (true)
                return Ok(operator == OperatorType::NotRegex);
            }

            // Three-state dispatch:
            // - Some(Compiled): use the pre-compiled regex (fast path)
            // - Some(InvalidPattern): pattern was already known-bad, short-circuit
            // - None: prepare_regex() was not called, compile on-the-fly (fallback
            //   for cohort property filters and test code)
            let compiled;
            let regex: &fancy_regex::Regex = match &property.compiled_regex {
                Some(CompiledRegex::Compiled(regex)) => regex,
                Some(CompiledRegex::InvalidPattern) => return Ok(false),
                None => match RegexBuilder::new(&to_string_representation(value))
                    .backtrack_limit(REGEX_BACKTRACK_LIMIT)
                    .build()
                {
                    Ok(regex) => {
                        compiled = regex;
                        &compiled
                    }
                    Err(_) => return Ok(false),
                },
            };

            let haystack = to_string_representation(match_value.unwrap_or(&Value::Null));
            let match_ = regex
                .find(&haystack)
                .map_err(|_| FlagMatchingError::InvalidRegexPattern)?;

            if operator == OperatorType::Regex {
                Ok(match_.is_some())
            } else {
                Ok(match_.is_none())
            }
        }
        OperatorType::Gt | OperatorType::Gte | OperatorType::Lt | OperatorType::Lte => {
            if match_value.is_none() {
                // When value doesn't exist:
                // - for Gt/Gte/Lt/Lte: it's not a match (false)
                return Ok(false);
            }
            // TODO: Move towards only numeric matching of these operators???

            let compare = |lhs: f64, rhs: f64, operator: OperatorType| -> bool {
                match operator {
                    OperatorType::Gt => lhs > rhs,
                    OperatorType::Gte => lhs >= rhs,
                    OperatorType::Lt => lhs < rhs,
                    OperatorType::Lte => lhs <= rhs,
                    _ => false,
                }
            };

            let parsed_value = match to_f64_representation(
                match_value.unwrap_or(&serde_json::Value::Null),
            ) {
                Some(parsed_value) => parsed_value,
                None => {
                    tracing::debug!(
                        "Failed to parse property value '{}' for key '{}' as number for operator {:?}",
                        match_value.unwrap_or(&serde_json::Value::Null),
                        key,
                        operator
                    );
                    return Err(FlagMatchingError::ValidationError(
                        "value is not a number".to_string(),
                    ));
                }
            };

            if let Some(filter_value) = to_f64_representation(value) {
                Ok(compare(parsed_value, filter_value, operator))
            } else {
                tracing::debug!(
                    "Failed to parse filter value '{}' for key '{}' as number for operator {:?}",
                    value,
                    key,
                    operator
                );
                Err(FlagMatchingError::ValidationError(
                    "filter value is not a number".to_string(),
                ))
            }
        }
        OperatorType::SemverGt
        | OperatorType::SemverGte
        | OperatorType::SemverLt
        | OperatorType::SemverLte
        | OperatorType::SemverEq
        | OperatorType::SemverNeq => {
            if match_value.is_none() {
                return Ok(false);
            }

            let compare = |lhs: &Version, rhs: &Version, operator: OperatorType| -> bool {
                match operator {
                    OperatorType::SemverGt => lhs > rhs,
                    OperatorType::SemverGte => lhs >= rhs,
                    OperatorType::SemverLt => lhs < rhs,
                    OperatorType::SemverLte => lhs <= rhs,
                    // NB: Build metadata comparison is not currently supported (see to_semver_representation).
                    OperatorType::SemverEq => lhs == rhs,
                    OperatorType::SemverNeq => lhs != rhs,
                    _ => false,
                }
            };

            let parsed_value = match to_semver_representation(
                match_value.unwrap_or(&serde_json::Value::Null),
            ) {
                Some(parsed_value) => parsed_value,
                None => {
                    tracing::debug!(
                        "Failed to parse property value '{}' for key '{}' as semver for operator {:?}",
                        match_value.unwrap_or(&serde_json::Value::Null),
                        key,
                        operator
                    );
                    return Ok(false);
                }
            };

            if let Some(filter_value) = to_semver_representation(value) {
                Ok(compare(&parsed_value, &filter_value, operator))
            } else {
                tracing::debug!(
                    "Failed to parse filter value '{}' for key '{}' as semver for operator {:?}",
                    value,
                    key,
                    operator
                );
                Err(FlagMatchingError::ValidationError(
                    "filter value is not a valid semver".to_string(),
                ))
            }
        }
        OperatorType::SemverTilde | OperatorType::SemverCaret | OperatorType::SemverWildcard => {
            if match_value.is_none() {
                return Ok(false);
            }

            // Parse the property value as a version
            let parsed_value = match to_semver_representation(
                match_value.unwrap_or(&serde_json::Value::Null),
            ) {
                Some(parsed_value) => parsed_value,
                None => {
                    tracing::debug!(
                        "Failed to parse property value '{}' for key '{}' as semver for operator {:?}",
                        match_value.unwrap_or(&serde_json::Value::Null),
                        key,
                        operator
                    );
                    return Ok(false);
                }
            };

            // Build the version requirement string based on the operator
            let version_string = to_string_representation(value);
            let normalized_version = normalize_version_string(&version_string);

            let requirement_string = match operator {
                OperatorType::SemverTilde => {
                    format!("~{}", canonicalize_version_string(normalized_version))
                }
                OperatorType::SemverCaret => {
                    format!("^{}", canonicalize_version_string(normalized_version))
                }
                OperatorType::SemverWildcard => {
                    // For wildcard, replace * with x for semver compatibility.
                    // Supported patterns: "1.*", "1.2.*", "1.*.*", "*"
                    //
                    // Python uses rstrip(".*") then calculates bounds manually:
                    //   "1.2.*" -> "1.2" -> >=1.2.0 <1.3.0
                    //   "1.*.*" -> "1"   -> >=1.0.0 <2.0.0
                    // Rust uses VersionReq with x wildcards:
                    //   "1.2.*" -> "1.2.x" -> >=1.2.0 <1.3.0
                    //   "1.*.*" -> "1.x.x" -> >=1.0.0 <2.0.0
                    // Both produce equivalent results for valid patterns.
                    //
                    // Invalid patterns like "1.*.3" will fail VersionReq parsing and
                    // return a ValidationError, which is the expected behavior.
                    normalized_version.replace('*', "x")
                }
                _ => normalized_version.to_string(),
            };

            // Parse the version requirement
            let requirement = match VersionReq::parse(&requirement_string) {
                Ok(req) => req,
                Err(_) => {
                    tracing::debug!(
                        "Failed to parse version requirement '{}' for key '{}' as semver requirement for operator {:?}",
                        requirement_string,
                        key,
                        operator
                    );
                    return Err(FlagMatchingError::ValidationError(
                        "filter value is not a valid semver requirement".to_string(),
                    ));
                }
            };

            // Check if the parsed value matches the requirement
            Ok(requirement.matches(&parsed_value))
        }
        OperatorType::IsDateExact | OperatorType::IsDateAfter | OperatorType::IsDateBefore => {
            // Both the person value and the filter value are interpreted in the
            // team timezone (naive strings) or by their explicit offset, so the two
            // sides agree with each other and with HogQL/ClickHouse cohort evaluation.
            let parsed_date =
                determine_parsed_date_for_property_matching(match_value, team_timezone);

            if parsed_date.is_none() {
                // When value doesn't exist:
                // - for IsDateExact/IsDateAfter/IsDateBefore: it's not a match (false)
                return Ok(false);
            }

            if let Some(override_value) = value.as_str() {
                let override_date = match parse_date_string_in_tz(override_value, team_timezone) {
                    Some(date) => date,
                    None => {
                        return Ok(false);
                    }
                };

                match operator {
                    OperatorType::IsDateBefore => Ok(parsed_date.unwrap() < override_date),
                    OperatorType::IsDateAfter => Ok(parsed_date.unwrap() > override_date),
                    OperatorType::IsDateExact => Ok(parsed_date.unwrap() == override_date),
                    _ => Ok(false),
                }
            } else {
                Ok(false)
            }
        }
        // NB: In/NotIn operators are only for Cohorts,
        // and should be handled by cohort matching code because
        // by the time we match properties, we've already decomposed the cohort
        // filter into multiple property filters
        OperatorType::In | OperatorType::NotIn => Err(FlagMatchingError::ValidationError(
            "In/NotIn operators should be handled by cohort matching".to_string(),
        )),
        OperatorType::FlagEvaluatesTo => Err(FlagMatchingError::ValidationError(
            "FlagEvaluatesTo operator should be handled by flag dependency matching".to_string(),
        )),
    }
}

fn is_truthy_or_falsy_property_value(value: &Value) -> bool {
    if value.is_boolean() {
        return true;
    }

    if value.is_string() {
        let parsed_value = value
            .as_str()
            .expect("expected string value")
            .to_lowercase();
        return parsed_value == "true" || parsed_value == "false";
    }

    if value.is_array() {
        return value
            .as_array()
            .expect("expected array value")
            .iter()
            .all(is_truthy_or_falsy_property_value);
    }

    false
}

fn is_truthy_property_value(value: &Value) -> bool {
    if value.is_boolean() {
        return value.as_bool().expect("expected boolean value");
    }

    if value.is_string() {
        let parsed_value = value
            .as_str()
            .expect("expected string value")
            .to_lowercase();
        return parsed_value == "true";
    }

    if value.is_array() {
        return value
            .as_array()
            .expect("expected array value")
            .iter()
            .all(is_truthy_property_value);
    }

    false
}

/// Naive wall-clock datetime formats (no embedded offset). A match here means the
/// value is interpreted in the team timezone. `%.f` is optional in chrono, so these
/// also cover the no-fractional-seconds case; both the space and `T` separators are
/// listed because chrono does not treat them as interchangeable.
const NAIVE_DATETIME_FORMATS: &[&str] = &[
    "%Y-%m-%d %H:%M:%S%.f",
    "%Y-%m-%dT%H:%M:%S%.f",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
];

/// Parses a datetime string, interpreting naive wall-clock values in
/// `team_timezone` and honoring explicit offsets as written.
///
/// Both sides of an IS_DATE_* comparison flow through here so they agree with
/// each other and with HogQL/ClickHouse cohort evaluation. HogQL wraps both the
/// stored value and the filter constant in `…(value, <team_tz>)`, so a naive
/// string like "2024-06-01" means midnight in the team timezone — not UTC.
/// Values that carry an explicit offset (a trailing `Z` or `±HH:MM`) are honored
/// as written, mirroring ClickHouse's `parseDateTime64BestEffort`, which respects
/// the embedded offset regardless of the team timezone.
fn parse_date_string_in_tz(date_str: &str, team_timezone: Tz) -> Option<DateTime<Utc>> {
    // Relative dates ("-7d", "-30d", …) are anchored to "now" in the team timezone.
    if let Some(date) = relative_date::parse_relative_date_in_tz(date_str, team_timezone) {
        return Some(date);
    }

    // Explicit-offset formats carry their own timezone; honor it as-is.
    if let Ok(date) = DateTime::parse_from_rfc3339(date_str) {
        return Some(date.with_timezone(&Utc));
    }

    // Bare date ("2024-06-01") is the common filter form — check it first, then the
    // forms that include a time component. All are interpreted in the team timezone.
    if let Ok(date) = NaiveDate::parse_from_str(date_str, "%Y-%m-%d") {
        return relative_date::naive_to_utc_in_tz(date.and_hms_opt(0, 0, 0)?, team_timezone);
    }
    for fmt in NAIVE_DATETIME_FORMATS {
        if let Ok(naive) = NaiveDateTime::parse_from_str(date_str, fmt) {
            return relative_date::naive_to_utc_in_tz(naive, team_timezone);
        }
    }

    // Fallback for any exotic format the explicit list misses; assumes UTC for
    // naive input — preferable to failing the match outright.
    parse_date(date_str).ok()
}

fn determine_parsed_date_for_property_matching(
    value: Option<&Value>,
    team_timezone: Tz,
) -> Option<DateTime<Utc>> {
    let value = value?;

    if let Some(date_str) = value.as_str() {
        // First try parsing as a float timestamp (an unambiguous epoch instant).
        if let Ok(num) = date_str.parse::<f64>() {
            return parse_float_timestamp(num);
        }
        // Otherwise interpret the string in the team timezone, like the filter side.
        return parse_date_string_in_tz(date_str, team_timezone);
    }

    if let Some(num) = value.as_number() {
        // Unix timestamps are the number of seconds since epoch (January 1, 1970, at 00:00:00 UTC)
        let seconds_f = num.as_f64()?;
        return parse_float_timestamp(seconds_f);
    }

    None
}

fn parse_float_timestamp(value: f64) -> Option<DateTime<Utc>> {
    let whole_seconds = value.floor() as i64;
    let nanos = ((value % 1.0) * 1_000_000_000.0).round() as u32;
    DateTime::from_timestamp(whole_seconds, nanos)
}

/// Copy of https://github.com/PostHog/posthog/blob/master/posthog/queries/test/test_base.py#L35
/// with some modifications to match Rust's behavior
/// and to test the match_property function
#[cfg(test)]
mod test_match_properties {
    use crate::properties::property_models::PropertyType;

    use super::*;
    use chrono::{Datelike, Timelike};
    use serde_json::json;
    use test_case::test_case;

    /// UTC-defaulting wrapper so timezone-agnostic tests stay terse. Date-specific
    /// tests call `super::match_property` directly with the team timezone they need.
    fn match_property(
        property: &PropertyFilter,
        matching_property_values: &HashMap<String, Value>,
        partial_props: bool,
    ) -> Result<bool, FlagMatchingError> {
        super::match_property(property, matching_property_values, partial_props, Tz::UTC)
    }

    #[test]
    fn test_match_properties_exact_with_partial_props() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("value")),
            operator: None,
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value2"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(""))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            true
        )
        .is_err());
        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key2".to_string(), json!("value"))]),
                true
            )
            .expect_err("expected match to exist"),
            FlagMatchingError::MissingProperty(
                "can't match properties without a value. Missing property: key".to_string()
            )
        );
        assert!(match_property(&property_a, &HashMap::from([]), true).is_err());

        let property_b = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("value")),
            operator: Some(OperatorType::Exact),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("value"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("value2"))]),
            true
        )
        .expect("expected match to exist"));

        let property_c = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(["value1", "value2", "value3"])),
            operator: Some(OperatorType::Exact),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value1"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value2"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value3"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value4"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_c,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            true
        )
        .is_err());
    }

    #[rstest::rstest]
    #[case("us", true)]
    #[case("Us", true)]
    #[case("US", true)]
    #[case("ca", true)]
    #[case("uk", true)]
    #[case("UK", true)]
    #[case("de", false)]
    fn test_match_properties_exact_array_is_case_insensitive(
        #[case] user_value: &str,
        #[case] expected: bool,
    ) {
        // Array Exact comparisons lowercase both sides, so a mixed-case filter
        // value must still match a lowercase user property and vice-versa.
        let property = PropertyFilter {
            key: "country".to_string(),
            value: Some(json!(["US", "CA", "Uk"])),
            operator: Some(OperatorType::Exact),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        let actual = match_property(
            &property,
            &HashMap::from([("country".to_string(), json!(user_value))]),
            true,
        )
        .expect("expected match to exist");

        assert_eq!(actual, expected, "user_value = {user_value}");
    }

    #[test]
    fn test_match_properties_exact_empty_array_never_matches() {
        let property = PropertyFilter {
            key: "country".to_string(),
            value: Some(json!([])),
            operator: Some(OperatorType::Exact),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };
        assert!(!match_property(
            &property,
            &HashMap::from([("country".to_string(), json!("us"))]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_match_properties_is_not() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("value")),
            operator: Some(OperatorType::IsNot),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value2"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(""))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));

        // partial mode returns error when key doesn't exist
        assert!(match_property(
            &property_a,
            &HashMap::from([("key2".to_string(), json!("value1"))]),
            true
        )
        .is_err());

        let property_c = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(["value1", "value2", "value3"])),
            operator: Some(OperatorType::IsNot),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value4"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value5"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value6"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!(""))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value2"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value3"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value1"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_c,
            &HashMap::from([("key2".to_string(), json!("value1"))]),
            true
        )
        .is_err());
    }

    #[test]
    fn test_match_properties_is_set() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("value")),
            operator: Some(OperatorType::IsSet),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value2"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(""))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key2".to_string(), json!("value1"))]),
            true
        )
        .is_err());

        assert!(match_property(&property_a, &HashMap::from([]), true).is_err());
    }

    #[test]
    fn test_match_properties_icontains() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("valUe")),
            operator: Some(OperatorType::Icontains),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value2"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value3"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("vaLue4"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("343tfvalue5"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("Alakazam"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(123))]),
            true
        )
        .expect("expected match to exist"));

        let property_b = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("3")),
            operator: Some(OperatorType::Icontains),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("3"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!(323))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("val3"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("three"))]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_match_properties_regex() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(r"\.com$")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value.com"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value2.com"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(".com343tfvalue5"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("Alakazam"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(123))]),
            true
        )
        .expect("expected match to exist"));

        let property_b = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("3")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };
        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("3"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!(323))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("val3"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("three"))]),
            true
        )
        .expect("expected match to exist"));

        // invalid regex
        let property_c = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(r"?*")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value2"))]),
            true
        )
        .expect("expected match to exist"));

        // non string value
        let property_d = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(4)),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };
        assert!(match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!("4"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!(4))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!("value"))]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_match_properties_math_operators() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(1)),
            operator: Some(OperatorType::Gt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(2))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(3))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(0))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(-1))]),
            true
        )
        .expect("expected match to exist"));

        // # we handle type mismatches so this should be true
        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("23"))]),
            true
        )
        .expect("expected match to exist"));

        let property_b = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(1)),
            operator: Some(OperatorType::Lt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!(0))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!(-1))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!(-3))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!(1))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("1"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("3"))]),
            true
        )
        .expect("expected match to exist"));

        let property_c = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(1)),
            operator: Some(OperatorType::Gte),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!(1))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!(2))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!(0))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!(-1))]),
            true
        )
        .expect("expected match to exist"));
        // # now we handle type mismatches so this should be true
        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("3"))]),
            true
        )
        .expect("expected match to exist"));

        let property_d = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("43")),
            operator: Some(OperatorType::Lt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!("41"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!("42"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!(42))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!("43"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!("44"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!(44))]),
            true
        )
        .expect("expected match to exist"));

        let property_e = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("30")),
            operator: Some(OperatorType::Lt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_e,
            &HashMap::from([("key".to_string(), json!("29"))]),
            true
        )
        .expect("expected match to exist"));

        // # depending on the type of override, we adjust type comparison
        // This is wonky, do we want to continue this behavior? :/
        // TODO: Come back to this
        // TODO: Fix
        // assert_eq!(
        //     match_property(
        //         &property_e,
        //         &HashMap::from([("key".to_string(), json!("100"))]),
        //         true
        //     )
        //     .expect("expected match to exist"),
        //     true
        // );
        assert!(!match_property(
            &property_e,
            &HashMap::from([("key".to_string(), json!(100))]),
            true
        )
        .expect("expected match to exist"));

        // let property_f = PropertyFilter {
        //     key: "key".to_string(),
        //     value: json!("123aloha"),
        //     operator: Some(OperatorType::Gt),
        //     prop_type: "person".to_string(),
        //     group_type_index: None,
        // };

        // TODO: This test fails because 123aloha is not a number
        // and currently we don't support string comparison..
        // assert_eq!(
        //     match_property(
        //         &property_f,
        //         &HashMap::from([("key".to_string(), json!("123"))]),
        //         true
        //     )
        //     .expect("expected match to exist"),
        //     false
        // );
        // assert_eq!(
        //     match_property(
        //         &property_f,
        //         &HashMap::from([("key".to_string(), json!(122))]),
        //         true
        //     )
        //     .expect("expected match to exist"),
        //     false
        // );

        // # this turns into a string comparison
        // TODO: Fix
        // assert_eq!(
        //     match_property(
        //         &property_f,
        //         &HashMap::from([("key".to_string(), json!(129))]),
        //         true
        //     )
        //     .expect("expected match to exist"),
        //     true
        // );
    }

    #[test]
    fn test_none_property_value_with_all_operators() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("null")),
            operator: Some(OperatorType::IsNot),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("non"))]),
            true
        )
        .expect("expected match to exist"));

        let property_b = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(null)),
            operator: Some(OperatorType::IsSet),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));

        let property_c = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("nu")),
            operator: Some(OperatorType::Icontains),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("smh"))]),
            true
        )
        .expect("expected match to exist"));

        let property_d = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("Nu")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(!match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));

        let property_d_upper_case = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("Nu")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(!match_property(
            &property_d_upper_case,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));

        // TODO: Fails because not a number
        // let property_e = PropertyFilter {
        //     key: "key".to_string(),
        //     value: json!(1),
        //     operator: Some(OperatorType::Gt),
        //     prop_type: "person".to_string(),
        //     group_type_index: None,
        // };

        // assert_eq!(
        //     match_property(&property_e, &HashMap::from([("key".to_string(), json!(null))]), true)
        //         .expect("expected match to exist"),
        //     true
        // );
    }

    #[test]
    fn test_match_properties_all_operators_with_full_props() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("value")),
            operator: None,
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(!match_property(
            &property_a,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            false
        )
        .expect("Expected no errors with full props mode for non-existent keys"));
        assert_eq!(
            match_property(&property_a, &HashMap::from([]), false),
            Ok(false)
        );

        let property_exact = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(["value1", "value2", "value3"])),
            operator: Some(OperatorType::Exact),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(!match_property(
            &property_exact,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_is_set = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("value")),
            operator: Some(OperatorType::IsSet),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(!match_property(
            &property_is_set,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_is_not_set = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(null)),
            operator: Some(OperatorType::IsNotSet),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_is_not_set,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            false
        )
        .expect("Expected no errors with full props mode"));
        assert!(!match_property(
            &property_is_not_set,
            &HashMap::from([("key".to_string(), json!("value"))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        // is not set with partial props returns false when key exists
        assert!(!match_property(
            &property_is_not_set,
            &HashMap::from([("key".to_string(), json!("value"))]),
            true
        )
        .expect("Expected no errors with full props mode"));
        // is not set returns error when key doesn't exist
        assert!(match_property(
            &property_is_not_set,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            true
        )
        .is_err());

        let property_icontains = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("valUe")),
            operator: Some(OperatorType::Icontains),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(!match_property(
            &property_icontains,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_not_icontains = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("valUe")),
            operator: Some(OperatorType::NotIcontains),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_not_icontains,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_regex = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(r"\.com$")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(!match_property(
            &property_regex,
            &HashMap::from([("key2".to_string(), json!("value.com"))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_not_regex = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(r"\.com$")),
            operator: Some(OperatorType::NotRegex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_not_regex,
            &HashMap::from([("key2".to_string(), json!("value.com"))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_gt = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(1)),
            operator: Some(OperatorType::Gt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(!match_property(
            &property_gt,
            &HashMap::from([("key2".to_string(), json!(2))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_gte = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(1)),
            operator: Some(OperatorType::Gte),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(!match_property(
            &property_gte,
            &HashMap::from([("key2".to_string(), json!(2))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_lt = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(1)),
            operator: Some(OperatorType::Lt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(!match_property(
            &property_lt,
            &HashMap::from([("key2".to_string(), json!(0))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_lte = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(1)),
            operator: Some(OperatorType::Lte),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(!match_property(
            &property_lte,
            &HashMap::from([("key2".to_string(), json!(0))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        // TODO: Handle date operators
        let property_is_date_before = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("2021-01-01")),
            operator: Some(OperatorType::IsDateBefore),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(!match_property(
            &property_is_date_before,
            &HashMap::from([("key2".to_string(), json!("2021-01-02"))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        // Test IsDateAfter with different date formats
        let property_is_date_after = PropertyFilter {
            key: "joined_at".to_string(),
            value: Some(json!("2023-06-04")), // Simple date format in filter
            operator: Some(OperatorType::IsDateAfter),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Test with ISO8601 format in person properties
        assert!(match_property(
            &property_is_date_after,
            &HashMap::from([(
                "joined_at".to_string(),
                json!("2025-01-24T23:20:24.865148+00:00")
            )]),
            true
        )
        .expect("expected match to exist"));

        // Test with a date before the filter date (should not match)
        assert!(!match_property(
            &property_is_date_after,
            &HashMap::from([(
                "joined_at".to_string(),
                json!("2023-01-24T23:20:24.865148+00:00")
            )]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_match_properties_exact_date() {
        let exact_date = "2024-03-21T00:00:00Z"; // Define the exact date we want to test
        let property_exact = PropertyFilter {
            key: "date".to_string(),
            value: Some(json!(exact_date)),
            operator: Some(OperatorType::IsDateExact),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_exact,
            &HashMap::from([("date".to_string(), json!(exact_date))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_exact,
            &HashMap::from([("date".to_string(), json!("2024-03-22T00:00:00Z"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_exact,
            &HashMap::from([("date".to_string(), json!(1710979200))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_exact,
            &HashMap::from([("date".to_string(), json!("1710979200"))]),
            true
        )
        .expect("expected match to exist"));

        // Test with invalid date format
        assert!(!match_property(
            &property_exact,
            &HashMap::from([("date".to_string(), json!("invalid-date"))]),
            true
        )
        .expect("expected match to exist"));

        // Test with timestamp
        assert!(match_property(
            &property_exact,
            &HashMap::from([("date".to_string(), json!(1710979200.0))]), // 2024-03-21 00:00:00 UTC
            true
        )
        .expect("expected match to exist"));
    }

    #[test_case(json!(1836277747) => true; "numeric timestamp after target date")] // 2028-03-10 05:09:07
    #[test_case(json!("1836277747") => true; "string timestamp after target date")] // 2028-03-10 05:09:07
    #[test_case(json!(1747793088) => false; "numeric timestamp before target date")] // 2025-05-21 02:04:48
    #[test_case(json!("1747793088") => false; "string timestamp before target date")] // 2025-05-21 02:04:48
    fn test_match_properties_date_after_with_timestamp(input_value: Value) -> bool {
        let target_date = "2027-03-21T00:00:00Z";
        let property = PropertyFilter {
            key: "date".to_string(),
            value: Some(json!(target_date)),
            operator: Some(OperatorType::IsDateAfter),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        match_property(
            &property,
            &HashMap::from([("date".to_string(), input_value)]),
            true,
        )
        .expect("expected match to exist")
    }

    #[test]
    fn test_match_properties_relative_date() {
        let property_relative = PropertyFilter {
            key: "joined_at".to_string(),
            value: Some(json!("-3d")),
            operator: Some(OperatorType::IsDateBefore),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Get current time and 3 days ago
        let now = chrono::Utc::now();
        let four_days_ago = now - chrono::Duration::days(4);
        let two_days_ago = now - chrono::Duration::days(2);

        // Test with date 4 days ago (should match)
        assert!(match_property(
            &property_relative,
            &HashMap::from([("joined_at".to_string(), json!(four_days_ago.to_rfc3339()))]),
            true
        )
        .expect("expected match to exist"));

        // Test with date 2 days ago (should not match)
        assert!(!match_property(
            &property_relative,
            &HashMap::from([("joined_at".to_string(), json!(two_days_ago.to_rfc3339()))]),
            true
        )
        .expect("expected match to exist"));

        // Test with timestamp format
        assert!(match_property(
            &property_relative,
            &HashMap::from([(
                "joined_at".to_string(),
                json!(four_days_ago.timestamp() as f64)
            )]),
            true
        )
        .expect("expected match to exist"));

        // Test with invalid date
        assert!(!match_property(
            &property_relative,
            &HashMap::from([("joined_at".to_string(), json!("invalid-date"))]),
            true
        )
        .expect("expected match to exist"));

        // Test with null value
        assert!(!match_property(
            &property_relative,
            &HashMap::from([("joined_at".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));

        // Test with missing property
        assert!(match_property(&property_relative, &HashMap::from([]), true).is_err());
    }

    #[test]
    fn test_parse_timestamp_in_seconds_as_date() {
        let expected_date = DateTime::parse_from_rfc3339("2028-03-10T05:09:07Z")
            .unwrap()
            .with_timezone(&Utc);
        let timestamp_number = 1836277747;
        let timestamp_string = timestamp_number.to_string();
        let date =
            determine_parsed_date_for_property_matching(Some(&json!(timestamp_number)), Tz::UTC);
        assert_eq!(date, Some(expected_date));
        let date =
            determine_parsed_date_for_property_matching(Some(&json!(timestamp_string)), Tz::UTC);
        assert_eq!(date, Some(expected_date));
    }

    #[test]
    fn test_parse_timestamp_with_fractional_milliseconds_as_date() {
        let expected_date = DateTime::parse_from_rfc3339("2028-03-10T05:09:07.867530107Z")
            .unwrap()
            .with_timezone(&Utc);
        let timestamp_number = 1836277747.86753;
        let date =
            determine_parsed_date_for_property_matching(Some(&json!(timestamp_number)), Tz::UTC);
        assert_eq!(date, Some(expected_date));

        let timestamp_string = "1836277747.86753";
        let date =
            determine_parsed_date_for_property_matching(Some(&json!(timestamp_string)), Tz::UTC);
        assert_eq!(date, Some(expected_date));
    }

    #[test]
    fn test_parse_iso8601_with_milliseconds_no_timezone() {
        // Test parsing ISO 8601 format with milliseconds but no timezone. A naive
        // value like this is interpreted in the team timezone; this test passes
        // Tz::UTC, so the result lands at UTC midnight.
        let date_string = "2025-12-19T00:00:00.000";
        let date = parse_date_string_in_tz(date_string, Tz::UTC);
        assert!(
            date.is_some(),
            "Should be able to parse ISO 8601 with milliseconds"
        );

        let parsed_date = date.unwrap();
        assert_eq!(parsed_date.year(), 2025);
        assert_eq!(parsed_date.month(), 12);
        assert_eq!(parsed_date.day(), 19);
        assert_eq!(parsed_date.hour(), 0);
        assert_eq!(parsed_date.minute(), 0);
        assert_eq!(parsed_date.second(), 0);
    }

    #[test]
    fn test_parse_iso8601_with_variable_millisecond_precision() {
        // Test 1 digit milliseconds
        assert!(parse_date_string_in_tz("2025-12-19T00:00:00.5", Tz::UTC).is_some());

        // Test 2 digit milliseconds
        assert!(parse_date_string_in_tz("2025-12-19T00:00:00.12", Tz::UTC).is_some());

        // Test 3 digit milliseconds (existing case)
        assert!(parse_date_string_in_tz("2025-12-19T00:00:00.123", Tz::UTC).is_some());
    }

    #[test]
    fn test_match_properties_semver_operators() {
        // Test SemverGt
        let property_gt = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.0.0")),
            operator: Some(OperatorType::SemverGt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_gt,
            &HashMap::from([("version".to_string(), json!("1.0.1"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_gt,
            &HashMap::from([("version".to_string(), json!("2.0.0"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_gt,
            &HashMap::from([("version".to_string(), json!("1.0.0"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_gt,
            &HashMap::from([("version".to_string(), json!("0.9.9"))]),
            true
        )
        .expect("expected match to exist"));

        // Test minimal version 0.0.0
        let property_minimal = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("0.0.0")),
            operator: Some(OperatorType::SemverGte),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_minimal,
            &HashMap::from([("version".to_string(), json!("0.0.0"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_minimal,
            &HashMap::from([("version".to_string(), json!("0.0.1"))]),
            true
        )
        .expect("expected match to exist"));

        // Test SemverGte
        let property_gte = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.0.0")),
            operator: Some(OperatorType::SemverGte),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_gte,
            &HashMap::from([("version".to_string(), json!("1.0.0"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_gte,
            &HashMap::from([("version".to_string(), json!("1.0.1"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_gte,
            &HashMap::from([("version".to_string(), json!("0.9.9"))]),
            true
        )
        .expect("expected match to exist"));

        // Test SemverLt
        let property_lt = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("2.0.0")),
            operator: Some(OperatorType::SemverLt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_lt,
            &HashMap::from([("version".to_string(), json!("1.9.9"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_lt,
            &HashMap::from([("version".to_string(), json!("1.0.0"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_lt,
            &HashMap::from([("version".to_string(), json!("2.0.0"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_lt,
            &HashMap::from([("version".to_string(), json!("2.0.1"))]),
            true
        )
        .expect("expected match to exist"));

        // Test SemverLte
        let property_lte = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("2.0.0")),
            operator: Some(OperatorType::SemverLte),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_lte,
            &HashMap::from([("version".to_string(), json!("2.0.0"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_lte,
            &HashMap::from([("version".to_string(), json!("1.9.9"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_lte,
            &HashMap::from([("version".to_string(), json!("2.0.1"))]),
            true
        )
        .expect("expected match to exist"));

        // Test SemverEq
        let property_eq = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.2.3")),
            operator: Some(OperatorType::SemverEq),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_eq,
            &HashMap::from([("version".to_string(), json!("1.2.3"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_eq,
            &HashMap::from([("version".to_string(), json!("1.2.4"))]),
            true
        )
        .expect("expected match to exist"));

        // Test SemverNeq
        let property_neq = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.2.3")),
            operator: Some(OperatorType::SemverNeq),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_neq,
            &HashMap::from([("version".to_string(), json!("1.2.4"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_neq,
            &HashMap::from([("version".to_string(), json!("1.2.3"))]),
            true
        )
        .expect("expected match to exist"));

        // Note: Build metadata is not supported because our `sortableSemver` method doesn't support it yet.
    }

    #[test]
    fn test_semver_with_v_prefix() {
        let property = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.0.0")),
            operator: Some(OperatorType::SemverGt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Test with 'v' prefix in property value
        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("v1.0.1"))]),
            true
        )
        .expect("expected match to exist"));

        // Test with 'v' prefix in filter value
        let property_with_v = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("v1.0.0")),
            operator: Some(OperatorType::SemverGt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_with_v,
            &HashMap::from([("version".to_string(), json!("1.0.1"))]),
            true
        )
        .expect("expected match to exist"));

        // Test with 'v' prefix on both sides
        assert!(match_property(
            &property_with_v,
            &HashMap::from([("version".to_string(), json!("v1.0.1"))]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_semver_with_prerelease() {
        let property = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.0.0")),
            operator: Some(OperatorType::SemverGt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Pre-release versions are less than the release version
        assert!(!match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.0.0-alpha.1"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.0.1-beta.2"))]),
            true
        )
        .expect("expected match to exist"));

        // Test pre-release comparison
        let property_pre = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.0.0-alpha.1")),
            operator: Some(OperatorType::SemverLt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_pre,
            &HashMap::from([("version".to_string(), json!("1.0.0-alpha.0"))]),
            true
        )
        .expect("expected match to exist"));
    }

    // TODO: Build metadata in semver (e.g., "1.0.0+build.1") is not currently supported.
    // For semver equality checks, use regular string equality operators (Exact, IsNot) instead.
    // See to_semver_representation() for details.

    #[test]
    fn test_semver_invalid_versions() {
        let property = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.0.0")),
            operator: Some(OperatorType::SemverGt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Invalid semver in property value should return false
        assert!(!match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("not-a-version"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.2.abc"))]),
            true
        )
        .expect("expected match to exist"));

        // Leading/trailing whitespace is trimmed and accepted
        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!(" 1.2.3"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.2.3 "))]),
            true
        )
        .expect("expected match to exist"));

        // Zero-padded components are canonicalized ("01.02.03" -> "1.2.3"), which many
        // mobile SDKs emit. 1.2.3 > 1.0.0, so this matches.
        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("01.02.03"))]),
            true
        )
        .expect("expected match to exist"));

        // A leading zero in a single component is canonicalized too ("3.07" -> "3.7.0").
        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("3.07"))]),
            true
        )
        .expect("expected match to exist"));

        // Two-part versions get a padded patch component ("3.7" -> "3.7.0"), the common
        // shape mobile SDKs emit. 3.7.0 > 1.0.0, so this matches.
        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("3.7"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("3.0"))]),
            true
        )
        .expect("expected match to exist"));

        // Too many version components (common in .NET)
        assert!(!match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.2.3.4"))]),
            true
        )
        .expect("expected match to exist"));

        // Empty component
        assert!(!match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1..2.3"))]),
            true
        )
        .expect("expected match to exist"));

        // Trailing dot
        assert!(!match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.2.3."))]),
            true
        )
        .expect("expected match to exist"));

        // Leading dot
        assert!(!match_property(
            &property,
            &HashMap::from([("version".to_string(), json!(".1.2.3"))]),
            true
        )
        .expect("expected match to exist"));

        // Negative version part
        assert!(!match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.-2.3"))]),
            true
        )
        .expect("expected match to exist"));

        // Invalid semver in filter value should return an error (configuration error)
        let property_invalid_filter = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("invalid-semver")),
            operator: Some(OperatorType::SemverGt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_invalid_filter,
            &HashMap::from([("version".to_string(), json!("1.0.0"))]),
            true
        )
        .is_err());

        // Invalid semver in filter value for range operators should also return an error
        let property_invalid_tilde = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("not-a-version")),
            operator: Some(OperatorType::SemverTilde),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_invalid_tilde,
            &HashMap::from([("version".to_string(), json!("1.0.0"))]),
            true
        )
        .is_err());

        let property_invalid_wildcard = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.*.3")), // Invalid: wildcard in middle
            operator: Some(OperatorType::SemverWildcard),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_invalid_wildcard,
            &HashMap::from([("version".to_string(), json!("1.2.3"))]),
            true
        )
        .is_err());
    }

    #[test]
    fn test_semver_mobile_version_formats() {
        // Mobile SDKs commonly emit two-component versions ("3.10") and zero-padded
        // components ("3.08"), neither of which is strict semver. Before canonicalization
        // these silently failed to parse, so version-gated flag conditions never matched.

        // "3.08+" is the reported enterprise case: property "3.08" (-> 3.8.0) satisfies
        // a SemverGte "3.08" (-> 3.8.0) condition.
        let gte_308 = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("3.08")),
            operator: Some(OperatorType::SemverGte),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        for version in ["3.08", "3.8", "3.8.0", "3.9", "3.10", "4.0.0"] {
            assert!(
                match_property(
                    &gte_308,
                    &HashMap::from([("version".to_string(), json!(version))]),
                    true
                )
                .expect("expected match to exist"),
                "expected {version} to satisfy SemverGte 3.08"
            );
        }

        for version in ["3.07", "3.7", "2.48", "3.0"] {
            assert!(
                !match_property(
                    &gte_308,
                    &HashMap::from([("version".to_string(), json!(version))]),
                    true
                )
                .expect("expected match to exist"),
                "expected {version} to not satisfy SemverGte 3.08"
            );
        }

        // Two-component ordering: 3.10 (-> 3.10.0) is greater than 3.9 (-> 3.9.0), not a
        // string comparison where "3.10" < "3.9".
        let gt_39 = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("3.9")),
            operator: Some(OperatorType::SemverGt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &gt_39,
            &HashMap::from([("version".to_string(), json!("3.10"))]),
            true
        )
        .expect("expected match to exist"));

        // Canonicalization also applies to the filter value in tilde/caret ranges.
        let tilde_308 = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("3.08")),
            operator: Some(OperatorType::SemverTilde),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // ~3.08 (-> ~3.8.0) means >=3.8.0 <3.9.0
        assert!(match_property(
            &tilde_308,
            &HashMap::from([("version".to_string(), json!("3.8.5"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &tilde_308,
            &HashMap::from([("version".to_string(), json!("3.9.0"))]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_semver_missing_property() {
        let property = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.0.0")),
            operator: Some(OperatorType::SemverGt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Missing property should return false
        assert!(!match_property(
            &property,
            &HashMap::from([("other_key".to_string(), json!("1.0.0"))]),
            false
        )
        .expect("expected match to exist"));

        // Missing property with partial_props should error
        assert!(match_property(
            &property,
            &HashMap::from([("other_key".to_string(), json!("1.0.0"))]),
            true
        )
        .is_err());
    }

    #[test]
    fn test_semver_tilde_operator() {
        // ~1.2.3 means >=1.2.3 <1.3.0 (allows patch-level changes)
        let property = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.2.3")),
            operator: Some(OperatorType::SemverTilde),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Should match: same version
        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.2.3"))]),
            true
        )
        .expect("expected match to exist"));

        // Should match: higher patch version
        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.2.4"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.2.10"))]),
            true
        )
        .expect("expected match to exist"));

        // Should not match: higher minor version
        assert!(!match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.3.0"))]),
            true
        )
        .expect("expected match to exist"));

        // Should not match: lower version
        assert!(!match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.2.2"))]),
            true
        )
        .expect("expected match to exist"));

        // Should not match: different major version
        assert!(!match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("2.2.3"))]),
            true
        )
        .expect("expected match to exist"));

        // Test with v prefix
        let property_with_v = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("v1.2.3")),
            operator: Some(OperatorType::SemverTilde),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_with_v,
            &HashMap::from([("version".to_string(), json!("v1.2.5"))]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_semver_caret_operator() {
        // ^1.2.3 means >=1.2.3 <2.0.0 (allows minor-level changes)
        let property = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.2.3")),
            operator: Some(OperatorType::SemverCaret),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Should match: same version
        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.2.3"))]),
            true
        )
        .expect("expected match to exist"));

        // Should match: higher patch version
        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.2.4"))]),
            true
        )
        .expect("expected match to exist"));

        // Should match: higher minor version
        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.3.0"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.10.5"))]),
            true
        )
        .expect("expected match to exist"));

        // Should not match: different major version
        assert!(!match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("2.0.0"))]),
            true
        )
        .expect("expected match to exist"));

        // Should not match: lower version
        assert!(!match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.2.2"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.1.9"))]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_semver_wildcard_operator() {
        // 1.2.* means >=1.2.0 <1.3.0
        let property_patch = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.2.*")),
            operator: Some(OperatorType::SemverWildcard),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Should match: any patch version in 1.2.x
        assert!(match_property(
            &property_patch,
            &HashMap::from([("version".to_string(), json!("1.2.0"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_patch,
            &HashMap::from([("version".to_string(), json!("1.2.5"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_patch,
            &HashMap::from([("version".to_string(), json!("1.2.99"))]),
            true
        )
        .expect("expected match to exist"));

        // Should not match: different minor version
        assert!(!match_property(
            &property_patch,
            &HashMap::from([("version".to_string(), json!("1.3.0"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_patch,
            &HashMap::from([("version".to_string(), json!("1.1.9"))]),
            true
        )
        .expect("expected match to exist"));

        // Test 1.*.* which means >=1.0.0 <2.0.0
        let property_minor = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.*.*")),
            operator: Some(OperatorType::SemverWildcard),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Should match: any version in 1.x.x
        assert!(match_property(
            &property_minor,
            &HashMap::from([("version".to_string(), json!("1.0.0"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_minor,
            &HashMap::from([("version".to_string(), json!("1.5.9"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_minor,
            &HashMap::from([("version".to_string(), json!("1.99.99"))]),
            true
        )
        .expect("expected match to exist"));

        // Should not match: different major version
        assert!(!match_property(
            &property_minor,
            &HashMap::from([("version".to_string(), json!("2.0.0"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_minor,
            &HashMap::from([("version".to_string(), json!("0.9.9"))]),
            true
        )
        .expect("expected match to exist"));

        // Test 1.* (single wildcard, should work same as 1.*.*)
        let property_single = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.*")),
            operator: Some(OperatorType::SemverWildcard),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_single,
            &HashMap::from([("version".to_string(), json!("1.5.0"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_single,
            &HashMap::from([("version".to_string(), json!("2.0.0"))]),
            true
        )
        .expect("expected match to exist"));

        // Test * (all versions)
        let property_all = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("*")),
            operator: Some(OperatorType::SemverWildcard),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_all,
            &HashMap::from([("version".to_string(), json!("1.0.0"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_all,
            &HashMap::from([("version".to_string(), json!("99.99.99"))]),
            true
        )
        .expect("expected match to exist"));

        // Test invalid pattern: 1.*.3 (wildcard in middle) - should return error
        let property_invalid = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.*.3")),
            operator: Some(OperatorType::SemverWildcard),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Invalid patterns return an error (configuration error)
        assert!(match_property(
            &property_invalid,
            &HashMap::from([("version".to_string(), json!("1.2.3"))]),
            true
        )
        .is_err());
    }

    #[test]
    fn test_semver_range_with_prerelease() {
        // Tilde with pre-release versions
        let property = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.2.3-beta.1")),
            operator: Some(OperatorType::SemverTilde),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Should match higher pre-release in same patch version
        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.2.3-beta.2"))]),
            true
        )
        .expect("expected match to exist"));

        // Should match release version
        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.2.3"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("1.2.4"))]),
            true
        )
        .expect("expected match to exist"));

        // Caret with pre-release
        let property_caret = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.2.0-alpha")),
            operator: Some(OperatorType::SemverCaret),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_caret,
            &HashMap::from([("version".to_string(), json!("1.2.0"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_caret,
            &HashMap::from([("version".to_string(), json!("1.5.0"))]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_semver_range_invalid_versions() {
        let property = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("1.2.3")),
            operator: Some(OperatorType::SemverTilde),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Invalid version in property value should return false
        assert!(!match_property(
            &property,
            &HashMap::from([("version".to_string(), json!("not-a-version"))]),
            true
        )
        .expect("expected match to exist"));

        // Invalid version in filter value should return an error (configuration error)
        let property_invalid = PropertyFilter {
            key: "version".to_string(),
            value: Some(json!("invalid")),
            operator: Some(OperatorType::SemverCaret),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_invalid,
            &HashMap::from([("version".to_string(), json!("1.0.0"))]),
            true
        )
        .is_err());
    }

    #[test]
    fn test_match_properties_regex_with_lookahead() {
        // Positive lookahead: match "foo" only if followed by "bar"
        let property_positive = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(r"foo(?=bar)")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_positive,
            &HashMap::from([("key".to_string(), json!("foobar"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_positive,
            &HashMap::from([("key".to_string(), json!("foobar123"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_positive,
            &HashMap::from([("key".to_string(), json!("foobaz"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_positive,
            &HashMap::from([("key".to_string(), json!("foo"))]),
            true
        )
        .expect("expected match to exist"));

        // Negative lookahead: match "foo" only if NOT followed by "bar"
        let property_negative = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(r"foo(?!bar)")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_negative,
            &HashMap::from([("key".to_string(), json!("foobaz"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_negative,
            &HashMap::from([("key".to_string(), json!("foo"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_negative,
            &HashMap::from([("key".to_string(), json!("foobar"))]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_match_properties_regex_with_lookbehind() {
        // Positive lookbehind: match "bar" only if preceded by "foo"
        let property_positive = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(r"(?<=foo)bar")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_positive,
            &HashMap::from([("key".to_string(), json!("foobar"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_positive,
            &HashMap::from([("key".to_string(), json!("123foobar456"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_positive,
            &HashMap::from([("key".to_string(), json!("bazbar"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_positive,
            &HashMap::from([("key".to_string(), json!("bar"))]),
            true
        )
        .expect("expected match to exist"));

        // Negative lookbehind: match "bar" only if NOT preceded by "foo"
        let property_negative = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(r"(?<!foo)bar")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_negative,
            &HashMap::from([("key".to_string(), json!("bazbar"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_negative,
            &HashMap::from([("key".to_string(), json!("bar"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_negative,
            &HashMap::from([("key".to_string(), json!("foobar"))]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_match_properties_regex_with_backreference() {
        // Backreference: match repeated words like "the the" or "is is"
        let property = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(r"\b(\w+)\s+\1\b")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property,
            &HashMap::from([("key".to_string(), json!("the the"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property,
            &HashMap::from([("key".to_string(), json!("this is is a test"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property,
            &HashMap::from([("key".to_string(), json!("the quick brown fox"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property,
            &HashMap::from([("key".to_string(), json!("hello world"))]),
            true
        )
        .expect("expected match to exist"));

        // Another backreference: match HTML-like tags where opening and closing match
        let property_tags = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(r"<(\w+)>.*</\1>")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property_tags,
            &HashMap::from([("key".to_string(), json!("<div>content</div>"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_tags,
            &HashMap::from([("key".to_string(), json!("<span>text</span>"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_tags,
            &HashMap::from([("key".to_string(), json!("<div>content</span>"))]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_match_properties_regex_complex_patterns() {
        // Real-world example: match email addresses from specific domains using lookahead
        let property = PropertyFilter {
            key: "email".to_string(),
            value: Some(json!(r"^[\w.+-]+@(?=.*\.(com|org)$)[\w.-]+$")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &property,
            &HashMap::from([("email".to_string(), json!("user@example.com"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property,
            &HashMap::from([("email".to_string(), json!("test@posthog.org"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property,
            &HashMap::from([("email".to_string(), json!("user@example.net"))]),
            true
        )
        .expect("expected match to exist"));

        // Password validation: at least one uppercase, one lowercase, one digit
        let password_check = PropertyFilter {
            key: "password".to_string(),
            value: Some(json!(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        assert!(match_property(
            &password_check,
            &HashMap::from([("password".to_string(), json!("Password1"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &password_check,
            &HashMap::from([("password".to_string(), json!("SecurePass123"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &password_check,
            &HashMap::from([("password".to_string(), json!("password"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &password_check,
            &HashMap::from([("password".to_string(), json!("SHORT1"))]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_match_properties_regex_backtracking_limit() {
        // Test that pathological regex patterns complete quickly due to backtrack limits.
        // The backtrack limit only applies to patterns using "fancy" features (lookahead,
        // lookbehind, backreferences) since fancy-regex delegates simple patterns to the
        // standard regex crate which uses a non-backtracking DFA/NFA algorithm.
        //
        // This pattern uses a backreference which forces the backtracking engine,
        // combined with nested quantifiers that cause exponential backtracking.
        let property = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(r"^(a+)+\1$")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Should match when the string is repeated correctly
        assert!(match_property(
            &property,
            &HashMap::from([("key".to_string(), json!("aaaa"))]),
            true
        )
        .expect("expected match to exist"));

        // This causes exponential backtracking: the engine tries many ways to split
        // the 'a's between the group and the backreference, and with the nested
        // quantifier (a+)+, each split has many sub-combinations to try.
        let pathological_input = "a".repeat(30) + "!";
        let start = std::time::Instant::now();
        let result = match_property(
            &property,
            &HashMap::from([("key".to_string(), json!(pathological_input))]),
            true,
        );
        let elapsed = start.elapsed();

        // The key assertion: this should complete quickly (not hang)
        // With 10k backtrack limit, should complete in well under 100ms
        assert!(
            elapsed.as_millis() < 100,
            "Regex matching took too long: {:?}",
            elapsed
        );

        // Result should be an error due to backtracking limit being exceeded
        assert!(
            matches!(result, Err(FlagMatchingError::InvalidRegexPattern)),
            "Expected InvalidRegexPattern error due to backtrack limit, got {:?}",
            result
        );
    }

    #[test]
    fn test_match_properties_icontains_multi() {
        // Test icontains_multi with array of values
        let property_array = PropertyFilter {
            key: "email".to_string(),
            value: Some(json!(["@gmail.com", "@yahoo.com"])),
            operator: Some(OperatorType::IcontainsMulti),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Should match gmail
        assert!(match_property(
            &property_array,
            &HashMap::from([("email".to_string(), json!("user@gmail.com"))]),
            true
        )
        .expect("expected match to exist"));

        // Should match yahoo
        assert!(match_property(
            &property_array,
            &HashMap::from([("email".to_string(), json!("user@yahoo.com"))]),
            true
        )
        .expect("expected match to exist"));

        // Should not match hotmail
        assert!(!match_property(
            &property_array,
            &HashMap::from([("email".to_string(), json!("user@hotmail.com"))]),
            true
        )
        .expect("expected match to exist"));

        // Test icontains_multi with single value
        let property_single = PropertyFilter {
            key: "name".to_string(),
            value: Some(json!("john")),
            operator: Some(OperatorType::IcontainsMulti),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Should match case-insensitively
        assert!(match_property(
            &property_single,
            &HashMap::from([("name".to_string(), json!("John Doe"))]),
            true
        )
        .expect("expected match to exist"));

        // Should not match different name
        assert!(!match_property(
            &property_single,
            &HashMap::from([("name".to_string(), json!("Jane Doe"))]),
            true
        )
        .expect("expected match to exist"));

        // Should return error when key doesn't exist in partial mode
        assert!(match_property(
            &property_single,
            &HashMap::from([("other_key".to_string(), json!("value"))]),
            true
        )
        .is_err());
    }

    #[test]
    fn test_match_properties_not_icontains_multi() {
        // Test not_icontains_multi with array of values
        let property_array = PropertyFilter {
            key: "email".to_string(),
            value: Some(json!(["@gmail.com", "@yahoo.com"])),
            operator: Some(OperatorType::NotIcontainsMulti),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Should not match gmail (negated)
        assert!(!match_property(
            &property_array,
            &HashMap::from([("email".to_string(), json!("user@gmail.com"))]),
            true
        )
        .expect("expected match to exist"));

        // Should not match yahoo (negated)
        assert!(!match_property(
            &property_array,
            &HashMap::from([("email".to_string(), json!("user@yahoo.com"))]),
            true
        )
        .expect("expected match to exist"));

        // Should match hotmail (does not contain any of the blocked domains)
        assert!(match_property(
            &property_array,
            &HashMap::from([("email".to_string(), json!("user@hotmail.com"))]),
            true
        )
        .expect("expected match to exist"));

        // Test not_icontains_multi with single value
        let property_single = PropertyFilter {
            key: "name".to_string(),
            value: Some(json!("spam")),
            operator: Some(OperatorType::NotIcontainsMulti),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Should match when value doesn't contain spam
        assert!(match_property(
            &property_single,
            &HashMap::from([("name".to_string(), json!("John Doe"))]),
            true
        )
        .expect("expected match to exist"));

        // Should not match when value contains spam
        assert!(!match_property(
            &property_single,
            &HashMap::from([("name".to_string(), json!("Spam Email"))]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_match_properties_icontains_multi_empty_values() {
        // Test with empty array
        let property_empty = PropertyFilter {
            key: "test".to_string(),
            value: Some(json!([])),
            operator: Some(OperatorType::IcontainsMulti),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Empty array should not match anything
        assert!(!match_property(
            &property_empty,
            &HashMap::from([("test".to_string(), json!("any value"))]),
            true
        )
        .expect("expected match to exist"));

        // Test with missing key should default to false for icontains_multi
        assert!(!match_property(
            &property_empty,
            &HashMap::from([("other_key".to_string(), json!("value"))]),
            false // non-partial mode
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_match_properties_not_icontains_multi_empty_values() {
        // Test with empty array
        let property_empty = PropertyFilter {
            key: "test".to_string(),
            value: Some(json!([])),
            operator: Some(OperatorType::NotIcontainsMulti),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // Empty array should match everything (nothing to exclude)
        assert!(match_property(
            &property_empty,
            &HashMap::from([("test".to_string(), json!("any value"))]),
            true
        )
        .expect("expected match to exist"));

        // Test with missing key should default to true for not_icontains_multi
        assert!(match_property(
            &property_empty,
            &HashMap::from([("other_key".to_string(), json!("value"))]),
            false // non-partial mode
        )
        .expect("expected match to exist"));
    }

    // Timezone parity tests
    //
    // These prove the Rust matcher interprets a naive datetime filter (the
    // right-hand side) in the team timezone — exactly as HogQL/ClickHouse cohort
    // evaluation does. HogQL lowers a naive IS_DATE_* constant to
    // `toDateTime(value, <team_tz>)`, so for an `America/Los_Angeles` team the
    // filter "2024-06-01" means 2024-06-01 00:00 Pacific = 2024-06-01 07:00 UTC
    // (PDT, UTC-7 in June), not 2024-06-01 00:00 UTC.
    //
    // The person value (left-hand side) is supplied as an unambiguous UTC instant
    // (a `Z`-suffixed ISO string or an epoch), so both engines agree on it and the
    // only thing under test is the right-hand-side interpretation. Each case also
    // asserts the pre-fix UTC interpretation produced a different decision in the
    // offset window straddling local midnight.

    const PACIFIC: Tz = Tz::America__Los_Angeles;

    fn date_filter(value: &str, operator: OperatorType) -> PropertyFilter {
        PropertyFilter {
            key: "joined_at".to_string(),
            value: Some(json!(value)),
            operator: Some(operator),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        }
    }

    fn match_date(person_value: Value, filter: &PropertyFilter, tz: Tz) -> bool {
        super::match_property(
            filter,
            &HashMap::from([("joined_at".to_string(), person_value)]),
            true,
            tz,
        )
        .expect("expected match to exist")
    }

    #[test_case("2024-06-01T03:00:00Z", false; "person before pacific midnight does not match")]
    #[test_case("2024-06-01T08:00:00Z", true; "person after pacific midnight matches")]
    fn test_is_date_after_interpreted_in_team_tz(person_iso: &str, expected_pacific: bool) {
        // Filter "2024-06-01" after-midnight resolves to 07:00 UTC for a Pacific team.
        let filter = date_filter("2024-06-01", OperatorType::IsDateAfter);
        assert_eq!(
            match_date(json!(person_iso), &filter, PACIFIC),
            expected_pacific
        );

        // The same person value at 03:00 UTC sits inside the offset window: it is
        // "after" UTC midnight but "before" Pacific midnight, so the pre-fix UTC
        // interpretation disagrees with the team-tz one.
        if person_iso == "2024-06-01T03:00:00Z" {
            assert!(match_date(json!(person_iso), &filter, Tz::UTC));
            assert_ne!(
                match_date(json!(person_iso), &filter, PACIFIC),
                match_date(json!(person_iso), &filter, Tz::UTC)
            );
        }
    }

    #[test_case("2024-06-01T03:00:00Z", true; "person before pacific midnight is before")]
    #[test_case("2024-06-01T08:00:00Z", false; "person after pacific midnight is not before")]
    fn test_is_date_before_interpreted_in_team_tz(person_iso: &str, expected_pacific: bool) {
        let filter = date_filter("2024-06-01", OperatorType::IsDateBefore);
        assert_eq!(
            match_date(json!(person_iso), &filter, PACIFIC),
            expected_pacific
        );

        // Pre-fix UTC interpretation flips the decision inside the offset window.
        if person_iso == "2024-06-01T03:00:00Z" {
            assert!(!match_date(json!(person_iso), &filter, Tz::UTC));
        }
    }

    #[test]
    fn test_is_date_exact_interpreted_in_team_tz() {
        // "2024-06-01" == 2024-06-01 07:00 UTC for a Pacific team.
        let filter = date_filter("2024-06-01", OperatorType::IsDateExact);

        assert!(match_date(json!("2024-06-01T07:00:00Z"), &filter, PACIFIC));
        assert!(!match_date(json!("2024-06-01T00:00:00Z"), &filter, PACIFIC));

        // Under UTC the equality lands on 00:00Z instead — the opposite decision.
        assert!(match_date(json!("2024-06-01T00:00:00Z"), &filter, Tz::UTC));
        assert!(!match_date(json!("2024-06-01T07:00:00Z"), &filter, Tz::UTC));
    }

    #[test]
    fn test_is_date_after_with_explicit_offset_filter_ignores_team_tz() {
        // A filter value carrying an explicit offset is honored as written, so the
        // team timezone must not shift it. "2024-06-01T00:00:00Z" is 00:00 UTC
        // regardless of the team timezone.
        let filter = date_filter("2024-06-01T00:00:00Z", OperatorType::IsDateAfter);
        let person = json!("2024-06-01T03:00:00Z");
        assert!(match_date(person.clone(), &filter, PACIFIC));
        assert_eq!(
            match_date(person.clone(), &filter, PACIFIC),
            match_date(person, &filter, Tz::UTC)
        );
    }

    #[test]
    fn test_is_date_after_with_epoch_person_value() {
        // Epoch person values are unambiguous instants; only the naive filter is
        // reinterpreted. 1717225200 = 2024-06-01 07:00:00 UTC, exactly Pacific
        // midnight, so it is not strictly after the "2024-06-01" boundary.
        let filter = date_filter("2024-06-01", OperatorType::IsDateAfter);
        assert!(!match_date(json!(1717225200_i64), &filter, PACIFIC));
        // One second later is after the boundary.
        assert!(match_date(json!(1717225201_i64), &filter, PACIFIC));
    }

    #[test]
    fn test_relative_date_filter_evaluates_in_team_tz_without_panicking() {
        // Relative dates anchor to "now" in the team timezone. The exact instant
        // depends on wall-clock time, so use a comfortable margin: a person who
        // joined 30 days ago is "before -7d", one who joined now is not. This
        // exercises the non-UTC relative path end to end (the deterministic
        // team-tz anchoring is covered in relative_date.rs).
        //
        // Use a non-DST zone (Tokyo, UTC+9 year-round) so "now - 7d" can never land
        // in a spring-forward wall-clock gap. That keeps the test deterministic
        // every day of the year — no skip path that would silently drop coverage.
        const TOKYO: Tz = Tz::Asia__Tokyo;
        let filter = date_filter("-7d", OperatorType::IsDateBefore);

        let thirty_days_ago = (Utc::now() - chrono::Duration::days(30)).to_rfc3339();
        let now = Utc::now().to_rfc3339();
        assert!(match_date(json!(thirty_days_ago), &filter, TOKYO));
        assert!(!match_date(json!(now), &filter, TOKYO));
    }

    #[test]
    fn test_naive_person_value_interpreted_in_team_tz() {
        // A naive person value is also read in the team timezone (matching HogQL,
        // which wraps both sides in the team tz). Against a fixed absolute filter
        // this changes the decision: a naive person clock of 08:00 is 15:00 UTC in
        // Pacific (after the 14:00Z filter) but 08:00 UTC if misread as UTC (before
        // it). This is the half of the fix that keeps the person side consistent.
        let filter = date_filter("2024-06-01T14:00:00Z", OperatorType::IsDateAfter);
        let person = json!("2024-06-01 08:00:00"); // naive wall clock, no offset

        assert!(match_date(person.clone(), &filter, PACIFIC));
        assert!(!match_date(person, &filter, Tz::UTC));
    }

    #[test]
    fn test_naive_person_and_naive_filter_agree_across_timezones() {
        // When both the person value and the filter are naive, they receive the
        // same team-tz shift, so the comparison reduces to a wall-clock comparison
        // that lands the same way in every timezone — matching HogQL (which reads
        // both sides in team tz) and never diverging at the day boundary. This is
        // the case a filter-only fix would have regressed.
        let after = date_filter("2024-06-01", OperatorType::IsDateAfter);
        let before = date_filter("2024-06-01", OperatorType::IsDateBefore);
        let person = json!("2024-06-01 03:00:00"); // naive: 03:00 is after midnight

        assert!(match_date(person.clone(), &after, PACIFIC));
        assert!(!match_date(person.clone(), &before, PACIFIC));

        // Identical decision under UTC — both sides move together, so naive+naive
        // has no day-boundary divergence between the two engines.
        assert_eq!(
            match_date(person.clone(), &after, PACIFIC),
            match_date(person.clone(), &after, Tz::UTC)
        );
        assert_eq!(
            match_date(person.clone(), &before, PACIFIC),
            match_date(person, &before, Tz::UTC)
        );
    }

    #[test]
    fn test_match_property_person_metadata_uses_sentinel_key() {
        // PersonMetadata filters look up under a sentinel-prefixed key so they don't
        // collide with user-set properties of the same name.
        let filter = PropertyFilter {
            key: "created_at".to_string(),
            value: Some(json!("2024-01-01")),
            operator: Some(OperatorType::IsDateAfter),
            prop_type: PropertyType::PersonMetadata,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
            extra: Default::default(),
        };

        // A user-set "created_at" property must NOT satisfy a person_metadata filter:
        // the metadata field is intentionally segregated so user-set values can't
        // override the canonical persons-table value.
        let user_set_only = HashMap::from([(
            "created_at".to_string(),
            json!("2099-01-01"), // Far-future user-set value
        )]);
        assert!(match_property(&filter, &user_set_only, false).is_ok());
        assert!(!match_property(&filter, &user_set_only, false).expect("filter evaluated"));

        // The sentinel-prefixed key (which the matcher injects from Person.created_at)
        // is what actually resolves the filter.
        let metadata_only =
            HashMap::from([(person_metadata_key("created_at"), json!("2025-06-01"))]);
        assert!(match_property(&filter, &metadata_only, false).expect("filter evaluated"));
    }
}
