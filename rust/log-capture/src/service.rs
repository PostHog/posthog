use crate::log_record::LogRow;
use crate::{auth::authenticate_request, clickhouse::ClickHouseWriter, config::Config};
use opentelemetry_proto::tonic::collector::logs::v1::{
    logs_service_server::LogsService, ExportLogsServiceRequest, ExportLogsServiceResponse,
};
use opentelemetry_proto::tonic::collector::trace::v1::trace_service_server::TraceService;
use opentelemetry_proto::tonic::collector::trace::v1::{
    ExportTraceServiceRequest, ExportTraceServiceResponse,
};

use tonic::{Request, Response, Status};
use tracing::error;

#[derive(Clone)]
pub struct Service {
    config: Config,
    clickhouse_writer: ClickHouseWriter,
}

impl Service {
    pub async fn new(config: Config) -> Result<Self, anyhow::Error> {
        let clickhouse_writer = ClickHouseWriter::new(&config).await?;
        Ok(Self {
            config,
            clickhouse_writer,
        })
    }
}

#[tonic::async_trait]
impl LogsService for Service {
    async fn export(
        &self,
        request: Request<ExportLogsServiceRequest>,
    ) -> Result<Response<ExportLogsServiceResponse>, Status> {
        // Extract team_id from JWT token in the Authorization header
        let team_id = match authenticate_request(&request, &self.config.jwt_secret) {
            Ok(team_id) => team_id,
            Err(status) => {
                return Err(status);
            }
        };

        let team_id = match team_id.parse::<i32>() {
            Ok(id) => id,
            Err(e) => {
                error!("Failed to parse team_id '{}' as i32: {}", team_id, e);
                return Err(Status::invalid_argument(format!(
                    "Invalid team_id format: {}",
                    team_id
                )));
            }
        };

        let export_request = request.into_inner();

        let mut insert = match self.clickhouse_writer.client.insert("logs") {
            Ok(insert) => insert,
            Err(e) => {
                error!("Failed to create ClickHouse insert: {}", e);
                return Err(Status::internal(format!(
                    "Failed to create ClickHouse insert: {}",
                    e
                )));
            }
        };
        for resource_logs in export_request.resource_logs {
            // Convert resource to string for storing in ClickHouse
            for scope_logs in resource_logs.scope_logs {
                for log_record in scope_logs.log_records {
                    let row = match LogRow::new(
                        team_id,
                        log_record,
                        resource_logs.resource.clone(),
                        scope_logs.scope.clone(),
                    ) {
                        Ok(row) => row,
                        Err(e) => {
                            error!("Failed to create LogRow: {}", e);
                            continue;
                        }
                    };

                    if let Err(e) = insert.write(&row).await {
                        error!("Failed to insert log into ClickHouse: {}", e);
                        // Continue processing other logs even if one fails
                    }
                }
            }
        }
        if let Err(e) = insert.end().await {
            error!("Failed to end ClickHouse insert: {}", e);
        }

        // A successful OTLP export expects an ExportLogsServiceResponse.
        let response = ExportLogsServiceResponse {
            partial_success: None,
        };
        Ok(Response::new(response))
    }
}

#[tonic::async_trait]
impl TraceService for Service {
    async fn export(
        &self,
        _request: Request<ExportTraceServiceRequest>,
    ) -> Result<Response<ExportTraceServiceResponse>, Status> {
        let response = ExportTraceServiceResponse {
            partial_success: None,
        };
        Ok(Response::new(response))
    }
}
