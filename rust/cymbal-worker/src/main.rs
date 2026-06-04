use cymbal_worker::{
    build_worker, config::Config, embedding_results::run_embedding_result_consumer,
};
use tracing::level_filters::LevelFilter;
use tracing::{error, info};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

fn setup_tracing() {
    let log_layer = tracing_subscriber::fmt::layer().with_filter(
        EnvFilter::builder()
            .with_default_directive(LevelFilter::INFO.into())
            .from_env_lossy(),
    );
    tracing_subscriber::registry().with(log_layer).init();
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    setup_tracing();

    let config = Config::init_with_defaults()?;
    info!(
        namespace = %config.temporal_namespace,
        task_queue = %config.temporal_task_queue,
        "starting cymbal Temporal worker"
    );

    let mut worker = build_worker(&config).await?;
    let worker_config = config.clone();

    tokio::try_join!(
        async move {
            if let Err(error) = worker.run().await {
                error!(?error, "cymbal Temporal worker stopped with an error");
                return Err(error);
            }
            Ok(())
        },
        run_embedding_result_consumer(worker_config),
    )?;

    Ok(())
}
