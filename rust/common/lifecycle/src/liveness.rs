//! Liveness probe handler and health strategy.

use std::collections::HashMap;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};

/// Liveness strategy: All components must be healthy, or any one suffices.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum HealthStrategy {
    All,
    Any,
}

impl std::str::FromStr for HealthStrategy {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_str() {
            "all" => Ok(HealthStrategy::All),
            "any" => Ok(HealthStrategy::Any),
            _ => Err(format!("Unknown Health Strategy: {s}, must be ALL or ANY")),
        }
    }
}

/// Per-component liveness state for the liveness probe response.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ComponentLiveness {
    Starting,
    Healthy,
    Unhealthy,
    Stalled,
}

#[derive(Clone)]
pub(crate) struct LivenessComponentRef {
    pub tag: String,
    pub healthy_until_ms: Arc<std::sync::atomic::AtomicI64>,
    #[allow(dead_code)]
    pub deadline: std::time::Duration,
}

/// Axum-compatible liveness probe handler; returns 200 if healthy per strategy, 500 with component detail otherwise.
#[derive(Clone)]
pub struct LivenessHandler {
    components: Arc<Vec<LivenessComponentRef>>,
    strategy: HealthStrategy,
}

impl LivenessHandler {
    pub(crate) fn new(
        components: Arc<Vec<LivenessComponentRef>>,
        strategy: HealthStrategy,
    ) -> Self {
        Self {
            components,
            strategy,
        }
    }

    /// Evaluate liveness from per-component heartbeat state; no I/O, pure atomic reads.
    pub fn check(&self) -> LivenessStatus {
        let now_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as i64;

        let mut components = HashMap::new();
        let mut any_healthy = false;
        let mut all_healthy = true;

        for comp in self.components.iter() {
            let until = comp.healthy_until_ms.load(Ordering::Relaxed);
            let status = if until == 0 {
                all_healthy = false;
                ComponentLiveness::Starting
            } else if until > now_ms {
                any_healthy = true;
                ComponentLiveness::Healthy
            } else {
                all_healthy = false;
                ComponentLiveness::Stalled
            };
            components.insert(comp.tag.clone(), status);
        }

        let healthy = match self.strategy {
            HealthStrategy::All => !components.is_empty() && all_healthy,
            HealthStrategy::Any => any_healthy,
        };

        LivenessStatus {
            healthy,
            components,
        }
    }
}

/// Result of a liveness check; used for HTTP response body and status.
#[derive(Debug)]
pub struct LivenessStatus {
    pub healthy: bool,
    pub components: HashMap<String, ComponentLiveness>,
}

impl IntoResponse for LivenessStatus {
    fn into_response(self) -> Response {
        let body = format!("{self:?}");
        let status = if self.healthy {
            StatusCode::OK
        } else {
            StatusCode::INTERNAL_SERVER_ERROR
        };
        (status, body).into_response()
    }
}
