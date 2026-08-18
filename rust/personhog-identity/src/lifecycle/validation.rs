use std::collections::HashSet;
use std::sync::LazyLock;

use tonic::Status;
use uuid::Uuid;

use personhog_proto::personhog::identity::v1::MergePersonsRequest;
use personhog_proto::personhog::lifecycle::v1::DeletePersonsRequest;

/// Maximum person ids per DeletePersons request. Matches the identity
/// get-or-create batch cap; GDPR jobs chunk above this.
pub const MAX_DELETE_BATCH_SIZE: usize = 250;

/// Maximum sources per MergePersons request — the same per-op cap.
pub const MAX_MERGE_BATCH_SIZE: usize = 250;

/// Carried operations are leader writes issued before the durable op row
/// exists, so they are capped well below the source limit: a caller carries
/// one lane per distinct id its batch folded, not one per merge source.
pub const MAX_CARRIED_OPERATIONS: usize = 32;

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

/// Whether JavaScript's `String.prototype.trim` would strip this char:
/// ECMAScript WhiteSpace (TAB VT FF SP NBSP ZWNBSP + Space_Separator) plus
/// LineTerminator (LF CR LS PS). Deliberately NOT Rust's `str::trim`, whose
/// Unicode White_Space set also strips U+0085 (NEL) — a char JS keeps. The
/// two sides must agree on which ids are illegal, or an id one side accepts
/// draws a whole-request INVALID_ARGUMENT from the other on every delivery.
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

// tonic Status is a large Err variant; boxing here would diverge from the
// tonic handler signatures these feed into.
#[allow(clippy::result_large_err)]
/// Validates the request and returns the parsed op_id.
pub fn validate_delete_persons(request: &DeletePersonsRequest) -> Result<Uuid, Status> {
    // The persons DB stores team_id as int4 and the storage layer narrows
    // with `as i32` — an unchecked value above i32::MAX would wrap and read
    // or write another tenant's rows.
    if request.team_id <= 0 || request.team_id > i32::MAX as i64 {
        return Err(Status::invalid_argument(
            "team_id must be a positive 32-bit integer",
        ));
    }
    if request.person_ids.is_empty() {
        return Err(Status::invalid_argument("person_ids must not be empty"));
    }
    if request.person_ids.len() > MAX_DELETE_BATCH_SIZE {
        return Err(Status::invalid_argument(format!(
            "batch size {} exceeds maximum {MAX_DELETE_BATCH_SIZE}",
            request.person_ids.len()
        )));
    }
    if request.person_ids.iter().any(|&id| id <= 0) {
        return Err(Status::invalid_argument(
            "person_ids must be positive integers",
        ));
    }
    Uuid::parse_str(&request.op_id)
        .map_err(|_| Status::invalid_argument("op_id must be a valid UUID"))
}

// See validate_delete_persons for why result_large_err is allowed.
#[allow(clippy::result_large_err)]
/// Validates the request and returns the parsed op_id and move_limit.
/// Illegal SOURCE distinct ids are per-source outcomes, not request
/// errors — only the target's legality gates the whole call (nothing can
/// merge into a bug).
pub fn validate_merge_persons(request: &MergePersonsRequest) -> Result<(Uuid, i64), Status> {
    if request.team_id <= 0 || request.team_id > i32::MAX as i64 {
        return Err(Status::invalid_argument(
            "team_id must be a positive 32-bit integer",
        ));
    }
    if is_distinct_id_oversized(&request.target_distinct_id) {
        return Err(Status::invalid_argument(format!(
            "target_distinct_id exceeds {MAX_DISTINCT_ID_LENGTH} characters"
        )));
    }
    if is_distinct_id_illegal(&request.target_distinct_id) {
        return Err(Status::invalid_argument(
            "target_distinct_id is an illegal distinct id",
        ));
    }
    // Postgres cannot store NUL in text: an unresolved NUL target would
    // reach the establish path and fail person creation with an internal
    // error on every attempt.
    if request.target_distinct_id.contains('\u{0000}') {
        return Err(Status::invalid_argument(
            "target_distinct_id must not contain NUL",
        ));
    }
    if request.sources.is_empty() {
        return Err(Status::invalid_argument("sources must not be empty"));
    }
    if request.sources.len() > MAX_MERGE_BATCH_SIZE {
        return Err(Status::invalid_argument(format!(
            "batch size {} exceeds maximum {MAX_MERGE_BATCH_SIZE}",
            request.sources.len()
        )));
    }
    let mut seen = HashSet::with_capacity(request.sources.len());
    for source in &request.sources {
        // NUL is a whole-request reject where oversized ids are a
        // per-source outcome: Postgres cannot store NUL in text at all,
        // so the frozen op row — which must record every requested
        // source for retries — would be unwritable jsonb.
        if source.source_distinct_id.contains('\u{0000}') {
            return Err(Status::invalid_argument(
                "source distinct ids must not contain NUL",
            ));
        }
        if !seen.insert(source.source_distinct_id.as_str()) {
            return Err(Status::invalid_argument(format!(
                "duplicate source distinct id: the caller must dedupe (\"{}\")",
                source.source_distinct_id
            )));
        }
    }
    if request.carried_operations.len() > MAX_CARRIED_OPERATIONS {
        return Err(Status::invalid_argument(format!(
            "carried operation count {} exceeds maximum {MAX_CARRIED_OPERATIONS}",
            request.carried_operations.len()
        )));
    }
    let mut carried = HashSet::with_capacity(request.carried_operations.len());
    for entry in &request.carried_operations {
        // A merge refuses to touch an illegal distinct id, so it must not
        // become a property-write surface for one either.
        if is_distinct_id_illegal(&entry.distinct_id) {
            return Err(Status::invalid_argument(
                "a carried distinct id is an illegal distinct id",
            ));
        }
        if is_distinct_id_oversized(&entry.distinct_id) {
            return Err(Status::invalid_argument(format!(
                "a carried distinct id exceeds {MAX_DISTINCT_ID_LENGTH} characters"
            )));
        }
        if entry.distinct_id.contains('\u{0000}') {
            return Err(Status::invalid_argument(
                "carried distinct ids must not contain NUL",
            ));
        }
        // One entry per distinct id: two would race each other on the same
        // person with no defined precedence between them.
        if !carried.insert(entry.distinct_id.as_str()) {
            return Err(Status::invalid_argument(format!(
                "duplicate carried distinct id: the caller must fold them (\"{}\")",
                entry.distinct_id
            )));
        }
    }
    // Unlimited is not a supported mode: the flip's repoint would be an
    // unbounded statement under statement_timeout.
    let move_limit = match request.move_limit {
        Some(limit) if limit >= 1 => limit,
        Some(_) => return Err(Status::invalid_argument("move_limit must be positive")),
        None => return Err(Status::invalid_argument("move_limit is required")),
    };
    if request.created_at < 0 {
        return Err(Status::invalid_argument("created_at must not be negative"));
    }
    let op_id = Uuid::parse_str(&request.op_id)
        .map_err(|_| Status::invalid_argument("op_id must be a valid UUID"))?;
    Ok((op_id, move_limit))
}
