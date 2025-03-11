use std::sync::Arc;

use common_types::ClickHouseEvent;

use crate::{
    app_context::AppContext,
    error::{EventError, PipelineResult},
};

pub async fn handle_errors(
    buffer: Vec<PipelineResult>,
    context: Arc<AppContext>,
) -> Vec<ClickHouseEvent> {
    let mut out = Vec::with_capacity(buffer.len());

    for result in buffer {
        match result {
            Ok(event) => out.push(event),
            Err(err) => report_error(context.clone(), err).await,
        }
    }

    out
}

pub async fn report_error(_context: Arc<AppContext>, _error: EventError) {
    // TODO - I don't actually know what's needed here - most of the errors
    // below don't really require any handling beyond just dropping the event,
    // and the ones that do we emit a warning for, I think.
    // match error {
    //     EventError::WrongEventType(_, uuid) => todo!(),
    //     EventError::NoProperties(uuid) => todo!(),
    //     EventError::InvalidProperties(uuid, _) => todo!(),
    //     EventError::NoExceptionList(uuid) => todo!(),
    //     EventError::EmptyExceptionList(uuid) => todo!(),
    //     EventError::InvalidTimestamp(_, _) => todo!(),
    //     EventError::NoTeamForToken(_) => todo!(),
    //     EventError::FailedToSanitize(uuid, _) => todo!(),
    // }
}
