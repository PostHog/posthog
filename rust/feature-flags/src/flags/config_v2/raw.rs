use serde_json::value::RawValue;
use std::collections::HashSet;

use super::{ParseError, MAX_CONFIG_BYTES};

// Raw tokens prevent binary64 rounding from making an overprecise value valid.
pub(super) fn decimal_places_at_most(number: &str, places: i64) -> bool {
    let (mantissa, exponent) = number.split_once(['e', 'E']).unwrap_or((number, "0"));
    let mantissa = mantissa.strip_prefix('-').unwrap_or(mantissa);
    let mut digits = mantissa.bytes().filter(|&b| b != b'.');
    let digit_count = digits.clone().count();
    if digit_count == 0 || digits.any(|b| !b.is_ascii_digit()) {
        return false;
    }
    let trailing_zeros = mantissa
        .bytes()
        .rev()
        .filter(|&b| b != b'.')
        .take_while(|&b| b == b'0')
        .count();
    if trailing_zeros == digit_count {
        return true;
    }
    let Ok(exponent) = exponent.parse::<i64>() else {
        return false;
    };
    let fraction = mantissa.split_once('.').map_or(0, |(_, f)| f.len()) as i64;
    fraction
        .saturating_sub(trailing_zeros as i64)
        .saturating_sub(exponent)
        <= places
}

enum Container {
    Object {
        keys: HashSet<String>,
        key: String,
        expects_key: bool,
        is_rule: bool,
    },
    Array {
        is_rule_list: bool,
    },
}

pub(crate) fn validate_raw_document(document: &RawValue) -> Result<(), ParseError> {
    // RawValue already checked JSON syntax. Inspect tokens before Value loses
    // duplicate keys or rounds nonzero numbers to zero.
    let max_config_bytes = *MAX_CONFIG_BYTES;
    let text = document.get();
    let bytes = text.as_bytes();
    let mut containers = Vec::new();
    let mut compact_bytes = 0;
    let mut index = 0;
    while index < bytes.len() {
        let start = index;
        match bytes[index] {
            b' ' | b'\t' | b'\n' | b'\r' => {
                index += 1;
                continue;
            }
            b'"' => {
                index += 1;
                while bytes[index] != b'"' {
                    if bytes[index] == b'\\' {
                        index += 1;
                    }
                    index += 1;
                }
                index += 1;
                if let Some(Container::Object {
                    keys,
                    key,
                    expects_key,
                    ..
                }) = containers.last_mut()
                {
                    if *expects_key {
                        *key = serde_json::from_str(&text[start..index])
                            .map_err(|_| ParseError::Malformed("filters"))?;
                        if !keys.insert(key.clone()) {
                            return Err(ParseError::Malformed("json_keys_unique"));
                        }
                        *expects_key = false;
                    }
                }
            }
            b'{' => {
                let is_rule = matches!(
                    containers.last(),
                    Some(Container::Array { is_rule_list: true })
                );
                containers.push(Container::Object {
                    keys: HashSet::new(),
                    key: String::new(),
                    expects_key: true,
                    is_rule,
                });
                index += 1;
            }
            b'[' => {
                let is_rule_list = containers.len() == 1
                    && matches!(containers.last(), Some(Container::Object { key, .. }) if key == "rules");
                containers.push(Container::Array { is_rule_list });
                index += 1;
            }
            b'}' | b']' => {
                containers.pop();
                index += 1;
            }
            b',' => {
                if let Some(Container::Object { expects_key, .. }) = containers.last_mut() {
                    *expects_key = true;
                }
                index += 1;
            }
            b'-' | b'0'..=b'9' => {
                while index < bytes.len()
                    && matches!(bytes[index], b'-' | b'+' | b'.' | b'e' | b'E' | b'0'..=b'9')
                {
                    index += 1;
                }
                let token = &text[start..index];
                let number = token
                    .parse::<f64>()
                    .map_err(|_| ParseError::Malformed("number_is_binary64"))?;
                let mantissa = token.split(['e', 'E']).next().unwrap();
                if !number.is_finite()
                    || (number == 0.0 && mantissa.bytes().any(|b| matches!(b, b'1'..=b'9')))
                {
                    return Err(ParseError::Malformed("number_is_binary64"));
                }
                if matches!(containers.last(), Some(Container::Object { key, is_rule: true, .. }) if key == "rollout_percentage")
                    && !decimal_places_at_most(token, 2)
                {
                    return Err(ParseError::Malformed("rollout_percentage"));
                }
            }
            _ => index += 1,
        }
        compact_bytes += index - start;
        if compact_bytes > max_config_bytes {
            return Err(ParseError::LimitExceeded("filters"));
        }
    }
    Ok(())
}
