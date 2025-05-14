use opentelemetry_proto::tonic::collector::logs::v1::{
    logs_service_server::{LogsService, LogsServiceServer}, // Note the Server trait
    ExportLogsServiceRequest,
    ExportLogsServiceResponse,
};
use std::net::SocketAddr;
use tonic::{transport::Server, Request, Response, Status};

use axum::{routing::get, Router};
// For easy request body deserialization
use common_metrics::{serve, setup_metrics_routes};
use log_capture::clickhouse::ClickHouseWriter;
use log_capture::config::Config;
use std::future::ready;
use std::sync::Arc;

use health::HealthRegistry;
use serde_json::json;
use tracing::{error, info};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};
mod auth;

common_alloc::used!();

fn setup_tracing() {
    let log_layer: tracing_subscriber::filter::Filtered<
        tracing_subscriber::fmt::Layer<tracing_subscriber::Registry>,
        EnvFilter,
        tracing_subscriber::Registry,
    > = tracing_subscriber::fmt::layer().with_filter(EnvFilter::from_default_env());
    tracing_subscriber::registry().with(log_layer).init();
}

pub async fn index() -> &'static str {
    "log hog hogs logs

.|||||||||.
|||||||||||||  gimme your logs
|||||||||||' .\\
`||||||||||_,__o
"
}

// Define our service implementation
pub struct MyLogsService {
    config: Arc<Config>,
    clickhouse_writer: Arc<ClickHouseWriter>,
}

impl MyLogsService {
    pub async fn new(config: Arc<Config>) -> Result<Self, anyhow::Error> {
        let clickhouse_writer = ClickHouseWriter::new(config.clone()).await?;
        Ok(Self {
            config,
            clickhouse_writer: Arc::new(clickhouse_writer),
        })
    }
}

#[tonic::async_trait]
impl LogsService for MyLogsService {
    async fn export(
        &self,
        request: Request<ExportLogsServiceRequest>,
    ) -> Result<Response<ExportLogsServiceResponse>, Status> {
        // Extract team_id from JWT token in the Authorization header
        let team_id = match auth::authenticate_request(&request, &self.config.jwt_secret) {
            Ok(team_id) => team_id,
            Err(status) => {
                return Err(status);
            }
        };

        // Convert team_id string to i64 for ClickHouse
        let team_id_i64 = match team_id.parse::<i64>() {
            Ok(id) => id,
            Err(e) => {
                error!("Failed to parse team_id '{}' as i64: {}", team_id, e);
                return Err(Status::invalid_argument(format!(
                    "Invalid team_id format: {}",
                    team_id
                )));
            }
        };

        info!("Authenticated request for team_id: {}", team_id);

        let export_request = request.into_inner();
        info!(
            "Received OTLP gRPC logs request with {} resource logs for team_id: {}",
            export_request.resource_logs.len(),
            team_id
        );

        for resource_logs in export_request.resource_logs {
            // Convert resource to string for storing in ClickHouse
            let resource_str = json!(&resource_logs.resource).to_string();

            for scope_logs in resource_logs.scope_logs {
                let scope_ref = scope_logs.scope.as_ref();

                if let Some(scope) = scope_ref {
                    info!(
                        "Processing scope: {} ({}) for team_id {}",
                        scope.name, scope.version, team_id
                    );
                }

                info!(
                    "Processing {} log records in this scope for team_id {}.",
                    scope_logs.log_records.len(),
                    team_id
                );

                for log_record in scope_logs.log_records {
                    // Store log in ClickHouse
                    if let Err(e) = self
                        .clickhouse_writer
                        .insert_log(team_id_i64, &log_record, &resource_str, scope_ref)
                        .await
                    {
                        error!("Failed to insert log into ClickHouse: {}", e);
                        // Continue processing other logs even if one fails
                    }
                }
            }
        }

        // A successful OTLP export expects an ExportLogsServiceResponse.
        let response = ExportLogsServiceResponse {
            partial_success: None,
        };
        Ok(Response::new(response))
    }
}

#[tokio::main]
async fn main() {
    setup_tracing();
    info!("Starting up...");

    let config = Config::init_with_defaults().unwrap();
    let health_registry = HealthRegistry::new("liveness");
    let config_arc = Arc::new(config);

    let config_clone = config_arc.clone();
    let router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route(
            "/_liveness",
            get(move || ready(health_registry.get_status())),
        );
    let router = setup_metrics_routes(router);
    let bind = format!("{}:{}", config_clone.host, config_clone.port);
    println!("Healthcheck listening on {}", bind);
    let server = serve(router, &bind);

    let addr = SocketAddr::from(([0, 0, 0, 0], 4317)); // Standard OTLP gRPC port

    // Initialize ClickHouse writer and logs service
    let logs_service = match MyLogsService::new(config_arc).await {
        Ok(service) => service,
        Err(e) => {
            error!("Failed to initialize log service: {}", e);
            panic!("Could not start log capture service: {}", e);
        }
    };

    println!("OTLP gRPC server listening on {}", addr);
    println!("JWT Authentication enabled - team_id will be extracted from Authorization header");
    println!("Logs will be stored in ClickHouse");

    Server::builder()
        .add_service(LogsServiceServer::new(logs_service))
        .serve(addr)
        .await
        .unwrap();
    server.await;
}
