use serde::{Deserialize, Serialize};
use temporal_sdk::{ActContext, ActivityError};

pub const ECHO_ACTIVITY_TYPE: &str = "cymbal_echo_activity";
pub const PRINT_EMBEDDING_RESULT_ACTIVITY_TYPE: &str = "cymbal_print_embedding_result_activity";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EchoActivityInput {
    pub message: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EchoActivityOutput {
    pub message: String,
}

pub async fn echo_activity(
    _ctx: ActContext,
    input: EchoActivityInput,
) -> Result<EchoActivityOutput, ActivityError> {
    Ok(EchoActivityOutput {
        message: input.message,
    })
}

pub async fn print_embedding_result_activity(
    _ctx: ActContext,
    raw_message: String,
) -> Result<(), ActivityError> {
    println!("{raw_message}");
    Ok(())
}
