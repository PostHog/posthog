//! Shared request-parameter helpers (time ranges etc.).

use chrono::{DateTime, Duration, Utc};
use serde::Deserialize;

#[derive(Debug, Clone, Deserialize, Default)]
pub struct Range {
    /// Look-back window like `15m`, `1h`, `24h` (default 1h) — or explicit `from`/`to`.
    pub since: Option<String>,
    pub from: Option<DateTime<Utc>>,
    pub to: Option<DateTime<Utc>>,
}

impl Range {
    pub fn resolve(&self) -> anyhow::Result<(DateTime<Utc>, DateTime<Utc>)> {
        let to = self.to.unwrap_or_else(Utc::now);
        let from = match (&self.from, &self.since) {
            (Some(f), _) => *f,
            (None, Some(s)) => to - Duration::from_std(humantime::parse_duration(s)?)?,
            (None, None) => to - Duration::hours(1),
        };
        anyhow::ensure!(from < to, "empty range");
        anyhow::ensure!(
            to - from <= Duration::days(31),
            "range too large (max 31 days)"
        );
        Ok((from, to))
    }
}
