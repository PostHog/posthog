use serde::{Deserialize, Serialize};

/// One re-keyed event as published to `cohort_stream_events`. Field names mirror the shuffler
/// envelope exactly.
///
/// `properties` / `person_properties` are raw JSON strings parsed lazily in globals construction.
/// `source_partition` / `source_offset` are the upstream coordinates for replay-safe counter
/// increments.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CohortStreamEvent {
    pub team_id: i32,
    pub person_id: String,
    pub distinct_id: String,
    pub uuid: String,
    pub event: String,
    /// ClickHouse wire format `"YYYY-MM-DD HH:MM:SS.ffffff"`; normalized to ISO 8601 in globals.
    pub timestamp: String,
    pub properties: Option<String>,
    pub person_properties: Option<String>,
    pub elements_chain: Option<String>,
    pub source_offset: i64,
    pub source_partition: i32,
    /// The merge origin person, set when a post-merge straggler is redirected to the merged-into
    /// person. `None` for a normal event. Stage 1 routes replay-dedup through
    /// `redirect_dedup[origin]` when set, preventing double-fold.
    #[serde(default)]
    pub redirected_from: Option<String>,
    /// Cross-partition re-produce hops this straggler has taken through the tombstone redirect.
    /// `0` for a normal event; incremented on each re-key produce. At the cap
    /// (`MAX_CROSS_PARTITION_REDIRECT_HOPS`) the worker degrades to an inline fold to break cycles.
    #[serde(default)]
    pub redirect_hops: u8,
}
