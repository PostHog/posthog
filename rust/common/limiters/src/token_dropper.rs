use std::collections::HashMap;

use tracing::warn;

#[derive(Default)]
pub struct TokenDropper {
    to_drop: HashMap<String, Vec<String>>,
}

impl TokenDropper {
    // Takes "<token>:<distinct_id or *>,<distinct_id or *>;<token>..."
    pub fn new(config: &str) -> Self {
        let mut to_drop = HashMap::new();
        for pair in config.split(';') {
            let mut parts = pair.split(':');
            let Some(token) = parts.next() else {
                warn!("No distinct id's configured for pair {}", pair);
                continue;
            };
            let Some(ids) = parts.next() else {
                warn!("No distinct id's configured for token {}", token);
                continue;
            };
            let ids = ids.split(',').map(|s| s.to_string()).collect();
            to_drop.insert(token.to_string(), ids);
        }
        Self { to_drop }
    }

    pub fn should_drop(&self, token: &str, distinct_id: &str) -> bool {
        self.to_drop
            .get(token)
            .map(|ids| ids.iter().any(|id| id == distinct_id || id == "*"))
            .unwrap_or(false)
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
        let dropper = TokenDropper::new("token:id1,id2");
        assert!(dropper.should_drop("token", "id1"));
        assert!(dropper.should_drop("token", "id2"));
        assert!(!dropper.should_drop("token", "id3"));
    }

    #[test]
    fn test_wildcard() {
        let dropper = TokenDropper::new("token:*");
        assert!(dropper.should_drop("token", "anything"));
    }

    #[test]
    fn test_multiple_tokens() {
        let dropper = TokenDropper::new("token1:id1;token2:id2");
        assert!(dropper.should_drop("token1", "id1"));
        assert!(dropper.should_drop("token2", "id2"));
        assert!(!dropper.should_drop("token1", "id2"));
    }
}
