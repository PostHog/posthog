use crate::log_record::KafkaLogRow;
use crate::{auth::authenticate_request, config::Config};
use opentelemetry_proto::tonic::collector::logs::v1::{
    logs_service_server::LogsService, ExportLogsServiceRequest, ExportLogsServiceResponse,
};
use opentelemetry_proto::tonic::collector::trace::v1::trace_service_server::TraceService;
use opentelemetry_proto::tonic::collector::trace::v1::{
    ExportTraceServiceRequest, ExportTraceServiceResponse,
};

use crate::kafka::KafkaSink;

use tonic::{Request, Response, Status};
use tracing::{debug, error};

#[derive(Clone)]
pub struct Service {
    config: Config,
    sink: KafkaSink,
}

impl Service {
    pub async fn new(config: Config, kafka_sink: KafkaSink) -> Result<Self, anyhow::Error> {
        Ok(Self {
            config,
            sink: kafka_sink,
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
                return Err(*status);
            }
        };

        let team_id = match team_id.parse::<i32>() {
            Ok(id) => id,
            Err(e) => {
                error!("Failed to parse team_id '{team_id}' as i32: {e}");
                return Err(Status::invalid_argument(format!(
                    "Invalid team_id format: {team_id}"
                )));
            }
        };

        let export_request = request.into_inner();
        let mut rows: Vec<KafkaLogRow> = Vec::new();
        for resource_logs in export_request.resource_logs {
            for scope_logs in resource_logs.scope_logs {
                for log_record in scope_logs.log_records {
                    let row = match KafkaLogRow::new(
                        team_id,
                        log_record,
                        resource_logs.resource.clone(),
                        scope_logs.scope.clone(),
                    ) {
                        Ok(row) => row,
                        Err(e) => {
                            error!("Failed to create LogRow: {e}");
                            continue;
                        }
                    };
                    rows.push(row);
                }
            }
        }

        if let Err(e) = self.sink.write(team_id, rows).await {
            error!("Failed to send logs to Kafka: {}", e);
        } else {
            debug!("Successfully sent logs to Kafka");
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
