pub const EVENTS_RECEIVED: &str = "prop_defs_events_received";
pub const EVENTS_SKIPPED: &str = "prop_defs_events_skipped";
pub const FORCED_SMALL_BATCH: &str = "prop_defs_forced_small_batch";
pub const UPDATES_SEEN: &str = "prop_defs_seen_updates";
pub const WORKER_BLOCKED: &str = "prop_defs_worker_blocked";
pub const UPDATES_PER_EVENT: &str = "prop_defs_updates_per_event";
pub const UPDATES_FILTERED_BY_CACHE: &str = "prop_defs_filtered_by_cache";
pub const EMPTY_EVENTS: &str = "prop_defs_empty_events";
pub const EVENT_PARSE_ERROR: &str = "prop_defs_event_parse_error";
pub const BATCH_ACQUIRE_TIME: &str = "prop_defs_batch_acquire_time_ms";
// Fraction of a subcache's capacity currently occupied, 0.0 to 1.0. Not an absolute size:
// CACHE_LEN carries that, and a threshold written against this one has to be a fraction.
pub const CACHE_FILL_RATIO: &str = "prop_defs_cache_fill_ratio";
pub const CACHE_LEN: &str = "prop_defs_cache_len";
pub const CACHE_HITS: &str = "prop_defs_cache_hits";
pub const CACHE_MISSES: &str = "prop_defs_cache_misses";
pub const CACHE_EVICTIONS: &str = "prop_defs_cache_evictions";
pub const UPDATES_CACHE: &str = "prop_defs_updates_cache";
// Kafka offset stores that failed. The producer loop continues past a failure, so a later
// successful store on the same partition supersedes it and nothing is redelivered. Redelivery
// only follows a failure that a rebalance or restart interrupts before the next store lands.
pub const OFFSET_STORE_FAILURES: &str = "prop_defs_offset_store_failures";

// Outcomes of group-type resolution, labeled `action`:
//   hit          local cache had the index
//   miss         local cache did not, and personhog resolved it (a cache miss, not a failure)
//   negative_hit a recent unresolvable lookup is still within its TTL, so we skipped personhog
//   fail         personhog returned no mapping, and the definition is dropped
// A hit rate must divide by the sum of all four. Dividing by hit + miss alone silently drops
// both of the outcomes where a definition does not get written.
pub const GROUP_TYPE_CACHE: &str = "prop_defs_group_type_cache";
pub const RECV_DEQUEUED: &str = "prop_defs_recv_dequeued";
pub const COMPACTED_UPDATES: &str = "prop_defs_compaction_dropped_updates";
pub const UPDATES_SKIPPED: &str = "prop_defs_skipped_updates";
pub const SKIPPED_DUE_TO_TEAM_FILTER: &str = "prop_defs_skipped_due_to_team_filter";
pub const ISSUE_FAILED: &str = "prop_defs_issue_failed";
pub const DUPLICATES_IN_BATCH: &str = "prop_defs_duplicates_in_batch";
pub const CHANNEL_MESSAGES_IN_FLIGHT: &str = "prop_defs_channel_messages_in_flight";
// Remaining free slots, not the channel size. CHANNEL_CAPACITY_TOTAL carries the size, so
// occupancy is 1 - (capacity / capacity_total).
pub const CHANNEL_CAPACITY: &str = "prop_defs_channel_capacity";
pub const CHANNEL_CAPACITY_TOTAL: &str = "prop_defs_channel_capacity_total";

pub const PERSONHOG_RESOLVE_ERRORS: &str = "prop_defs_personhog_resolve_errors";
pub const PERSONHOG_RESOLVE_DURATION: &str = "prop_defs_personhog_resolve_duration_ms";
pub const PERSONHOG_ERRORS_TOTAL: &str = "personhog_errors_total";
pub const PERSONHOG_RETRIES_TOTAL: &str = "personhog_retries_total";
pub const PERSONHOG_TERMINAL_ERRORS_TOTAL: &str = "personhog_terminal_errors_total";

//
// Batch write path metric keys below. The "v2" prefix is vestigial and maps to nothing in the
// current code, but Grafana dashboards query these names directly, so renaming them means
// changing the dashboards in lockstep rather than editing this file alone.
//

pub const V2_EVENT_DEFS_BATCH_WRITE_TIME: &str = "propdefs_v2_eventdefs_batch_ms";
pub const V2_EVENT_DEFS_BATCH_ATTEMPT: &str = "propdefs_v2_eventdefs_batch_attempt";
pub const V2_EVENT_DEFS_BATCH_ROWS_AFFECTED: &str = "propdefs_v2_eventdefs_batch_rows";
pub const V2_EVENT_DEFS_BATCH_CACHE_TIME: &str = "propdefs_v2_eventdefs_batch_cache_time_ms";
pub const V2_EVENT_DEFS_CACHE_REMOVED: &str = "propdefs_v2_eventdefs_cache_removed";
pub const V2_EVENT_DEFS_BATCH_SIZE: &str = "propdefs_v2_eventdefs_batch_size";

pub const V2_EVENT_PROPS_BATCH_WRITE_TIME: &str = "propdefs_v2_eventprops_batch_ms";
pub const V2_EVENT_PROPS_BATCH_ATTEMPT: &str = "propdefs_v2_eventprops_batch_attempt";
pub const V2_EVENT_PROPS_BATCH_ROWS_AFFECTED: &str = "propdefs_v2_eventprops_batch_rows";
pub const V2_EVENT_PROPS_BATCH_CACHE_TIME: &str = "propdefs_v2_eventprops_batch_cache_time_ms";
pub const V2_EVENT_PROPS_CACHE_REMOVED: &str = "propdefs_v2_eventprops_cache_removed";
pub const V2_EVENT_PROPS_BATCH_SIZE: &str = "propdefs_v2_eventprops_batch_size";

pub const V2_PROP_DEFS_BATCH_WRITE_TIME: &str = "propdefs_v2_propdefs_batch_ms";
pub const V2_PROP_DEFS_BATCH_ATTEMPT: &str = "propdefs_v2_propdefs_batch_attempt";
pub const V2_PROP_DEFS_BATCH_ROWS_AFFECTED: &str = "propdefs_v2_propdefs_batch_rows";
pub const V2_PROP_DEFS_BATCH_CACHE_TIME: &str = "propdefs_v2_propdefs_batch_cache_time_ms";
pub const V2_PROP_DEFS_CACHE_REMOVED: &str = "propdefs_v2_propdefs_cache_removed";
pub const V2_PROP_DEFS_BATCH_SIZE: &str = "propdefs_v2_propdefs_batch_size";

// Group property definitions dropped for an unresolved group_type_index and evicted from
// the shared dedup cache, so a later $groupidentify (whose type resolves once the mapping
// lands) is not filtered out and can persist.
pub const V2_PROP_DEFS_DROPPED_UNCACHED: &str = "propdefs_v2_propdefs_dropped_uncached";

// Rows stripped from a write batch because they reference a team/project that no longer
// exists (Postgres FK violation, e.g. a deleted team still sending events). Labeled by
// target table. Stripped rows stay in the shared dedup cache on purpose, so the dead
// tenant's events stop re-issuing the same failing write.
pub const V2_BATCH_ROWS_DROPPED_FK: &str = "propdefs_v2_batch_rows_dropped_fk";
