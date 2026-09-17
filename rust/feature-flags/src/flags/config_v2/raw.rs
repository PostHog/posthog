use serde::Deserialize;
use serde_json::value::RawValue;

use super::ParseError;

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

pub(crate) fn classify_number(number: &str, expected: f64) -> bool {
    decimal_places_at_most(number, 0) && number.parse::<f64>().ok() == Some(expected)
}

pub(crate) fn validate_raw_percentages(document: &RawValue) -> Result<(), ParseError> {
    #[derive(Deserialize)]
    struct Percentages<'a> {
        #[serde(borrow)]
        rules: Vec<Rule<'a>>,
    }
    #[derive(Deserialize)]
    struct Rule<'a> {
        #[serde(borrow)]
        rollout_percentage: Option<&'a RawValue>,
    }
    let parsed: Percentages<'_> =
        serde_json::from_str(document.get()).map_err(|_| ParseError::Malformed("rules"))?;
    for rule in parsed.rules {
        if let Some(percentage) = rule.rollout_percentage {
            if !decimal_places_at_most(percentage.get(), 2) {
                return Err(ParseError::Malformed("rollout_percentage"));
            }
        }
    }
    Ok(())
}
