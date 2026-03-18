use std::collections::HashSet;

/// Handles logic for determining if person processing should be disabled for specific token:distinct_id pairs
#[derive(Debug, Clone)]
pub struct PersonProcessingFilter {
    // Set of "token:distinct_id" pairs that should have person processing disabled
    disabled_pairs: HashSet<String>,
}

impl PersonProcessingFilter {
    /// Create a new filter from a comma-separated string of "token:distinct_id" pairs
    pub fn new(config_string: &str) -> Self {
        let disabled_pairs = config_string
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .filter_map(|entry| {
                // Find the first colon to split token from distinct_id
                entry.find(':').map(|idx| {
                    let token = &entry[..idx];
                    let distinct_id = &entry[idx + 1..];
                    format!("{}:{}", token, distinct_id)
                })
            })
            .collect();

        Self { disabled_pairs }
    }

    /// Check if person processing should be disabled for the given token and distinct_id
    pub fn should_disable_person_processing(&self, token: &str, distinct_id: &str) -> bool {
        let pair = format!("{}:{}", token, distinct_id);
        self.disabled_pairs.contains(&pair)
    }

    /// Returns true if the filter is empty (no pairs configured)
    pub fn is_empty(&self) -> bool {
        self.disabled_pairs.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_empty_config() {
        let filter = PersonProcessingFilter::new("");
        assert!(filter.is_empty());
        assert!(!filter.should_disable_person_processing("token1", "user1"));
    }

    #[test]
    fn test_single_pair() {
        let filter = PersonProcessingFilter::new("token1:user1");
        assert!(!filter.is_empty());
        assert!(filter.should_disable_person_processing("token1", "user1"));
        assert!(!filter.should_disable_person_processing("token1", "user2"));
        assert!(!filter.should_disable_person_processing("token2", "user1"));
    }

    #[test]
    fn test_multiple_pairs() {
        let filter = PersonProcessingFilter::new("token1:user1,token2:user2,token3:user3");
        assert!(filter.should_disable_person_processing("token1", "user1"));
        assert!(filter.should_disable_person_processing("token2", "user2"));
        assert!(filter.should_disable_person_processing("token3", "user3"));
        assert!(!filter.should_disable_person_processing("token1", "user2"));
        assert!(!filter.should_disable_person_processing("token4", "user4"));
    }

    #[test]
    fn test_whitespace_handling() {
        let filter = PersonProcessingFilter::new("token1:user1 , token2:user2 , token3:user3");
        assert!(filter.should_disable_person_processing("token1", "user1"));
        assert!(filter.should_disable_person_processing("token2", "user2"));
        assert!(filter.should_disable_person_processing("token3", "user3"));
    }

    #[test]
    fn test_empty_elements() {
        let filter = PersonProcessingFilter::new("token1:user1,,,token2:user2");
        assert!(filter.should_disable_person_processing("token1", "user1"));
        assert!(filter.should_disable_person_processing("token2", "user2"));
        assert!(!filter.should_disable_person_processing("", ""));
    }

    #[test]
    fn test_distinct_id_with_special_characters() {
        let filter = PersonProcessingFilter::new("token1:user@example.com");
        assert!(filter.should_disable_person_processing("token1", "user@example.com"));
        assert!(!filter.should_disable_person_processing("token1", "user"));
    }

    #[test]
    fn test_entry_with_multiple_colons() {
        // Entry with multiple colons - splits on first colon only during parsing
        let filter = PersonProcessingFilter::new("phc_abc:def:user123");
        // Stored as: "phc_abc:def:user123"
        // This matches because format!("{}:{}", "phc_abc", "def:user123") == "phc_abc:def:user123"
        assert!(filter.should_disable_person_processing("phc_abc", "def:user123"));
        // This also matches because format!("{}:{}", "phc_abc:def", "user123") == "phc_abc:def:user123"
        assert!(filter.should_disable_person_processing("phc_abc:def", "user123"));
        // This does NOT match
        assert!(!filter.should_disable_person_processing("phc_abc", "def"));
    }

    #[test]
    fn test_distinct_id_with_colons() {
        let filter = PersonProcessingFilter::new("token1:user:session:123");
        assert!(filter.should_disable_person_processing("token1", "user:session:123"));
        assert!(!filter.should_disable_person_processing("token1", "user"));
    }
}
