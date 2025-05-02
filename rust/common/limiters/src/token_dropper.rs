use std::collections::HashMap;

use tracing::warn;

#[derive(Default)]
pub struct TokenDropper {
    to_drop: HashMap<String, Option<Vec<String>>>,
}

impl TokenDropper {
    // Takes "token1:id1,token:id2,token" where token without id means drop all events
    pub fn new(config: &str) -> Self {
        let mut to_drop = HashMap::new();

        for entry in config.split(',') {
            if entry.trim().is_empty() {
                continue;
            }
            let mut parts = entry.split(':');

            // fetch token if present and nonempty; if no token, we reject this entry
            let Some(token) = parts.find(|s| !s.trim().is_empty()) else {
                warn!("Invalid format in part {}", entry);
                continue;
            };

            // fetch distinct_id if present and nonempty
            if let Some(id) = parts.find(|s| !s.trim().is_empty()) {
                let entry = to_drop
                    .entry(token.to_string())
                    .or_insert_with(|| Some(Vec::new()));
                if let Some(ids) = entry {
                    ids.push(id.to_string());
                }
            } else {
                // No distinct_id means drop all events for this token
                to_drop.insert(token.to_string(), None);
            }
        }

        Self { to_drop }
    }

    pub fn should_drop(&self, token: &str, distinct_id: &str) -> bool {
        if token.is_empty() {
            return false;
        }
        match self.to_drop.get(token) {
            Some(None) => true, // Drop all events for this token
            Some(Some(ids)) => ids.iter().any(|id| id == distinct_id),
            None => false,
        }
    }
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn test_empty_config() {
        let dropper = TokenDropper::new("");
        assert!(!dropper.should_drop("token", "id"));
    }

    #[test]
    fn test_single_token_id() {
        let dropper = TokenDropper::new("token:id");
        assert!(dropper.should_drop("token", "id"));
        assert!(!dropper.should_drop("token", "other"));
    }

    #[test]
    fn test_multiple_ids() {
        let dropper = TokenDropper::new("token:id1,token:id2");
        assert!(dropper.should_drop("token", "id1"));
        assert!(dropper.should_drop("token", "id2"));
        assert!(!dropper.should_drop("token", "id3"));
    }

    #[test]
    fn test_drop_all_for_token() {
        let dropper = TokenDropper::new("token");
        assert!(dropper.should_drop("token", "anything"));
    }

    #[test]
    fn test_mixed_format() {
        let dropper = TokenDropper::new("token1:id1,token2,token3:id3");
        assert!(dropper.should_drop("token1", "id1"));
        assert!(dropper.should_drop("token2", "anything"));
        assert!(dropper.should_drop("token3", "id3"));
        assert!(!dropper.should_drop("token1", "id2"));
        assert!(!dropper.should_drop("token3", "id1"));
    }
}
