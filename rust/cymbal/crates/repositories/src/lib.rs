//! Persistence and side-effect boundaries for Cymbal.
//!
//! This crate owns repository-facing DTOs and helpers for Postgres, Redis-backed
//! state, and PostHog capture hooks. Stage crates depend on traits where possible,
//! while runtime constructs concrete repository implementations.

pub mod issue;
pub mod posthog;
pub mod redis;
pub mod team;

pub use issue::{
    FingerprintIssueState, Issue, IssueFingerprintOverride, IssueStatus, IssueWithFirstSeen,
};
pub use redis::{new_issue_buckets_redis_client, RedisBackedStateConfig};
pub use team::{CachedTeamRepository, TeamRepositoryConfig};
