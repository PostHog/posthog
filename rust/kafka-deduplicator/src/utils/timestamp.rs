/// Parse a timestamp string into milliseconds since epoch
/// Supports only valid formats:
/// - u64 (assumed to be milliseconds or seconds based on magnitude)
/// - ISO 8601 / RFC3339 datetime strings (strict format)
pub fn parse_timestamp(timestamp_str: &str) -> Option<u64> {
    // First try parsing as u64 (for backward compatibility with numeric timestamps)
    if let Ok(ts) = timestamp_str.parse::<u64>() {
        // If it's a 10-digit number, assume it's seconds and convert to millis
        // If it's 13+ digits, assume it's already milliseconds
        if ts < 10_000_000_000 {
            return Some(ts * 1000);
        } else {
            return Some(ts);
        }
    }

    // Try parsing as ISO 8601 / RFC3339 datetime (strict format)
    if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(timestamp_str) {
        // Convert to milliseconds for consistent precision
        return Some(dt.timestamp_millis() as u64);
    }

    // Not a valid timestamp format
    None
}

/// Check if a timestamp string is in a valid format
pub fn is_valid_timestamp(timestamp_str: &str) -> bool {
    parse_timestamp(timestamp_str).is_some()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_timestamp_valid_formats() {
        // Test standard RFC3339 formats
        assert!(parse_timestamp("2025-09-02T14:45:58.462+02:00").is_some());
        assert!(parse_timestamp("2025-09-02T14:45:58.462Z").is_some());
        assert!(parse_timestamp("2025-09-02T14:45:58+02:00").is_some());

        // Test numeric timestamps
        assert_eq!(parse_timestamp("1693584358"), Some(1693584358000)); // seconds to millis
        assert_eq!(parse_timestamp("1693584358000"), Some(1693584358000)); // already millis
    }

    #[test]
    fn test_parse_timestamp_invalid_formats() {
        // These formats are not valid RFC3339 and should fail
        assert!(parse_timestamp("2025-09-02T14:45:58.462+02").is_none()); // Missing :00
        assert!(parse_timestamp("2025-09-02T19:08:52.84").is_none()); // No timezone
        assert!(parse_timestamp("2025-09-02T19:08:52.8").is_none()); // Partial millis, no timezone
        assert!(parse_timestamp("2025-09-02T19:08:52").is_none()); // No millis, no timezone

        // Other invalid formats
        assert!(parse_timestamp("not-a-timestamp").is_none());
        assert!(parse_timestamp("").is_none());
    }

    #[test]
    fn test_is_valid_timestamp() {
        // Valid formats
        assert!(is_valid_timestamp("2025-09-02T14:45:58.462+02:00"));
        assert!(is_valid_timestamp("2025-09-02T14:45:58.462Z"));
        assert!(is_valid_timestamp("1693584358"));

        // Invalid formats
        assert!(!is_valid_timestamp("2025-09-02T14:45:58.462+02")); // Missing :00
        assert!(!is_valid_timestamp("not-a-timestamp"));
        assert!(!is_valid_timestamp(""));
    }
}
