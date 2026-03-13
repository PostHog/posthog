use std::sync::Arc;

use assignment_coordination::store::{EtcdStore, StoreConfig};
use kafka_assigner::assigner::{Assigner, AssignerConfig};
use kafka_assigner::config::Config;
use kafka_assigner::consumer_registry::ConsumerRegistry;
use kafka_assigner::grpc::relay::run_relay;
use kafka_assigner::grpc::server::KafkaAssignerService;
use kafka_assigner::store::KafkaAssignerStore;
use kafka_assigner_proto::kafka_assigner::v1::kafka_assigner_server::KafkaAssignerServer;
use tokio::net::TcpListener;
use tokio_stream::wrappers::TcpListenerStream;
use tokio_util::sync::CancellationToken;
use tonic::transport::Server;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::registry()
        .with(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")))
        .with(tracing_subscriber::fmt::layer())
        .init();

    let config = Config::init_with_defaults()?;
    tracing::info!(?config, "loaded configuration");

    let etcd_store = EtcdStore::connect(StoreConfig {
        endpoints: config.etcd_endpoint_list(),
        prefix: config.etcd_prefix.clone(),
    })
    .await?;

    let store = Arc::new(KafkaAssignerStore::new(etcd_store));
    let registry = Arc::new(ConsumerRegistry::new());
    let cancel = CancellationToken::new();

    // gRPC server
    let service =
        KafkaAssignerService::from_config(Arc::clone(&store), Arc::clone(&registry), &config);
    let bind_addr = config.bind_address();
    let listener = TcpListener::bind(&bind_addr).await?;
    tracing::info!(addr = %bind_addr, "gRPC server listening");

    let grpc_cancel = cancel.clone();
    let grpc_handle = tokio::spawn(async move {
        Server::builder()
            .add_service(KafkaAssignerServer::new(service))
            .serve_with_incoming_shutdown(TcpListenerStream::new(listener), grpc_cancel.cancelled())
            .await
    });

    // Relay: watches etcd and pushes events to locally connected consumers
    let relay_store = Arc::clone(&store);
    let relay_registry = Arc::clone(&registry);
    let relay_cancel = cancel.child_token();
    let relay_handle = tokio::spawn(async move {
        if let Err(e) = run_relay(relay_store, relay_registry, relay_cancel).await {
            tracing::error!(error = %e, "relay exited with error");
        }
    });

    // Assigner: leader election + coordination loop
    let assigner_config = AssignerConfig::from(&config);
    let strategy = config
        .build_strategy()
        .map_err(|e| format!("invalid strategy config: {e}"))?;
    let assigner = Assigner::new(Arc::clone(&store), assigner_config, strategy);
    let assigner_cancel = cancel.child_token();
    let assigner_handle = tokio::spawn(async move {
        if let Err(e) = assigner.run(assigner_cancel).await {
            tracing::error!(error = %e, "assigner exited with error");
        }
    });

    // Wait for shutdown signal
    tokio::signal::ctrl_c().await?;
    tracing::info!("shutdown signal received, stopping");
    cancel.cancel();

    let (_grpc, _relay, _assigner) = tokio::join!(grpc_handle, relay_handle, assigner_handle);
    tracing::info!("shutdown complete");

    Ok(())
}
