use std::sync::Arc;
use std::time::Duration;

use axum::{
    extract::{Json, Query, State},
    http::StatusCode,
    routing::get,
    Router,
};
use common_database::{get_pool_with_config, PoolConfig};
use common_grpc::GrpcMetricsLayer;
use common_kafka::kafka_producer::create_kafka_producer;
use envconfig::Envconfig;
use health::HealthRegistry;
use metrics_exporter_prometheus::{Matcher, PrometheusBuilder};
use serde::{Deserialize, Serialize};
use tonic::transport::Server;
use tonic::{Code, Status};
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt::format::FmtSpan;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, Layer};
use usage_ingestion::config::Config;
use usage_ingestion::counters::{spawn_flush_task, CounterAccumulator, RedisCounterReader};
use usage_ingestion::resolver::PostgresOrganizationResolver;
use usage_ingestion::service::UsageIngestionService;
use usage_ingestion_proto::usage_ingestion::v1::{
    get_usage_counters_request, usage_ingestion_server::UsageIngestionServer, CounterGranularity,
    GetUsageCountersRequest, GetUsageCountersResponse, UsageCounterBucket, UsageCounterValue,
};

#[derive(Deserialize)]
struct HttpUsageCountersRequest {
    team_id: Option<i64>,
    organization_id: Option<String>,
    start_timestamp_ms: i64,
    end_timestamp_ms: i64,
    granularity: HttpCounterGranularity,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum HttpCounterGranularity {
    Hour,
    Day,
}

impl TryFrom<HttpUsageCountersRequest> for GetUsageCountersRequest {
    type Error = Status;

    fn try_from(request: HttpUsageCountersRequest) -> Result<Self, Self::Error> {
        let scope = match (request.team_id, request.organization_id) {
            (Some(team_id), None) => Some(get_usage_counters_request::Scope::TeamId(team_id)),
            (None, Some(organization_id)) => Some(
                get_usage_counters_request::Scope::OrganizationId(organization_id),
            ),
            _ => return Err(Status::invalid_argument("exactly one scope is required")),
        };
        Ok(Self {
            scope,
            start_timestamp_ms: request.start_timestamp_ms,
            end_timestamp_ms: request.end_timestamp_ms,
            granularity: match request.granularity {
                HttpCounterGranularity::Hour => CounterGranularity::Hour.into(),
                HttpCounterGranularity::Day => CounterGranularity::Day.into(),
            },
        })
    }
}

#[derive(Serialize)]
struct HttpUsageCountersResponse {
    buckets: Vec<HttpUsageCounterBucket>,
}

#[derive(Serialize)]
struct HttpUsageCounterBucket {
    start_timestamp_ms: i64,
    values: Vec<HttpUsageCounterValue>,
}

#[derive(Serialize)]
struct HttpUsageCounterValue {
    usage_key: String,
    unit: String,
    quantity: i64,
}

impl From<GetUsageCountersResponse> for HttpUsageCountersResponse {
    fn from(response: GetUsageCountersResponse) -> Self {
        Self {
            buckets: response
                .buckets
                .into_iter()
                .map(HttpUsageCounterBucket::from)
                .collect(),
        }
    }
}

impl From<UsageCounterBucket> for HttpUsageCounterBucket {
    fn from(bucket: UsageCounterBucket) -> Self {
        Self {
            start_timestamp_ms: bucket.start_timestamp_ms,
            values: bucket
                .values
                .into_iter()
                .map(HttpUsageCounterValue::from)
                .collect(),
        }
    }
}

impl From<UsageCounterValue> for HttpUsageCounterValue {
    fn from(value: UsageCounterValue) -> Self {
        Self {
            usage_key: value.usage_key,
            unit: value.unit,
            quantity: value.quantity,
        }
    }
}

async fn get_usage_counters_http(
    State(service): State<UsageIngestionService>,
    Query(request): Query<HttpUsageCountersRequest>,
) -> Result<Json<HttpUsageCountersResponse>, (StatusCode, Json<serde_json::Value>)> {
    let request = GetUsageCountersRequest::try_from(request).map_err(http_error)?;
    service
        .get_usage_counters(request)
        .await
        .map(HttpUsageCountersResponse::from)
        .map(Json)
        .map_err(http_error)
}

fn http_error(status: Status) -> (StatusCode, Json<serde_json::Value>) {
    let status_code = match status.code() {
        Code::InvalidArgument => StatusCode::BAD_REQUEST,
        Code::FailedPrecondition | Code::Unavailable => StatusCode::SERVICE_UNAVAILABLE,
        _ => StatusCode::INTERNAL_SERVER_ERROR,
    };
    (
        status_code,
        Json(serde_json::json!({"error": status.message()})),
    )
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Without this, the first TLS handshake to Valkey panics the task that made it, which
    // takes the counter flush loop down before it reports anything.
    rustls::crypto::aws_lc_rs::default_provider()
        .install_default()
        .expect("failed to install rustls CryptoProvider");

    let log_layer = {
        let base = tracing_subscriber::fmt::layer()
            .with_target(true)
            .with_thread_ids(true)
            .with_level(true);

        if std::env::var_os("DEBUG").is_some() {
            base.with_span_events(
                FmtSpan::NEW | FmtSpan::CLOSE | FmtSpan::ENTER | FmtSpan::EXIT | FmtSpan::ACTIVE,
            )
            .with_ansi(true)
            .boxed()
        } else {
            base.json()
                .flatten_event(true)
                .with_span_list(true)
                .with_current_span(true)
                .boxed()
        }
    };

    tracing_subscriber::registry()
        .with(log_layer)
        .with(
            EnvFilter::builder()
                .with_default_directive(LevelFilter::INFO.into())
                .from_env_lossy(),
        )
        .init();

    let config = Config::init_from_env()?;
    config.validate()?;

    let database = get_pool_with_config(
        &config.database_url,
        PoolConfig {
            max_connections: 10,
            pool_name: Some("usage-ingestion".to_string()),
            ..Default::default()
        },
    )?;
    let resolver = Arc::new(PostgresOrganizationResolver::new(database));

    let kafka_config = config.kafka_config();
    let health = Arc::new(HealthRegistry::new("usage-ingestion"));
    let producer_liveness = health
        .register("kafka_producer".to_string(), Duration::from_secs(30))
        .await;
    let producer = create_kafka_producer(&kafka_config, producer_liveness).await?;
    let grpc_max_connection_age = config.grpc_max_connection_age();
    let redis_counter_config = config.redis_counter_config();
    let counters = (!config.redis_url.is_empty()).then(|| Arc::new(CounterAccumulator::default()));
    let counter_reader = (!config.redis_url.is_empty())
        .then(|| Arc::new(RedisCounterReader::new(config.redis_url.clone())));
    let service = UsageIngestionService::new(
        producer,
        resolver,
        config.max_batch_size,
        config.topic.clone(),
        counters.as_ref().map(Arc::clone),
        counter_reader,
    );

    // Buckets only for the shared gRPC histogram, so it renders the same way personhog's does
    // and quantiles aggregate across pods. Left global, these millisecond bounds would also
    // apply to kafka_delivery_seconds, which is in seconds and would land in one bucket.
    const GRPC_DURATION_BUCKETS_MS: &[f64] = &[
        1.0, 5.0, 10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0,
    ];
    let metrics_handle = PrometheusBuilder::new()
        .set_buckets_for_metric(
            Matcher::Full("grpc_server_request_duration_ms".to_string()),
            GRPC_DURATION_BUCKETS_MS,
        )?
        .install_recorder()?;
    if let Some(accumulator) = counters {
        spawn_flush_task(
            accumulator,
            config.redis_url,
            Duration::from_secs(config.redis_flush_interval_seconds),
            redis_counter_config,
        );
    }
    let metrics_address = config.metrics_address.clone();
    let health_for_routes = health.clone();
    let usage_counter_routes = Router::new()
        .route("/v1/usage-counters", get(get_usage_counters_http))
        .with_state(service.clone());
    tokio::spawn(async move {
        let router = Router::new()
            .route(
                "/_readiness",
                get(move || {
                    let health = health_for_routes.clone();
                    async move { health.get_status() }
                }),
            )
            .route("/_liveness", get(|| async { "ok" }))
            .route(
                "/metrics",
                get(move || std::future::ready(metrics_handle.render())),
            )
            .merge(usage_counter_routes);
        let listener = tokio::net::TcpListener::bind(metrics_address)
            .await
            .expect("failed to bind usage-ingestion metrics listener");
        axum::serve(listener, router)
            .await
            .expect("usage-ingestion metrics server failed");
    });

    tracing::info!(address = %config.grpc_address, "Starting usage-ingestion gRPC service");
    // This listener is limited to trusted in-cluster callers. Add authenticated caller identity
    // before exposing it beyond that boundary because records affect tenant billing.
    // Producers pin one HTTP/2 connection for the life of the process, so a scale-up takes no
    // traffic until connections churn. A periodic GOAWAY makes them re-resolve the service.
    // ponytail: tonic 0.12 adds no jitter here. Move to client-side round-robin if the
    // synchronized reconnect shows up as a latency sawtooth.
    let mut builder = Server::builder();
    if let Some(age) = grpc_max_connection_age {
        builder = builder.max_connection_age(age);
    }
    builder
        .layer(GrpcMetricsLayer)
        .add_service(UsageIngestionServer::new(service))
        .serve(config.grpc_address.parse()?)
        .await?;
    Ok(())
}
