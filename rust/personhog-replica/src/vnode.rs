use serde::Deserialize;
use std::collections::{HashMap, HashSet};
use std::path::Path;

/// Total number of vnodes in the system.
pub const VNODE_COUNT: u32 = 64;

/// How the service should handle routing awareness.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum RoutingMode {
    /// Routing checks are disabled. All requests are served without checking vnode ownership.
    #[default]
    Disabled,
    /// Routing checks are enabled in observe mode. Misrouted requests emit metrics but are
    /// still served. Useful during rollout to monitor routing accuracy.
    Observe,
    /// Routing checks are enforced. Misrouted requests emit metrics and are rejected with
    /// an error, signaling the client to retry with the correct pod.
    Enforce,
}

impl RoutingMode {
    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "disabled" | "off" | "none" => Some(Self::Disabled),
            "observe" | "monitor" | "warn" => Some(Self::Observe),
            "enforce" | "reject" | "strict" => Some(Self::Enforce),
            _ => None,
        }
    }
}

/// Compute the vnode for a given (team_id, person_id) pair.
///
/// Uses xxHash3 (64-bit) for fast, high-quality hashing.
/// The vnode is computed as: hash(team_id:person_id) % 64
pub fn compute_vnode(team_id: i64, person_id: i64) -> u32 {
    let key = format!("{}:{}", team_id, person_id);
    let hash = xxhash_rust::xxh3::xxh3_64(key.as_bytes());
    (hash % VNODE_COUNT as u64) as u32
}

/// Raw config file format for vnode assignments.
///
/// Example JSON:
/// ```json
/// {
///   "vnodes": {
///     "personhog-replica-0": [0, 3, 6, 9],
///     "personhog-replica-1": [1, 4, 7, 10],
///     "personhog-replica-2": [2, 5, 8, 11]
///   }
/// }
/// ```
#[derive(Debug, Deserialize)]
struct VnodeConfigFile {
    vnodes: HashMap<String, Vec<u32>>,
}

/// Vnode ownership configuration for this pod.
#[derive(Debug, Clone)]
pub struct VnodeOwnership {
    /// The pod identity (e.g., "personhog-replica-0")
    pod_name: String,
    /// Set of vnodes this pod is responsible for
    owned_vnodes: HashSet<u32>,
}

impl VnodeOwnership {
    /// Load vnode ownership from a JSON file for the given pod.
    ///
    /// Returns an error if the file exists but can't be parsed, or if the pod
    /// is not found in the configuration.
    pub fn load(config_path: &Path, pod_name: &str) -> Result<Self, VnodeConfigError> {
        let content = std::fs::read_to_string(config_path)
            .map_err(|e| VnodeConfigError::Io(config_path.display().to_string(), e.to_string()))?;

        let config: VnodeConfigFile = serde_json::from_str(&content)
            .map_err(|e| VnodeConfigError::Parse(config_path.display().to_string(), e.to_string()))?;

        let owned_vnodes = config
            .vnodes
            .get(pod_name)
            .ok_or_else(|| VnodeConfigError::PodNotFound(pod_name.to_string()))?
            .iter()
            .copied()
            .collect();

        Ok(Self {
            pod_name: pod_name.to_string(),
            owned_vnodes,
        })
    }

    /// Create a vnode ownership that owns specific vnodes (for testing).
    pub fn with_vnodes(pod_name: &str, vnodes: &[u32]) -> Self {
        Self {
            pod_name: pod_name.to_string(),
            owned_vnodes: vnodes.iter().copied().collect(),
        }
    }

    /// Check if this pod owns the given vnode.
    pub fn owns_vnode(&self, vnode: u32) -> bool {
        self.owned_vnodes.contains(&vnode)
    }

    /// Check if this pod is responsible for the given (team_id, person_id).
    pub fn owns_person(&self, team_id: i64, person_id: i64) -> bool {
        let vnode = compute_vnode(team_id, person_id);
        self.owns_vnode(vnode)
    }

    /// Get the pod name.
    pub fn pod_name(&self) -> &str {
        &self.pod_name
    }

    /// Get the number of vnodes this pod owns.
    pub fn vnode_count(&self) -> usize {
        self.owned_vnodes.len()
    }
}

/// Combined routing configuration: mode + optional ownership info.
#[derive(Debug, Clone)]
pub struct RoutingConfig {
    mode: RoutingMode,
    ownership: Option<VnodeOwnership>,
}

impl Default for RoutingConfig {
    fn default() -> Self {
        Self {
            mode: RoutingMode::Disabled,
            ownership: None,
        }
    }
}

impl RoutingConfig {
    /// Create a disabled routing config (no checks performed).
    pub fn disabled() -> Self {
        Self::default()
    }

    /// Create a routing config with the given mode and ownership.
    pub fn new(mode: RoutingMode, ownership: VnodeOwnership) -> Self {
        Self {
            mode,
            ownership: Some(ownership),
        }
    }

    /// Get the routing mode.
    pub fn mode(&self) -> RoutingMode {
        self.mode
    }

    /// Check routing for a (team_id, person_id) pair.
    ///
    /// Returns:
    /// - `Ok(())` if routing checks pass or are disabled
    /// - `Err(RoutingCheckResult::Misrouted { ... })` if the request is misrouted
    pub fn check_routing(&self, team_id: i64, person_id: i64) -> RoutingCheckResult {
        match (&self.mode, &self.ownership) {
            (RoutingMode::Disabled, _) | (_, None) => RoutingCheckResult::Ok,
            (mode, Some(ownership)) => {
                let vnode = compute_vnode(team_id, person_id);
                if ownership.owns_vnode(vnode) {
                    RoutingCheckResult::Ok
                } else {
                    RoutingCheckResult::Misrouted {
                        team_id,
                        person_id,
                        vnode,
                        pod_name: ownership.pod_name.clone(),
                        should_reject: *mode == RoutingMode::Enforce,
                    }
                }
            }
        }
    }

    /// Get the pod name if ownership is configured.
    pub fn pod_name(&self) -> Option<&str> {
        self.ownership.as_ref().map(|o| o.pod_name.as_str())
    }
}

/// Result of a routing check.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RoutingCheckResult {
    /// Request is correctly routed (or routing is disabled).
    Ok,
    /// Request was routed to the wrong pod.
    Misrouted {
        team_id: i64,
        person_id: i64,
        vnode: u32,
        pod_name: String,
        /// Whether the request should be rejected (Enforce mode) or just logged (Observe mode).
        should_reject: bool,
    },
}

impl RoutingCheckResult {
    pub fn is_ok(&self) -> bool {
        matches!(self, Self::Ok)
    }

    pub fn is_misrouted(&self) -> bool {
        matches!(self, Self::Misrouted { .. })
    }

    pub fn should_reject(&self) -> bool {
        matches!(self, Self::Misrouted { should_reject: true, .. })
    }
}

#[derive(Debug, thiserror::Error)]
pub enum VnodeConfigError {
    #[error("failed to read vnode config from {0}: {1}")]
    Io(String, String),
    #[error("failed to parse vnode config from {0}: {1}")]
    Parse(String, String),
    #[error("pod '{0}' not found in vnode config")]
    PodNotFound(String),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compute_vnode_deterministic() {
        let vnode1 = compute_vnode(1, 100);
        let vnode2 = compute_vnode(1, 100);
        assert_eq!(vnode1, vnode2);
    }

    #[test]
    fn test_compute_vnode_range() {
        for team_id in 1..100 {
            for person_id in 1..100 {
                let vnode = compute_vnode(team_id, person_id);
                assert!(vnode < VNODE_COUNT, "vnode {} >= {}", vnode, VNODE_COUNT);
            }
        }
    }

    #[test]
    fn test_compute_vnode_distribution() {
        let mut counts = vec![0u32; VNODE_COUNT as usize];
        for team_id in 1..=1000 {
            for person_id in 1..=100 {
                let vnode = compute_vnode(team_id, person_id);
                counts[vnode as usize] += 1;
            }
        }

        let total = 1000 * 100;
        let expected_per_vnode = total / VNODE_COUNT as i32;
        let tolerance = expected_per_vnode / 10; // 10% tolerance

        for (vnode, count) in counts.iter().enumerate() {
            let diff = (*count as i32 - expected_per_vnode).abs();
            assert!(
                diff < tolerance,
                "vnode {} has count {} (expected ~{}, diff {})",
                vnode,
                count,
                expected_per_vnode,
                diff
            );
        }
    }

    #[test]
    fn test_routing_mode_from_str() {
        assert_eq!(RoutingMode::from_str("disabled"), Some(RoutingMode::Disabled));
        assert_eq!(RoutingMode::from_str("off"), Some(RoutingMode::Disabled));
        assert_eq!(RoutingMode::from_str("observe"), Some(RoutingMode::Observe));
        assert_eq!(RoutingMode::from_str("monitor"), Some(RoutingMode::Observe));
        assert_eq!(RoutingMode::from_str("enforce"), Some(RoutingMode::Enforce));
        assert_eq!(RoutingMode::from_str("reject"), Some(RoutingMode::Enforce));
        assert_eq!(RoutingMode::from_str("invalid"), None);
    }

    #[test]
    fn test_vnode_ownership_with_vnodes() {
        let ownership = VnodeOwnership::with_vnodes("test-pod", &[0, 3, 6, 9]);

        assert!(ownership.owns_vnode(0));
        assert!(ownership.owns_vnode(3));
        assert!(ownership.owns_vnode(6));
        assert!(ownership.owns_vnode(9));
        assert!(!ownership.owns_vnode(1));
        assert!(!ownership.owns_vnode(2));
        assert!(!ownership.owns_vnode(63));
        assert_eq!(ownership.vnode_count(), 4);
    }

    #[test]
    fn test_routing_config_disabled() {
        let config = RoutingConfig::disabled();

        // Disabled mode always returns Ok
        assert!(config.check_routing(1, 100).is_ok());
        assert!(config.check_routing(999, 999).is_ok());
    }

    #[test]
    fn test_routing_config_observe_mode() {
        // Find a (team_id, person_id) that maps to vnode 0
        let (team_id, person_id) = find_pair_for_vnode(0);

        let ownership = VnodeOwnership::with_vnodes("test-pod", &[0]);
        let config = RoutingConfig::new(RoutingMode::Observe, ownership);

        // Should be Ok for vnode 0
        assert!(config.check_routing(team_id, person_id).is_ok());

        // Find a pair that maps to vnode 1 (not owned)
        let (team_id2, person_id2) = find_pair_for_vnode(1);
        let result = config.check_routing(team_id2, person_id2);
        assert!(result.is_misrouted());
        assert!(!result.should_reject()); // Observe mode doesn't reject
    }

    #[test]
    fn test_routing_config_enforce_mode() {
        // Find a pair that maps to vnode 1 (not owned by our config)
        let (team_id, person_id) = find_pair_for_vnode(1);

        let ownership = VnodeOwnership::with_vnodes("test-pod", &[0]);
        let config = RoutingConfig::new(RoutingMode::Enforce, ownership);

        let result = config.check_routing(team_id, person_id);
        assert!(result.is_misrouted());
        assert!(result.should_reject()); // Enforce mode rejects
    }

    #[test]
    fn test_load_vnode_ownership_from_json() {
        let temp_dir = std::env::temp_dir();
        let config_path = temp_dir.join("test_vnode_config.json");

        let config_content = r#"{
            "vnodes": {
                "personhog-replica-0": [0, 3, 6, 9],
                "personhog-replica-1": [1, 4, 7, 10],
                "personhog-replica-2": [2, 5, 8, 11]
            }
        }"#;

        std::fs::write(&config_path, config_content).unwrap();

        let result = VnodeOwnership::load(&config_path, "personhog-replica-0");
        assert!(result.is_ok());
        let ownership = result.unwrap();
        assert_eq!(ownership.pod_name(), "personhog-replica-0");
        assert_eq!(ownership.vnode_count(), 4);
        assert!(ownership.owns_vnode(0));
        assert!(ownership.owns_vnode(3));
        assert!(!ownership.owns_vnode(1));

        // Cleanup
        std::fs::remove_file(&config_path).ok();
    }

    #[test]
    fn test_load_vnode_ownership_pod_not_found() {
        let temp_dir = std::env::temp_dir();
        let config_path = temp_dir.join("test_vnode_config_missing_pod.json");

        let config_content = r#"{
            "vnodes": {
                "personhog-replica-0": [0, 3, 6, 9]
            }
        }"#;

        std::fs::write(&config_path, config_content).unwrap();

        let result = VnodeOwnership::load(&config_path, "personhog-replica-99");
        assert!(matches!(result, Err(VnodeConfigError::PodNotFound(_))));

        // Cleanup
        std::fs::remove_file(&config_path).ok();
    }

    /// Helper to find a (team_id, person_id) pair that maps to a specific vnode.
    fn find_pair_for_vnode(target_vnode: u32) -> (i64, i64) {
        for team_id in 1i64..10000 {
            for person_id in 1i64..10000 {
                if compute_vnode(team_id, person_id) == target_vnode {
                    return (team_id, person_id);
                }
            }
        }
        panic!("Could not find pair for vnode {}", target_vnode);
    }
}
