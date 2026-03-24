use chrono::DateTime;
use uuid::Uuid;

use super::response::Response;
use super::types::CaptureV1Batch;
use crate::v1::context::Context;
use crate::v1::Error;

pub async fn process_batch(context: &Context, batch: CaptureV1Batch) -> Result<Response, Error> {
    // TODO: chatty on purpose, for now
    tracing::info!(ctx = ?context, "process_batch called");

    validate_batch(&batch)?;

    unimplemented!()
}

fn validate_batch(batch: &CaptureV1Batch) -> Result<(), Error> {
    DateTime::parse_from_rfc3339(&batch.created_at).map_err(|_| {
        Error::InvalidBatch(format!(
            "created_at is not valid RFC 3339: {}",
            batch.created_at
        ))
    })?;

    for event in &batch.batch {
        Uuid::parse_str(&event.uuid).map_err(|_| Error::MissingEventUuid)?;
    }

    Ok(())
}
