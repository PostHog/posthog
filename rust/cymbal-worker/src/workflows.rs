use std::time::Duration;

use serde::{Deserialize, Serialize};
use temporal_sdk::prelude::workflow::{execute_activity, ActivityOptions, WfContext};

use crate::activities::{
    echo_activity, print_embedding_result_activity, EchoActivityInput, ECHO_ACTIVITY_TYPE,
    PRINT_EMBEDDING_RESULT_ACTIVITY_TYPE,
};

pub const ECHO_WORKFLOW_TYPE: &str = "cymbal_echo_workflow";
pub const PROCESS_EMBEDDING_RESULT_WORKFLOW_TYPE: &str = "cymbal_process_embedding_result_workflow";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EchoWorkflowInput {
    pub message: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EchoWorkflowOutput {
    pub message: String,
}

pub async fn echo_workflow(
    ctx: WfContext,
    input: EchoWorkflowInput,
) -> Result<EchoWorkflowOutput, anyhow::Error> {
    let activity_output = execute_activity(
        &ctx,
        ActivityOptions {
            activity_type: ECHO_ACTIVITY_TYPE.to_string(),
            schedule_to_close_timeout: Some(Duration::from_secs(10)),
            ..Default::default()
        },
        echo_activity,
        EchoActivityInput {
            message: input.message,
        },
    )
    .await?;

    Ok(EchoWorkflowOutput {
        message: activity_output.message,
    })
}

pub async fn process_embedding_result_workflow(
    ctx: WfContext,
    raw_message: String,
) -> Result<(), anyhow::Error> {
    execute_activity(
        &ctx,
        ActivityOptions {
            activity_type: PRINT_EMBEDDING_RESULT_ACTIVITY_TYPE.to_string(),
            schedule_to_close_timeout: Some(Duration::from_secs(10)),
            ..Default::default()
        },
        print_embedding_result_activity,
        raw_message,
    )
    .await?;

    Ok(())
}
