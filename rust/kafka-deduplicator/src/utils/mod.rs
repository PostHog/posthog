pub mod timestamp;

use std::path::{Path, PathBuf};

use chrono::{DateTime, Utc};

/// Format a topic/partition pair as a filesystem-safe directory name.
/// Replaces `/` characters with `_` since `/` would create subdirectories.
pub fn format_partition_dir(topic: &str, partition: i32) -> String {
    format!("{}_{}", topic.replace('/', "_"), partition)
}

/// Build a complete store path with timestamp subdirectory.
/// Used by both StoreManager and CheckpointMetadata to ensure consistent paths.
pub fn format_store_path(
    base_path: &Path,
    topic: &str,
    partition: i32,
    timestamp: DateTime<Utc>,
) -> PathBuf {
    base_path
        .join(format_partition_dir(topic, partition))
        .join(timestamp.timestamp_millis().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    #[test]
    fn test_format_partition_dir_simple() {
        assert_eq!(format_partition_dir("events", 0), "events_0");
        assert_eq!(format_partition_dir("events", 42), "events_42");
    }

    #[test]
    fn test_format_partition_dir_with_slashes() {
        assert_eq!(format_partition_dir("org/events", 0), "org_events_0");
        assert_eq!(format_partition_dir("a/b/c", 1), "a_b_c_1");
    }

    #[test]
    fn test_format_partition_dir_edge_cases() {
        assert_eq!(format_partition_dir("", 0), "_0");
        assert_eq!(format_partition_dir("/", 0), "__0");
        assert_eq!(format_partition_dir("events/", 0), "events__0");
    }

    #[test]
    fn test_format_store_path() {
        let base = Path::new("/data/stores");
        // 2009-02-13T23:31:30.123Z
        let ts = Utc.timestamp_millis_opt(1234567890123).unwrap();
        let path = format_store_path(base, "events", 5, ts);
        assert_eq!(path, PathBuf::from("/data/stores/events_5/1234567890123"));
    }

    #[test]
    fn test_format_store_path_with_slashes() {
        let base = Path::new("/data/stores");
        let ts = Utc.timestamp_millis_opt(9999).unwrap();
        let path = format_store_path(base, "org/events", 0, ts);
        assert_eq!(path, PathBuf::from("/data/stores/org_events_0/9999"));
    }
}
