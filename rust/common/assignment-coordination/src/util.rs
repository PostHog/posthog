use std::collections::HashMap;

use crate::error::{Error, Result};

/// Validate that an identifier is safe for use in etcd key paths.
///
/// Identifiers (consumer names, topic names) are interpolated into etcd key
/// paths. Without validation, a name like `../../handoffs/events/0` could
/// write to arbitrary keys.
pub fn validate_identifier(name: &str) -> Result<()> {
    if name.is_empty() || name.len() > 128 {
        return Err(Error::InvalidState(
            "identifier must be 1-128 characters".to_string(),
        ));
    }
    if !name
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        return Err(Error::InvalidState(
            "identifier contains invalid characters (only alphanumeric, dash, underscore allowed)"
                .to_string(),
        ));
    }
    Ok(())
}

pub fn now_seconds() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64
}

/// Compare current and desired assignments to find partitions that need to move.
///
/// Returns `(partition, old_owner, new_owner)` for each partition whose owner
/// changed. New partitions (present in `desired` but not `current`) are not
/// included — they don't need a handoff, just a direct assignment.
pub fn compute_required_handoffs(
    current: &HashMap<u32, String>,
    desired: &HashMap<u32, String>,
) -> Vec<(u32, String, String)> {
    let mut handoffs = Vec::new();
    for (partition, new_owner) in desired {
        if let Some(old_owner) = current.get(partition) {
            if old_owner != new_owner {
                handoffs.push((*partition, old_owner.clone(), new_owner.clone()));
            }
        }
    }
    handoffs
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_change() {
        let mut current = HashMap::new();
        current.insert(0, "c-0".to_string());
        current.insert(1, "c-1".to_string());
        let desired = current.clone();
        assert!(compute_required_handoffs(&current, &desired).is_empty());
    }

    #[test]
    fn detects_moves() {
        let mut current = HashMap::new();
        current.insert(0, "c-0".to_string());
        current.insert(1, "c-0".to_string());

        let mut desired = HashMap::new();
        desired.insert(0, "c-0".to_string());
        desired.insert(1, "c-1".to_string());

        let handoffs = compute_required_handoffs(&current, &desired);
        assert_eq!(handoffs.len(), 1);
        assert_eq!(handoffs[0], (1, "c-0".to_string(), "c-1".to_string()));
    }

    #[test]
    fn new_partitions_not_included() {
        let current = HashMap::new();
        let mut desired = HashMap::new();
        desired.insert(0, "c-0".to_string());
        assert!(compute_required_handoffs(&current, &desired).is_empty());
    }

    #[test]
    fn validate_identifier_accepts_valid() {
        for name in ["c-0", "consumer_1", "abc", "A-B_C-123"] {
            assert!(validate_identifier(name).is_ok(), "should accept: {name}");
        }
    }

    #[test]
    fn validate_identifier_rejects_empty() {
        assert!(validate_identifier("").is_err());
    }

    #[test]
    fn validate_identifier_rejects_too_long() {
        let long = "a".repeat(129);
        assert!(validate_identifier(&long).is_err());
    }

    #[test]
    fn validate_identifier_rejects_path_traversal() {
        for name in ["../../etc", "foo/bar", "a.b", "hello world"] {
            assert!(validate_identifier(name).is_err(), "should reject: {name}");
        }
    }
}
