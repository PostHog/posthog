//! Internal batch flag evaluation endpoint for flag-driven static cohort generation.
//!
//! Django's `get_cohort_actors_for_feature_flag` Celery task drives this endpoint with
//! strictly sequential, cursor-paged requests: each page scans a slice of a team's persons
//! and evaluates a single (pinned-version) flag for every person, reusing the exact same
//! `FeatureFlagMatcher` machinery as live `/flags` evaluation. The response carries the
//! matched person UUIDs, which Django inserts into the static cohort.
//!
//! Deliberate differences from the live `/flags` pipeline:
//! - Auth is the `INTERNAL_REQUEST_TOKEN` bearer token only — no SDK token, no team lookup
//!   by token. The team is still loaded by id (once per page) to read its timezone, so
//!   naive datetime filters evaluate in the team's local time exactly like live `/flags`.
//! - The handler bypasses the `/flags` request pipeline entirely, so no billing or
//!   flag-analytics counters are emitted, and dedicated `flags_batch_eval_*` ops metrics
//!   track batch traffic. The per-person matcher still emits its own evaluation metrics
//!   (`flags_evaluation_time`, dependency-graph build counters), which share the same
//!   series as live `/flags`, so a large cohort run dominates those on its pod.
//! - The matcher always runs with `skip_writes(true)`: experience-continuity hash key
//!   overrides are read but never written.
//! - Flags are always read fresh from Postgres (never the hypercache) so the
//!   `expected_version` optimistic-lock check is meaningful.
//!
//! The paged scan walks `posthog_person.id` ascending across a live table, so the run sees
//! a moving snapshot rather than a point-in-time one: persons inserted above the current
//! cursor mid-run are included, persons inserted below it (or deleted) are not. Flag
//! definitions are pinned by `expected_version`, but person membership is eventually
//! consistent with the table at the time each page is scanned. This matches the existing
//! cohort-generation contract (a later refresh reconciles drift).

use std::collections::HashSet;
use std::sync::Arc;

use axum::{
    body::Body,
    extract::State,
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use common_database::PostgresReader;
use common_metrics::inc;
use common_types::PersonId;
use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use tracing::warn;
use uuid::Uuid;

use crate::{
    api::errors::FlagError,
    database::{get_connection_with_metrics, PostgresRouter},
    flags::{
        cache_builder::compute_flag_dependencies,
        feature_flag_list::PreparedFlags,
        flag_matching::FeatureFlagMatcher,
        flag_models::{EvaluationMetadata, FeatureFlag, FeatureFlagList},
    },
    handler::authentication::is_internal_request_inner,
    metrics::consts::{
        FLAG_BATCH_EVAL_PERSONS_COUNTER, FLAG_BATCH_EVAL_REQUESTS_COUNTER, FLAG_BATCH_EVAL_TIME,
    },
    router,
};

#[derive(Debug, Deserialize)]
pub struct BatchFlagEvaluationRequest {
    pub team_id: i32,
    /// The project the flag belongs to. Accepted for contract parity with the Django
    /// caller; flag lookup is team-scoped (matching live Rust evaluation), so this is
    /// currently informational only.
    #[serde(default)]
    pub project_id: Option<i64>,
    pub flag_key: String,
    /// Optimistic-lock pin: the flag `version` Django read before starting the run.
    /// Nullable versions coerce to 0 on both sides, so JSON `null` is accepted and
    /// treated as 0.
    #[serde(default)]
    pub expected_version: Option<i32>,
    /// Exclusive lower bound on `posthog_person.id`; 0 (default) starts from the beginning.
    #[serde(default)]
    pub cursor: i64,
    /// Page size; defaults to `DEFAULT_LIMIT` (1000), capped by `BATCH_FLAG_EVAL_MAX_LIMIT`.
    pub limit: Option<i64>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct BatchFlagEvaluationResponse {
    pub matched_person_uuids: Vec<Uuid>,
    /// Cursor for the next page, or `None` when this page was the last one.
    pub next_cursor: Option<i64>,
    /// Number of persons in this page whose evaluation failed (they are skipped, not matched).
    pub errors_count: u64,
}

const DEFAULT_LIMIT: i64 = 1_000;

#[derive(Debug)]
pub enum BatchFlagEvaluationError {
    Unauthorized,
    InvalidRequest(String),
    PayloadTooLarge,
    FlagNotFound,
    FlagInactive,
    GroupAggregatedFlag,
    VersionConflict { expected: i32, actual: i32 },
    Upstream(FlagError),
}

impl BatchFlagEvaluationError {
    fn outcome_label(&self) -> &'static str {
        match self {
            Self::Unauthorized => "unauthorized",
            Self::InvalidRequest(_) => "invalid_request",
            Self::PayloadTooLarge => "payload_too_large",
            Self::FlagNotFound => "flag_not_found",
            Self::FlagInactive => "flag_inactive",
            Self::GroupAggregatedFlag => "group_aggregated_flag",
            Self::VersionConflict { .. } => "version_conflict",
            Self::Upstream(_) => "upstream_error",
        }
    }
}

impl IntoResponse for BatchFlagEvaluationError {
    fn into_response(self) -> Response {
        let (status, error, detail, actual_version) = match self {
            Self::Unauthorized => (
                StatusCode::UNAUTHORIZED,
                "unauthorized",
                "Missing or invalid internal request token".to_string(),
                None,
            ),
            Self::InvalidRequest(detail) => {
                (StatusCode::BAD_REQUEST, "invalid_request", detail, None)
            }
            Self::PayloadTooLarge => (
                StatusCode::PAYLOAD_TOO_LARGE,
                "payload_too_large",
                format!("Request body exceeds the {MAX_BATCH_BODY_BYTES}-byte limit"),
                None,
            ),
            Self::FlagNotFound => (
                StatusCode::NOT_FOUND,
                "flag_not_found",
                "No flag with this key exists for this team".to_string(),
                None,
            ),
            Self::FlagInactive => (
                StatusCode::BAD_REQUEST,
                "flag_inactive",
                "Flag is not active".to_string(),
                None,
            ),
            Self::GroupAggregatedFlag => (
                StatusCode::BAD_REQUEST,
                "group_aggregated_flag",
                "Group-aggregated flags are not supported for batch evaluation".to_string(),
                None,
            ),
            Self::VersionConflict { expected, actual } => (
                StatusCode::CONFLICT,
                "version_conflict",
                format!("Flag version is {actual}, expected {expected}; the flag changed during cohort generation"),
                Some(actual),
            ),
            Self::Upstream(e) => {
                // Delegate status selection to FlagError's own mapping, but keep the
                // JSON envelope consistent with the other variants.
                let status = StatusCode::from_u16(e.status_code())
                    .unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
                (status, "upstream_error", e.to_string(), None)
            }
        };

        let mut body = serde_json::json!({ "error": error, "detail": detail });
        if let Some(actual) = actual_version {
            body["actual_version"] = serde_json::json!(actual);
        }
        (status, Json(body)).into_response()
    }
}

/// One row from the person page scan: the person plus its deterministic
/// (minimum `posthog_persondistinctid.id`) distinct_id, when one exists.
#[derive(Debug, FromRow)]
struct PersonScanRow {
    id: PersonId,
    uuid: Uuid,
    distinct_id: Option<String>,
}

/// Scans one page of a team's persons in `id` order, attaching the distinct_id with the
/// lowest `posthog_persondistinctid.id` (a deterministic choice). Persons with no
/// distinct_ids come back with `distinct_id = NULL` and still advance the cursor, so a
/// run of distinct_id-less persons cannot stall paging.
async fn scan_persons_page(
    reader: PostgresReader,
    team_id: i32,
    cursor: i64,
    limit: i64,
) -> Result<Vec<PersonScanRow>, FlagError> {
    let mut conn =
        get_connection_with_metrics(&reader, "persons_reader", "batch_eval_person_scan").await?;

    // Sort-free PK range scan on the partitioned persons table; the lateral subquery is
    // covered by the existing person_id index on posthog_persondistinctid.
    let query = r#"
        SELECT p.id, p.uuid, d.distinct_id
        FROM posthog_person p
        LEFT JOIN LATERAL (
            SELECT pd.distinct_id
            FROM posthog_persondistinctid pd
            WHERE pd.person_id = p.id
              AND pd.team_id = p.team_id
            ORDER BY pd.id
            LIMIT 1
        ) d ON true
        WHERE p.team_id = $1
          AND p.id > $2
        ORDER BY p.id
        LIMIT $3
    "#;

    sqlx::query_as::<_, PersonScanRow>(query)
        .bind(team_id)
        .bind(cursor)
        .bind(limit)
        .fetch_all(&mut *conn)
        .await
        .map_err(|e| {
            warn!(team_id, cursor, "Batch eval person scan failed: {e}");
            FlagError::Internal(format!("person scan query failed: {e}"))
        })
}

/// Fetches the team's flags fresh from Postgres and locates the target flag by key.
/// Returns the full flag set (needed for flag-dependency evaluation) and the target's index.
async fn fetch_flags_with_target(
    client: PostgresReader,
    team_id: i32,
    flag_key: &str,
) -> Result<(Vec<FeatureFlag>, usize), BatchFlagEvaluationError> {
    let flags = FeatureFlagList::from_pg(client, team_id)
        .await
        .map_err(BatchFlagEvaluationError::Upstream)?;
    let target_index = flags
        .iter()
        .position(|f| f.key == flag_key)
        .ok_or(BatchFlagEvaluationError::FlagNotFound)?;
    Ok((flags, target_index))
}

/// The request is a small JSON object (~200 bytes typical), so 64 KiB is generous
/// while protecting against oversized payloads.
pub const MAX_BATCH_BODY_BYTES: usize = 64 * 1024;

pub async fn batch_flag_evaluation(
    State(state): State<router::State>,
    headers: HeaderMap,
    body: Body,
) -> Result<Json<BatchFlagEvaluationResponse>, BatchFlagEvaluationError> {
    let timer = common_metrics::timing_guard(FLAG_BATCH_EVAL_TIME, &[]);

    // Authenticate before reading the body so unauthenticated clients cannot
    // tie up resources by streaming large or slow request bodies.
    if !is_internal_request_inner(state.config.internal_request_token.as_deref(), &headers) {
        let outcome = "unauthorized";
        inc(
            FLAG_BATCH_EVAL_REQUESTS_COUNTER,
            &[("outcome".to_string(), outcome.to_string())],
            1,
        );
        timer.label("outcome", outcome).fin();
        return Err(BatchFlagEvaluationError::Unauthorized);
    }

    let result = match axum::body::to_bytes(body, MAX_BATCH_BODY_BYTES).await {
        Ok(body_bytes) => handle_batch_flag_evaluation(&state, &body_bytes).await,
        // `to_bytes` wraps the underlying http_body_util error; walk the full source
        // chain (not just the first level) to classify an oversized body as 413, the
        // same way `body_read_metrics::record_body_read` does for `/flags`.
        Err(e) => {
            let too_large = std::iter::successors(std::error::Error::source(&e), |s| s.source())
                .any(|s| s.is::<http_body_util::LengthLimitError>());
            Err(if too_large {
                BatchFlagEvaluationError::PayloadTooLarge
            } else {
                BatchFlagEvaluationError::InvalidRequest(format!("body read error: {e}"))
            })
        }
    };

    let outcome = match &result {
        Ok(_) => "success",
        Err(e) => e.outcome_label(),
    };
    inc(
        FLAG_BATCH_EVAL_REQUESTS_COUNTER,
        &[("outcome".to_string(), outcome.to_string())],
        1,
    );
    timer.label("outcome", outcome).fin();

    result.map(Json)
}

async fn handle_batch_flag_evaluation(
    state: &router::State,
    body: &[u8],
) -> Result<BatchFlagEvaluationResponse, BatchFlagEvaluationError> {
    let request: BatchFlagEvaluationRequest = serde_json::from_slice(body)
        .map_err(|e| BatchFlagEvaluationError::InvalidRequest(format!("invalid JSON body: {e}")))?;

    let max_limit = state.config.batch_flag_eval_max_limit;
    let limit = request.limit.unwrap_or(DEFAULT_LIMIT.min(max_limit));
    if limit < 1 || limit > max_limit {
        return Err(BatchFlagEvaluationError::InvalidRequest(format!(
            "limit must be between 1 and {max_limit}"
        )));
    }
    if request.flag_key.is_empty() {
        return Err(BatchFlagEvaluationError::InvalidRequest(
            "flag_key must not be empty".to_string(),
        ));
    }
    if request.cursor < 0 {
        return Err(BatchFlagEvaluationError::InvalidRequest(
            "cursor must not be negative".to_string(),
        ));
    }

    // Read the flag set from the replica first; on a version mismatch, re-fetch from the
    // primary to rule out replica lag before declaring a conflict. No evaluation happens
    // under the wrong version.
    let (mut flags_vec, mut target_index) = fetch_flags_with_target(
        state.database_pools.non_persons_reader.clone(),
        request.team_id,
        &request.flag_key,
    )
    .await?;

    let expected_version = request.expected_version.unwrap_or(0);
    if flags_vec[target_index].version.unwrap_or(0) != expected_version {
        (flags_vec, target_index) = fetch_flags_with_target(
            state.database_pools.non_persons_writer.clone(),
            request.team_id,
            &request.flag_key,
        )
        .await?;
        let actual = flags_vec[target_index].version.unwrap_or(0);
        if actual != expected_version {
            return Err(BatchFlagEvaluationError::VersionConflict {
                expected: expected_version,
                actual,
            });
        }
    }

    let target = &flags_vec[target_index];
    // The Django caller already returns [] for group-aggregated and inactive flags
    // without calling us; these guards are defensive.
    if target.get_group_type_index().is_some() {
        return Err(BatchFlagEvaluationError::GroupAggregatedFlag);
    }
    if !target.active {
        return Err(BatchFlagEvaluationError::FlagInactive);
    }
    let target_key = target.key.clone();

    // Mirror the live pipeline's exclusion of inactive flags so dependency conditions on
    // them pre-seed as false instead of evaluating.
    let filtered_out_flag_ids: HashSet<i32> = flags_vec
        .iter()
        .filter(|f| !f.active)
        .map(|f| f.id)
        .collect();

    // Real dependency stages (like the hypercache path) rather than the PG fallback's
    // single stage, so flag-dependency conditions on the target flag evaluate correctly.
    let evaluation_metadata = compute_flag_dependencies(&flags_vec).unwrap_or_else(|e| {
        warn!(
            team_id = request.team_id,
            "Batch eval falling back to single-stage flag metadata: {e}"
        );
        EvaluationMetadata::single_stage(&flags_vec)
    });

    let flag_list = FeatureFlagList {
        flags: PreparedFlags::seal(flags_vec),
        filtered_out_flag_ids,
        evaluation_metadata: Arc::new(evaluation_metadata),
        cohorts: None,
    };

    // The service exposes no dedicated non-critical persons pool, so the scan shares the
    // live persons reader.
    let rows = scan_persons_page(
        state.database_pools.persons_reader.clone(),
        request.team_id,
        request.cursor,
        limit,
    )
    .await
    .map_err(BatchFlagEvaluationError::Upstream)?;

    let next_cursor = if rows.len() as i64 == limit {
        rows.last().map(|r| r.id)
    } else {
        None
    };

    let pg_router = PostgresRouter::new(
        state.database_pools.persons_reader.clone(),
        state.database_pools.persons_writer.clone(),
        state.database_pools.non_persons_reader.clone(),
        state.database_pools.non_persons_writer.clone(),
    );
    let enable_realtime_cohort_evaluation = state
        .config
        .realtime_cohort_evaluation_team_ids
        .includes_team(request.team_id);

    // Read the team's timezone from Postgres so naive datetime filter values (IS_DATE_* and
    // relative dates) are interpreted in the team's local time, matching live `/flags`
    // evaluation and HogQL/ClickHouse cohort membership. The live path reads the same
    // `team.timezone`; this is one PK lookup per page, negligible against the per-page
    // person scan. Falls back to UTC for an unrecognized timezone string.
    let team = state
        .flag_service()
        .get_team_by_id(request.team_id)
        .await
        .map_err(BatchFlagEvaluationError::Upstream)?;
    let team_timezone = team.parsed_timezone();

    let mut matched_person_uuids: Vec<Uuid> = Vec::new();
    let mut errors_count: u64 = 0;

    for row in rows {
        // Persons with zero distinct_ids (almost-deleted) are skipped.
        let Some(distinct_id) = row.distinct_id else {
            record_person_outcome("skipped_no_distinct_id");
            continue;
        };

        // Per-person so each evaluation is independently traceable in canonical logs.
        let request_id = Uuid::new_v4();

        let mut matcher = FeatureFlagMatcher::new(
            distinct_id,
            None,
            request.team_id,
            pg_router.clone(),
            state.cohort_cache_manager.clone(),
            state.group_type_cache_manager.clone(),
            None,
        )
        .with_cohort_membership_provider(state.cohort_membership_provider.clone())
        .with_realtime_cohort_evaluation(enable_realtime_cohort_evaluation)
        .with_rayon_dispatcher(state.rayon_dispatcher.clone())
        .with_parallel_eval_threshold(state.config.parallel_eval_threshold)
        // Read-only: experience-continuity overrides are consulted but never written.
        .with_skip_writes(true)
        .with_timezone(team_timezone);

        let evaluation = matcher
            .evaluate_all_feature_flags(
                flag_list.clone(),
                None,
                None,
                None,
                request_id,
                Some(vec![target_key.clone()]),
                state.config.optimize_experience_continuity_lookups.0,
            )
            .await;

        match evaluation {
            Ok(response) => match response.flags.get(&target_key) {
                Some(details) if details.failed => {
                    errors_count += 1;
                    record_person_outcome("error");
                }
                Some(details) if details.enabled => {
                    matched_person_uuids.push(row.uuid);
                    record_person_outcome("matched");
                }
                Some(_) => record_person_outcome("not_matched"),
                None => {
                    warn!(
                        team_id = request.team_id,
                        flag_key = %target_key,
                        person_uuid = %row.uuid,
                        "Batch eval response missing the target flag"
                    );
                    errors_count += 1;
                    record_person_outcome("error");
                }
            },
            Err(e) => {
                warn!(
                    team_id = request.team_id,
                    flag_key = %target_key,
                    person_uuid = %row.uuid,
                    "Batch eval failed for person: {e}"
                );
                errors_count += 1;
                record_person_outcome("error");
            }
        }
    }

    Ok(BatchFlagEvaluationResponse {
        matched_person_uuids,
        next_cursor,
        errors_count,
    })
}

fn record_person_outcome(result: &str) {
    inc(
        FLAG_BATCH_EVAL_PERSONS_COUNTER,
        &[("result".to_string(), result.to_string())],
        1,
    );
}
