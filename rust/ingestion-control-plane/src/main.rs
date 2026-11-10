use std::future::{ready, Future};
use std::sync::Arc;
use std::time::Duration;

use axum::routing::get;
use common_metrics::setup_metrics_routes;
use health::{readiness_handler, HealthRegistry};
use ingestion_control_plane::api;
use ingestion_control_plane::backup::{self, BackupStore, S3BackupStore};
use ingestion_control_plane::changelog;
use ingestion_control_plane::config::Config;
use ingestion_control_plane::state::AppState;
use tokio::signal;
use tracing::level_filters::LevelFilter;
use tracing::{info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

common_alloc::used!();

async fn shutdown() {
    let mut term = signal::unix::signal(signal::unix::SignalKind::terminate())
        .expect("failed to register SIGTERM handler");
    let mut interrupt = signal::unix::signal(signal::unix::SignalKind::interrupt())
        .expect("failed to register SIGINT handler");

    tokio::select! {
        _ = term.recv() => {},
        _ = interrupt.recv() => {},
    };

    info!("Shutting down gracefully...");
}

fn setup_tracing() {
    let log_layer = tracing_subscriber::fmt::layer().json().with_filter(
        EnvFilter::builder()
            .with_default_directive(LevelFilter::INFO.into())
            .from_env_lossy(),
    );
    tracing_subscriber::registry().with(log_layer).init();
}

#[tokio::main]
async fn main() {
    setup_tracing();
    info!("Starting ingestion-control-plane...");

    // kube's rustls-based client needs a process-wide crypto provider.
    rustls::crypto::ring::default_provider()
        .install_default()
        .expect("failed to install rustls crypto provider");

    let config = Config::init_with_defaults().expect("failed to load config");
    let bind = format!("{}:{}", config.host, config.port);

    // This service has no long-running pipeline to healthcheck; a heartbeat
    // task proves the runtime is alive so the liveness probe passes.
    let health_registry = HealthRegistry::new("liveness");
    let heartbeat = health_registry
        .register("heartbeat".to_string(), Duration::from_secs(30))
        .await;
    tokio::spawn(async move {
        loop {
            heartbeat.report_healthy().await;
            tokio::time::sleep(Duration::from_secs(10)).await;
        }
    });

    let mut state = AppState::new(config).expect("failed to initialize app state");
    let backups = changelog_backups(&mut state).await;
    record_changelog_cluster(&state);

    let router = api::router(state)
        .route("/_readiness", get(readiness_handler))
        .route(
            "/_liveness",
            get(move || ready(health_registry.get_status())),
        );
    let router = setup_metrics_routes(router);
    // The recorder exists only once setup_metrics_routes returns, and the first sync
    // sets the in-sync gauge, so the loop starts after it or the gauge is lost.
    if let Some(backups) = backups {
        tokio::spawn(backups);
    }

    info!("Listening on {}", bind);
    let listener = tokio::net::TcpListener::bind(bind)
        .await
        .expect("could not bind port");

    axum::serve(listener, router)
        .with_graceful_shutdown(shutdown())
        .await
        .expect("server failed");
}

fn record_changelog_cluster(state: &AppState) {
    let Some(etcd) = state.etcd.clone() else {
        return;
    };
    let cluster = match state.config.current_changelog_cluster() {
        Ok(Some(cluster)) => cluster,
        Ok(None) => {
            info!("no CHANGELOG_KAFKA_CLUSTERS entry matches PERSONHOG_KAFKA_HOSTS; a changelog config that records no cluster keeps none");
            return;
        }
        Err(e) => {
            warn!(error = %format!("{e:#}"), "could not read CHANGELOG_KAFKA_CLUSTERS; the changelog's cluster stays unrecorded");
            return;
        }
    };
    let prefix = state.config.personhog_etcd_prefix.clone();
    tokio::spawn(async move {
        let recorded = async {
            let client = etcd.client().await?;
            changelog::record_cluster(&client, &prefix, &cluster).await
        };
        match recorded.await {
            Ok(true) => info!(cluster = %cluster.name, "recorded the live changelog's cluster"),
            Ok(false) => info!("the live changelog's cluster was not recorded: it is unseeded, already recorded, or a migration is requested"),
            Err(e) => {
                warn!(error = %format!("{e:#}"), "could not record the live changelog's cluster; the next start retries")
            }
        }
    });
}

async fn changelog_backups(state: &mut AppState) -> Option<impl Future<Output = ()>> {
    let bucket = state.config.changelog_backup_bucket.clone();
    if bucket.is_empty() {
        info!("CHANGELOG_BACKUP_BUCKET not set; changelog backups disabled");
        return None;
    }
    let Some(etcd) = state.etcd.clone() else {
        warn!("CHANGELOG_BACKUP_BUCKET is set without ETCD_ENDPOINTS; changelog backups disabled");
        return None;
    };
    let backups: Arc<dyn BackupStore> = Arc::new(S3BackupStore::from_env(bucket).await);
    state.backups = Some(backups.clone());
    Some(backup::run(
        etcd,
        state.config.personhog_etcd_prefix.clone(),
        backups,
    ))
}
