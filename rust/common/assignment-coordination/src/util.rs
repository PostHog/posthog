use std::collections::HashMap;

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
}
