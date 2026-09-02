//! /healthz, /readyz and /metrics for the golden chart's probes and Prometheus
//! pod-annotation scraping.

use axum::{extract::State, http::StatusCode, routing::get, Router};
use once_cell::sync::Lazy;
use prometheus::{
    Encoder, HistogramVec, IntCounterVec, IntGaugeVec, Registry as PromRegistry, TextEncoder,
};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

pub static METRICS: Lazy<Metrics> = Lazy::new(Metrics::new);

pub struct Metrics {
    pub registry: PromRegistry,
    pub tick_seconds: HistogramVec,
    pub rows: IntCounterVec,
    pub errors: IntCounterVec,
    pub targets: IntGaugeVec,
}

impl Metrics {
    fn new() -> Self {
        let registry = PromRegistry::new();
        let tick_seconds = HistogramVec::new(
            prometheus::histogram_opts!("pgcollector_tick_seconds", "collector tick duration")
                .buckets(vec![0.005, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]),
            &["collector", "server"],
        )
        .unwrap();
        let rows = IntCounterVec::new(
            prometheus::opts!("pgcollector_rows_total", "rows emitted"),
            &["collector", "server"],
        )
        .unwrap();
        let errors = IntCounterVec::new(
            prometheus::opts!("pgcollector_errors_total", "tick errors"),
            &["collector", "server", "stage"],
        )
        .unwrap();
        let targets = IntGaugeVec::new(
            prometheus::opts!(
                "pgcollector_targets",
                "active (server, instance, database) targets"
            ),
            &["server"],
        )
        .unwrap();
        registry.register(Box::new(tick_seconds.clone())).unwrap();
        registry.register(Box::new(rows.clone())).unwrap();
        registry.register(Box::new(errors.clone())).unwrap();
        registry.register(Box::new(targets.clone())).unwrap();
        Self {
            registry,
            tick_seconds,
            rows,
            errors,
            targets,
        }
    }
}

#[derive(Clone, Default)]
pub struct Readiness(pub Arc<AtomicBool>);
impl Readiness {
    pub fn set(&self, ready: bool) {
        self.0.store(ready, Ordering::Relaxed);
    }
}

pub async fn serve(listen: String, ready: Readiness) -> anyhow::Result<()> {
    let app = Router::new()
        .route("/healthz", get(|| async { "ok" }))
        .route(
            "/readyz",
            get(|State(r): State<Readiness>| async move {
                if r.0.load(Ordering::Relaxed) {
                    (StatusCode::OK, "ready")
                } else {
                    (StatusCode::SERVICE_UNAVAILABLE, "not ready")
                }
            }),
        )
        .route(
            "/metrics",
            get(|| async {
                let mut buf = Vec::new();
                TextEncoder::new()
                    .encode(&METRICS.registry.gather(), &mut buf)
                    .unwrap();
                ([("content-type", "text/plain; version=0.0.4")], buf)
            }),
        )
        .with_state(ready);
    let listener = tokio::net::TcpListener::bind(&listen).await?;
    tracing::info!(listen, "http listening");
    axum::serve(listener, app).await?;
    Ok(())
}
