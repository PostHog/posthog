use std::{str::FromStr, sync::Arc};

use anyhow::Context;
use temporal_sdk::{prelude::registry::into_workflow, prelude::worker::*, Worker};

use crate::{
    activities::{
        echo_activity, print_embedding_result_activity, ECHO_ACTIVITY_TYPE,
        PRINT_EMBEDDING_RESULT_ACTIVITY_TYPE,
    },
    config::Config,
    workflows::{
        echo_workflow, process_embedding_result_workflow, ECHO_WORKFLOW_TYPE,
        PROCESS_EMBEDDING_RESULT_WORKFLOW_TYPE,
    },
};

pub async fn build_worker(config: &Config) -> anyhow::Result<Worker> {
    let temporal_url = Url::from_str(&config.temporal_address)
        .with_context(|| format!("invalid Temporal address: {}", config.temporal_address))?;
    let server_options = sdk_client_options(temporal_url)
        .build()
        .context("failed to build Temporal client options")?;
    let client = server_options
        .connect(&config.temporal_namespace, None)
        .await
        .context("failed to connect Temporal client")?;

    let telemetry_options = TelemetryOptionsBuilder::default()
        .build()
        .context("failed to build Temporal telemetry options")?;
    let runtime = CoreRuntime::new_assume_tokio(telemetry_options)
        .context("failed to initialize Temporal runtime")?;

    let task_queue = config.temporal_task_queue.clone();
    let worker_config = WorkerConfigBuilder::default()
        .namespace(config.temporal_namespace.clone())
        .task_queue(task_queue.clone())
        .client_identity_override(Some(config.temporal_client_identity.clone()))
        .versioning_strategy(WorkerVersioningStrategy::None {
            build_id: "cymbal-worker".to_string(),
        })
        .build()
        .context("failed to build Temporal worker config")?;
    let core_worker = init_worker(&runtime, worker_config, client)
        .context("failed to initialize Temporal worker")?;

    let mut worker = Worker::new_from_core(Arc::new(core_worker), task_queue);
    worker.register_activity(ECHO_ACTIVITY_TYPE, echo_activity);
    worker.register_activity(
        PRINT_EMBEDDING_RESULT_ACTIVITY_TYPE,
        print_embedding_result_activity,
    );
    worker.register_wf(ECHO_WORKFLOW_TYPE, into_workflow(echo_workflow));
    worker.register_wf(
        PROCESS_EMBEDDING_RESULT_WORKFLOW_TYPE,
        into_workflow(process_embedding_result_workflow),
    );

    Ok(worker)
}
