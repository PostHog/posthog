use tonic::Status;
use uuid::Uuid;

use personhog_proto::personhog::lifecycle::v1::DeletePersonsRequest;

/// Maximum person ids per DeletePersons request. Matches the identity
/// get-or-create batch cap; GDPR jobs chunk above this.
pub const MAX_DELETE_BATCH_SIZE: usize = 250;

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
