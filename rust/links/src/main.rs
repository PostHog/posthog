use envconfig::Envconfig;
use links::server::serve;
use tokio::signal;
use tracing_subscriber::fmt;
use tracing_subscriber::fmt::format::FmtSpan;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, Layer};

use links::config::Config;
use links::state::State;

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

    tracing::info!("Shutting down gracefully...");
}

#[tokio::main]
async fn main() {
    let config = Config::init_from_env().expect("Invalid configuration:");
    let state = State::from_config(&config)
        .await
        .expect("Failed to create state");

    // Configure logging format:
    //   with_span_events: Log when spans are created/closed
    //   with_target: Include module path (e.g. "feature_flags::api")
    //   with_thread_ids: Include thread ID for concurrent debugging
    //   with_level: Show log level (ERROR, INFO, etc)
    //   with_filter: Use RUST_LOG env var to control verbosity
    let fmt_layer = fmt::layer()
        .with_span_events(
            FmtSpan::NEW | FmtSpan::CLOSE | FmtSpan::ENTER | FmtSpan::EXIT | FmtSpan::ACTIVE,
        )
        .with_target(true)
        .with_thread_ids(true)
        .with_level(true)
        .with_filter(EnvFilter::from_default_env());
    tracing_subscriber::registry().with(fmt_layer).init();

    // Open the TCP port and start the server
    let listener = tokio::net::TcpListener::bind(config.address)
        .await
        .expect("could not bind port");
    serve(state, listener, shutdown()).await;
    unreachable!("Server exited unexpectedly");
}
