//! `flags-stream-gateway` binary entry point (plan §2.4).
//!
//! Thin by design: install the global allocator, initialize tracing (pretty when
//! `DEBUG`, JSON otherwise — Django's split), load and validate config, wire the
//! lifecycle manager, bind, serve, and translate a dirty shutdown into a non-zero
//! exit so restart policies fire. All real construction lives in
//! [`flags_stream_gateway::server`].

use std::time::Duration;

use envconfig::Envconfig;
use lifecycle::Manager;
use tokio::net::TcpListener;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter};

use flags_stream_gateway::config::Config;
use flags_stream_gateway::server;

common_alloc::used!();

#[tokio::main]
async fn main() {
    let config = Config::init_from_env()
        .expect("Invalid configuration")
        .validate()
        .expect("Invalid configuration");

    init_tracing(config.debug);

    let mut manager = Manager::builder("flags-stream-gateway")
        .with_global_shutdown_timeout(Duration::from_secs(45))
        .build();
    let handles = server::register_components(&mut manager, &config);
    let monitor = manager.monitor_background();

    let listener = TcpListener::bind(config.address)
        .await
        .expect("could not bind address");
    server::run(config, listener, handles).await;

    // Exit non-zero on a dirty shutdown so `restart: on-failure` policies fire;
    // a clean shutdown exits 0.
    if let Err(e) = monitor.wait().await {
        tracing::error!("Lifecycle monitor reported: {e}");
        std::process::exit(1);
    }
}

/// Pretty colored tracing in debug (like Django's `ConsoleRenderer`), structured
/// JSON otherwise (like Django's `JSONRenderer`). `RUST_LOG` overrides the level.
fn init_tracing(debug: bool) {
    let filter = EnvFilter::builder()
        .with_default_directive(LevelFilter::INFO.into())
        .from_env_lossy();
    let registry = tracing_subscriber::registry().with(filter);
    if debug {
        registry.with(fmt::layer().with_ansi(true)).init();
    } else {
        registry.with(fmt::layer().json()).init();
    }
}
