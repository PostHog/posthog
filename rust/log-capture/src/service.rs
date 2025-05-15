use opentelemetry_proto::tonic::collector::logs::v1::{
    logs_service_server::LogsService, ExportLogsServiceRequest, ExportLogsServiceResponse,
};
use tonic::{Request, Response, Status};
use tracing::error;

use crate::{auth::authenticate_request, clickhouse::ClickHouseWriter, config::Config};

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

        for resource_logs in export_request.resource_logs {
            // Convert resource to string for storing in ClickHouse
            let resource_str = match &resource_logs.resource {
                Some(resource) => {
                    let mut attributes = Vec::new();
                    for attr in &resource.attributes {
                        attributes.push(format!("{}={:?}", attr.key, attr.value));
                    }
                    attributes.join(", ")
                }
                None => "".to_string(),
            };

            for scope_logs in resource_logs.scope_logs {
                for log_record in scope_logs.log_records {
                    // Store log in ClickHouse
                    if let Err(e) = self
                        .clickhouse_writer
                        .insert_log(
                            team_id,
                            log_record,
                            resource_str.clone(),
                            scope_logs.scope.clone(),
                        )
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
