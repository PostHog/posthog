use std::sync::Arc;

use axum::extract::State;
use axum::http::StatusCode;
use axum::routing::{get, post};
use axum::{Json, Router};
use kafka_manager_types::HealthReport;
use metrics::counter;

use crate::state::{FleetSnapshot, FleetState};

pub fn router(state: Arc<FleetState>) -> Router {
    Router::new()
        .route("/v1/health-reports", post(ingest_report))
        .route("/v1/fleet", get(fleet_snapshot))
        .with_state(state)
}

async fn ingest_report(
    State(state): State<Arc<FleetState>>,
    Json(report): Json<HealthReport>,
) -> StatusCode {
    let deployment: Arc<str> = Arc::from(report.deployment.as_str());
    counter!("kafka_manager_reports_received_total", "deployment" => deployment).increment(1);
    state.ingest(report);
    StatusCode::NO_CONTENT
}

async fn fleet_snapshot(State(state): State<Arc<FleetState>>) -> Json<FleetSnapshot> {
    Json(state.snapshot())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum_test_helper::TestClient;
    use kafka_manager_types::DeliveryCounts;
    use std::time::Duration;

    #[tokio::test]
    async fn report_round_trips_into_fleet_snapshot() {
        let state = Arc::new(FleetState::new(Duration::from_secs(60)));
        let client = TestClient::new(router(state));

        let report = HealthReport {
            pod: "capture-abc".to_string(),
            deployment: "capture".to_string(),
            delivery: DeliveryCounts {
                ok: 42,
                ..Default::default()
            },
            producer: None,
        };
        let response = client.post("/v1/health-reports").json(&report).send().await;
        assert_eq!(response.status(), StatusCode::NO_CONTENT);

        let response = client.get("/v1/fleet").send().await;
        assert_eq!(response.status(), StatusCode::OK);
        let snapshot: serde_json::Value = response.json().await;
        assert_eq!(snapshot["deployments"][0]["pods"][0]["pod"], "capture-abc");
        assert_eq!(snapshot["deployments"][0]["pods"][0]["delivery"]["ok"], 42);
    }

    #[tokio::test]
    async fn malformed_report_is_rejected_not_fatal() {
        let state = Arc::new(FleetState::new(Duration::from_secs(60)));
        let client = TestClient::new(router(state));

        let response = client
            .post("/v1/health-reports")
            .header("content-type", "application/json")
            .body("{\"nope\": true}")
            .send()
            .await;
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    }
}
