//! Lifecycle sagas: person-destroying operations run as durable sagas with
//! all state in the lifecycle_op tables on the persons primary. The merge
//! saga's step handler lives in [`merge`]; the entrance that drives it
//! lives in [`crate::service::merge`].
//!
//! The [`engine`] carries everything op types share (op persistence, lease,
//! drive loop, sweeper, GC); [`delete`] and [`merge`] carry their sagas'
//! step handlers.

pub mod delete;
pub mod engine;
pub mod merge;
pub mod validation;

use std::sync::Arc;

use tonic::{Request, Response, Status};

use personhog_proto::personhog::lifecycle::v1::person_hog_lifecycle_server::PersonHogLifecycle;
use personhog_proto::personhog::lifecycle::v1::{
    DeletePersonOutcome, DeletePersonResult, DeletePersonsRequest, DeletePersonsResponse,
};

use crate::leader::LifecycleLeader;
use crate::lifecycle::delete::{
    DeleteDriver, DeleteOutcome, OUTCOME_DELETED, OUTCOME_NOT_FOUND, OUTCOME_SKIPPED_CONFLICT,
};
use crate::lifecycle::engine::{Engine, OpRow, SagaError};
use crate::lifecycle::validation::validate_delete_persons;

pub struct PersonHogLifecycleService {
    engine: Arc<Engine>,
    delete_driver: DeleteDriver,
}

impl PersonHogLifecycleService {
    pub fn new(
        engine: Arc<Engine>,
        leader: Arc<dyn LifecycleLeader>,
        tables: crate::config::IdentityTables,
    ) -> Self {
        Self {
            engine,
            delete_driver: DeleteDriver::new(leader, tables),
        }
    }
}

/// Translate a terminal op row's recorded outcome into the proto response.
/// The recorded outcome is the single source of truth — a retried call gets
/// byte-for-byte the same answer the original run recorded.
// tonic Status is a large Err variant; boxing here would diverge from the
// tonic handler signatures this feeds into.
#[allow(clippy::result_large_err)]
fn delete_response(row: &OpRow) -> Result<DeletePersonsResponse, Status> {
    let Some(outcome) = &row.outcome else {
        return Err(Status::internal(format!(
            "op {} is terminal but has no recorded outcome",
            row.op_id
        )));
    };
    let outcome: DeleteOutcome = serde_json::from_value(outcome.clone())
        .map_err(|e| Status::internal(format!("op {} outcome is malformed: {e}", row.op_id)))?;

    let results = outcome
        .results
        .into_iter()
        .map(|record| {
            let outcome = match record.outcome.as_str() {
                OUTCOME_DELETED => DeletePersonOutcome::Deleted,
                OUTCOME_SKIPPED_CONFLICT => DeletePersonOutcome::SkippedConflict,
                OUTCOME_NOT_FOUND => DeletePersonOutcome::NotFound,
                _ => DeletePersonOutcome::Unspecified,
            };
            DeletePersonResult {
                person_id: record.person_id,
                outcome: outcome.into(),
            }
        })
        .collect();

    Ok(DeletePersonsResponse {
        op_id: row.op_id.to_string(),
        results,
    })
}

#[tonic::async_trait]
impl PersonHogLifecycle for PersonHogLifecycleService {
    async fn delete_persons(
        &self,
        request: Request<DeletePersonsRequest>,
    ) -> Result<Response<DeletePersonsResponse>, Status> {
        let request = request.into_inner();
        let op_id = validate_delete_persons(&request)?;

        let frozen = serde_json::to_value(delete::DeleteRequest {
            person_ids: request.person_ids,
        })
        .map_err(|e| Status::internal(format!("failed to freeze request: {e}")))?;

        let row = self
            .engine
            .execute(&self.delete_driver, op_id, request.team_id, &frozen)
            .await
            .map_err(|err| {
                if matches!(err, SagaError::Db(_) | SagaError::CorruptState(_)) {
                    tracing::error!(op_id = %op_id, error = %err, "DeletePersons failed");
                }
                Status::from(err)
            })?;

        Ok(Response::new(delete_response(&row)?))
    }
}
