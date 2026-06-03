use std::{sync::Arc, time::Duration};

use common_metrics::{serve, setup_metrics_routes_with_overrides, Matcher};
use cymbal_proto::cymbal::process::v1::cymbal_process_server::CymbalProcessServer;
use tonic::transport::Server;
use tracing::{error, info};

use crate::{
    app_context::AppContext,
    config::Config,
    metric_consts::{
        BYTE_HISTOGRAM_BUCKETS, S3_FETCHED_BYTES, S3_PUT_BYTES, SOURCEMAP_EXTERNAL_BYTES,
        SYMBOL_SET_DECOMPRESSED_BYTES,
    },
    router::get_router,
    service::process::{CymbalProcessService, ProcessServiceConfig},
};

pub async fn start_server(config: Config, context: Arc<AppContext>) -> () {
    let grpc_handle = tokio::spawn(start_process_grpc_server(config.clone(), context.clone()));

    let router = get_router(context);
    let bucket_overrides: &[(Matcher, &[f64])] = &[
        (
            Matcher::Full(S3_FETCHED_BYTES.into()),
            BYTE_HISTOGRAM_BUCKETS,
        ),
        (Matcher::Full(S3_PUT_BYTES.into()), BYTE_HISTOGRAM_BUCKETS),
        (
            Matcher::Full(SOURCEMAP_EXTERNAL_BYTES.into()),
            BYTE_HISTOGRAM_BUCKETS,
        ),
        (
            Matcher::Full(SYMBOL_SET_DECOMPRESSED_BYTES.into()),
            BYTE_HISTOGRAM_BUCKETS,
        ),
    ];
    let router = setup_metrics_routes_with_overrides(router, bucket_overrides);
    let bind = format!("{}:{}", config.host, config.port);
    info!("Server started and listening on {}", bind);
    serve(router, &bind)
        .await
        .expect("failed to start serving metrics");

    grpc_handle.abort();
}

async fn start_process_grpc_server(config: Config, context: Arc<AppContext>) {
    let service_config = ProcessServiceConfig::new(config.process_grpc_stream_output_buffer);
    let service =
        CymbalProcessService::new(service_config, context.process_grpc_item_limiter.clone());

    let addr = match config.process_grpc_bind_addr.parse() {
        Ok(addr) => addr,
        Err(err) => {
            error!(
                bind = %config.process_grpc_bind_addr,
                error = %err,
                "failed to parse Cymbal process gRPC bind address"
            );
            return;
        }
    };

    info!(
        bind = %config.process_grpc_bind_addr,
        max_concurrent_streams = config.process_grpc_max_concurrent_streams,
        max_in_flight_items = config.process_grpc_max_in_flight_items,
        "Cymbal process gRPC server listening"
    );

    if let Err(err) = Server::builder()
        .http2_keepalive_interval(Some(Duration::from_secs(30)))
        .http2_keepalive_timeout(Some(Duration::from_secs(20)))
        .concurrency_limit_per_connection(config.process_grpc_max_concurrent_streams.max(1))
        .add_service(CymbalProcessServer::new(service))
        .serve(addr)
        .await
    {
        error!(error = %err, "Cymbal process gRPC server stopped with error");
    }
}
