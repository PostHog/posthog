use std::collections::HashSet;
use std::sync::LazyLock;

use tonic::Status;
use uuid::Uuid;

use personhog_common::persons::COOKIELESS_SENTINEL_VALUE;
use personhog_proto::personhog::identity::v1::MergePersonsRequest;
use personhog_proto::personhog::lifecycle::v1::DeletePersonsRequest;

use crate::service::validation::rejected;

/// Maximum person ids per DeletePersons request. Matches the identity
/// get-or-create batch cap; GDPR jobs chunk above this.
pub const MAX_DELETE_BATCH_SIZE: usize = 250;

/// Maximum sources per MergePersons request — the same per-op cap.
pub const MAX_MERGE_BATCH_SIZE: usize = 250;

const MAX_DISTINCT_ID_LENGTH: usize = 400;

/// Longer than the `posthog_persondistinctid.distinct_id` column admits.
/// The limit counts characters, not bytes — `varchar(400)` counts
/// characters, and capture emits multibyte ids whose UTF-8 length passes
/// 400 bytes well inside its own 200-character cap. An oversized id can
/// never exist in storage, so it can never resolve and must never be
/// attached; as a merge SOURCE it settles per-source (skipped_illegal)
/// rather than failing the batch.
pub fn is_distinct_id_oversized(id: &str) -> bool {
    id.chars().count() > MAX_DISTINCT_ID_LENGTH
}

// Mirrors ingestion's isDistinctIdIllegal (nodejs/src/common/persons/
// person-utils.ts): generic ids that stem from a bug or mistake must never
// drive a merge. Some are illegal in any casing, others only exactly as
// cased ('NaN' but not 'nan'), and both sets also match wrapped in single
// or double quotes.
const BARE_CASE_INSENSITIVE_ILLEGAL_IDS: &[&str] = &[
    "anonymous",
    "guest",
    "distinctid",
    "distinct_id",
    "id",
    "not_authenticated",
    "email",
    "undefined",
    "true",
    "false",
];
const BARE_CASE_SENSITIVE_ILLEGAL_IDS: &[&str] = &[
    "[object Object]",
    "NaN",
    "None",
    "none",
    "null",
    "0",
    "undefined",
    COOKIELESS_SENTINEL_VALUE,
];

fn with_quoted(ids: &[&str]) -> HashSet<String> {
    ids.iter()
        .flat_map(|id| [id.to_string(), format!("'{id}'"), format!("\"{id}\"")])
        .collect()
}

static CASE_INSENSITIVE_ILLEGAL_IDS: LazyLock<HashSet<String>> =
    LazyLock::new(|| with_quoted(BARE_CASE_INSENSITIVE_ILLEGAL_IDS));
static CASE_SENSITIVE_ILLEGAL_IDS: LazyLock<HashSet<String>> =
    LazyLock::new(|| with_quoted(BARE_CASE_SENSITIVE_ILLEGAL_IDS));

/// Whether JavaScript's `String.prototype.trim` would strip this char.
/// Deliberately not Rust's `str::trim`, which also strips U+0085: the
/// two sides must agree on which ids are illegal.
fn is_js_whitespace(c: char) -> bool {
    matches!(
        c,
        '\t' | '\u{000B}' | '\u{000C}' | ' ' | '\u{00A0}' | '\u{FEFF}' | '\u{1680}' | '\u{2000}'
            ..='\u{200A}'
                | '\u{202F}'
                | '\u{205F}'
                | '\u{3000}'
                | '\n'
                | '\r'
                | '\u{2028}'
                | '\u{2029}'
    )
}

pub fn is_distinct_id_illegal(id: &str) -> bool {
    id.trim_matches(is_js_whitespace).is_empty()
        || CASE_INSENSITIVE_ILLEGAL_IDS.contains(&id.to_lowercase())
        || CASE_SENSITIVE_ILLEGAL_IDS.contains(id)
}

/// Above i32::MAX the storage layer's `as i32` narrowing would wrap into
/// another tenant's rows.
pub fn is_team_id_valid(team_id: i64) -> bool {
    team_id > 0 && team_id <= i32::MAX as i64
}

// tonic Status is a large Err variant; boxing here would diverge from the
// tonic handler signatures these feed into.
#[allow(clippy::result_large_err)]
/// Validates the request and returns the parsed op_id.
pub fn validate_delete_persons(request: &DeletePersonsRequest) -> Result<Uuid, Status> {
    if !is_team_id_valid(request.team_id) {
        return Err(rejected(
            "team_id",
            "team_id must be a positive 32-bit integer",
        ));
    }
    if request.person_ids.is_empty() {
        return Err(rejected("person_ids_empty", "person_ids must not be empty"));
    }
    if request.person_ids.len() > MAX_DELETE_BATCH_SIZE {
        return Err(rejected(
            "batch_size",
            format!(
                "batch size {} exceeds maximum {MAX_DELETE_BATCH_SIZE}",
                request.person_ids.len()
            ),
        ));
    }
    if request.person_ids.iter().any(|&id| id <= 0) {
        return Err(rejected(
            "person_id",
            "person_ids must be positive integers",
        ));
    }
    Uuid::parse_str(&request.op_id).map_err(|_| rejected("op_id", "op_id must be a valid UUID"))
}

/// The id that made a merge request unmergeable, so the entrance warns
/// the customer about that id and no other.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UnmergeableId {
    Target,
    /// Index into `request.sources`.
    Source(usize),
}

/// A rejected merge request: the gRPC status, plus the offending id when
/// the rejection is one the customer can act on.
pub struct MergeRejection {
    pub status: Status,
    pub unmergeable: Option<UnmergeableId>,
}

impl From<Status> for MergeRejection {
    fn from(status: Status) -> Self {
        Self {
            status,
            unmergeable: None,
        }
    }
}

impl MergeRejection {
    fn unmergeable(status: Status, id: UnmergeableId) -> Self {
        Self {
            status,
            unmergeable: Some(id),
        }
    }
}

// See validate_delete_persons for why result_large_err is allowed.
#[allow(clippy::result_large_err)]
/// Validates the request and returns the parsed op_id and move_limit.
/// Illegal SOURCE distinct ids are per-source outcomes, not request
/// errors — only the target's legality gates the whole call (nothing can
/// merge into a bug).
pub fn validate_merge_persons(
    request: &MergePersonsRequest,
) -> Result<(Uuid, i64), MergeRejection> {
    if !is_team_id_valid(request.team_id) {
        return Err(rejected("team_id", "team_id must be a positive 32-bit integer").into());
    }
    if is_distinct_id_oversized(&request.target_distinct_id) {
        return Err(MergeRejection::unmergeable(
            rejected(
                "target_distinct_id_length",
                format!("target_distinct_id exceeds {MAX_DISTINCT_ID_LENGTH} characters"),
            ),
            UnmergeableId::Target,
        ));
    }
    if is_distinct_id_illegal(&request.target_distinct_id) {
        return Err(MergeRejection::unmergeable(
            rejected(
                "target_distinct_id_illegal",
                "target_distinct_id is an illegal distinct id",
            ),
            UnmergeableId::Target,
        ));
    }
    // Postgres cannot store NUL in text: an unresolved NUL target would
    // reach the establish path and fail person creation with an internal
    // error on every attempt.
    if request.target_distinct_id.contains('\u{0000}') {
        return Err(MergeRejection::unmergeable(
            rejected(
                "target_distinct_id_nul",
                "target_distinct_id must not contain NUL",
            ),
            UnmergeableId::Target,
        ));
    }
    if request.sources.is_empty() {
        return Err(rejected("sources_empty", "sources must not be empty").into());
    }
    if request.sources.len() > MAX_MERGE_BATCH_SIZE {
        return Err(rejected(
            "batch_size",
            format!(
                "batch size {} exceeds maximum {MAX_MERGE_BATCH_SIZE}",
                request.sources.len()
            ),
        )
        .into());
    }
    let mut seen = HashSet::with_capacity(request.sources.len());
    for (index, source) in request.sources.iter().enumerate() {
        // NUL is a whole-request reject where oversized ids are a
        // per-source outcome: Postgres cannot store NUL in text at all,
        // so the frozen op row — which must record every requested
        // source for retries — would be unwritable jsonb.
        if source.source_distinct_id.contains('\u{0000}') {
            return Err(MergeRejection::unmergeable(
                rejected(
                    "source_distinct_id_nul",
                    "source distinct ids must not contain NUL",
                ),
                UnmergeableId::Source(index),
            ));
        }
        if !seen.insert(source.source_distinct_id.as_str()) {
            return Err(rejected(
                "duplicate_source",
                format!(
                    "duplicate source distinct id: the caller must dedupe (\"{}\")",
                    source.source_distinct_id
                ),
            )
            .into());
        }
    }
    // Unlimited is not a supported mode: the flip's repoint would be an
    // unbounded statement under statement_timeout.
    let move_limit = match request.move_limit {
        Some(limit) if limit >= 1 => limit,
        Some(_) => return Err(rejected("move_limit", "move_limit must be positive").into()),
        None => return Err(rejected("move_limit", "move_limit is required").into()),
    };
    if request.created_at < 0 {
        return Err(rejected("created_at", "created_at must not be negative").into());
    }
    let op_id = Uuid::parse_str(&request.op_id)
        .map_err(|_| MergeRejection::from(rejected("op_id", "op_id must be a valid UUID")))?;
    Ok((op_id, move_limit))
}
