use governor::Quota;
use std::num::NonZeroU32;
use thiserror::Error;

#[derive(Error, Debug, PartialEq)]
pub enum RateParseError {
    #[error("Invalid rate format: {0}. Expected format: 'N/period' (e.g., '600/minute')")]
    InvalidFormat(String),
    #[error("Invalid rate number: {0}")]
    InvalidNumber(String),
    #[error("Invalid time period: {0}. Valid periods: second, minute, hour, day")]
    InvalidPeriod(String),
    #[error("Rate must be greater than zero")]
    ZeroRate,
}

/// Parse a Django SimpleRateThrottle-style rate string into a governor Quota
///
/// Supported formats:
/// - "N/second" - N requests per second
/// - "N/minute" - N requests per minute
/// - "N/hour" - N requests per hour
/// - "N/day" - N requests per day
///
/// Only the first character of the period is significant ('s', 'm', 'h', 'd').
///
/// Examples:
/// ```
/// use feature_flags::api::rate_parser::parse_rate_string;
/// use std::num::NonZeroU32;
///
/// let quota = parse_rate_string("600/minute").unwrap();
/// let quota = parse_rate_string("1200/hour").unwrap();
/// let quota = parse_rate_string("100/second").unwrap();
/// ```
pub fn parse_rate_string(rate_str: &str) -> Result<Quota, RateParseError> {
    let rate_str = rate_str.trim();

    // Split on '/' to get number and period
    let parts: Vec<&str> = rate_str.split('/').collect();
    if parts.len() != 2 {
        return Err(RateParseError::InvalidFormat(rate_str.to_string()));
    }

    // Parse the number part
    let num_str = parts[0].trim();
    let num = num_str
        .parse::<u32>()
        .map_err(|_| RateParseError::InvalidNumber(num_str.to_string()))?;

    if num == 0 {
        return Err(RateParseError::ZeroRate);
    }

    let num = NonZeroU32::new(num).unwrap(); // Safe because we checked for zero above

    // Parse the period part (only first character matters)
    let period_str = parts[1].trim().to_lowercase();
    let period_char = period_str
        .chars()
        .next()
        .ok_or_else(|| RateParseError::InvalidPeriod(parts[1].to_string()))?;

    // Create quota based on period
    let quota = match period_char {
        's' => Quota::per_second(num),
        'm' => Quota::per_minute(num),
        'h' => Quota::per_hour(num),
        'd' => Quota::with_period(std::time::Duration::from_secs(86400))
            .ok_or_else(|| RateParseError::InvalidPeriod("day".to_string()))?
            .allow_burst(num),
        _ => return Err(RateParseError::InvalidPeriod(parts[1].to_string())),
    };

    Ok(quota)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_valid_rate_strings() {
        // Test all valid formats
        assert!(parse_rate_string("600/minute").is_ok());
        assert!(parse_rate_string("1200/hour").is_ok());
        assert!(parse_rate_string("100/second").is_ok());
        assert!(parse_rate_string("2400/day").is_ok());
    }

    #[test]
    fn test_parse_with_whitespace() {
        // Should handle whitespace
        assert!(parse_rate_string(" 600 / minute ").is_ok());
        assert!(parse_rate_string("600/minute ").is_ok());
        assert!(parse_rate_string(" 600/minute").is_ok());
    }

    #[test]
    fn test_parse_first_char_only() {
        // Only first character of period matters (Django behavior)
        assert!(parse_rate_string("600/m").is_ok());
        assert!(parse_rate_string("600/min").is_ok());
        assert!(parse_rate_string("600/minutes").is_ok());
        assert!(parse_rate_string("100/s").is_ok());
        assert!(parse_rate_string("100/sec").is_ok());
        assert!(parse_rate_string("100/seconds").is_ok());
        assert!(parse_rate_string("1200/h").is_ok());
        assert!(parse_rate_string("1200/hr").is_ok());
        assert!(parse_rate_string("1200/hours").is_ok());
        assert!(parse_rate_string("2400/d").is_ok());
        assert!(parse_rate_string("2400/day").is_ok());
        assert!(parse_rate_string("2400/days").is_ok());
    }

    #[test]
    fn test_parse_case_insensitive() {
        // Period should be case-insensitive
        assert!(parse_rate_string("600/MINUTE").is_ok());
        assert!(parse_rate_string("600/Minute").is_ok());
        assert!(parse_rate_string("100/SECOND").is_ok());
    }

    #[test]
    fn test_invalid_format_no_slash() {
        let result = parse_rate_string("600");
        assert!(matches!(result, Err(RateParseError::InvalidFormat(_))));
    }

    #[test]
    fn test_invalid_format_multiple_slashes() {
        let result = parse_rate_string("600/minute/extra");
        assert!(matches!(result, Err(RateParseError::InvalidFormat(_))));
    }

    #[test]
    fn test_invalid_format_empty_period() {
        let result = parse_rate_string("600/");
        assert!(matches!(result, Err(RateParseError::InvalidPeriod(_))));
    }

    #[test]
    fn test_invalid_number() {
        let result = parse_rate_string("abc/minute");
        assert!(matches!(result, Err(RateParseError::InvalidNumber(_))));
    }

    #[test]
    fn test_invalid_number_negative() {
        let result = parse_rate_string("-600/minute");
        assert!(matches!(result, Err(RateParseError::InvalidNumber(_))));
    }

    #[test]
    fn test_invalid_number_float() {
        let result = parse_rate_string("600.5/minute");
        assert!(matches!(result, Err(RateParseError::InvalidNumber(_))));
    }

    #[test]
    fn test_zero_rate() {
        let result = parse_rate_string("0/minute");
        assert_eq!(result, Err(RateParseError::ZeroRate));
    }

    #[test]
    fn test_invalid_period() {
        let result = parse_rate_string("600/invalid");
        assert!(matches!(result, Err(RateParseError::InvalidPeriod(_))));
    }

    #[test]
    fn test_invalid_period_year() {
        // 'y' for year is not supported
        let result = parse_rate_string("600/year");
        assert!(matches!(result, Err(RateParseError::InvalidPeriod(_))));
    }

    #[test]
    fn test_quota_values() {
        // Verify the quota is created with correct values
        let quota = parse_rate_string("600/minute").unwrap();
        // We can't directly inspect quota internals, but we can verify it was created
        assert!(format!("{quota:?}").contains("600"));
    }
}
