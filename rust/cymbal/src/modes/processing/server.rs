use std::sync::Arc;

use common_metrics::{serve, setup_metrics_routes_with_overrides, Matcher};
use tracing::info;

use crate::{
    app_context::AppContext,
    metric_consts::{
        BYTE_HISTOGRAM_BUCKETS, S3_FETCHED_BYTES, S3_PUT_BYTES, SOURCEMAP_EXTERNAL_BYTES,
        SYMBOL_SET_DECOMPRESSED_BYTES,
    },
    modes::processing::config::ProcessingConfig,
    router::get_router,
};

pub async fn start_server(config: ProcessingConfig, context: Arc<AppContext>) -> () {
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
}
