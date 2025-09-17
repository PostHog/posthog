use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
enum Level {
    Error,
    Debug,
    Warn,
    Info,
    Warning,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
struct LogEntry {
    team_id: u32,
    log_source: String,
    log_source_id: String,
    instance_id: String,
    timestamp: DateTime<Utc>,
    level: Level,
    message: String,
}
