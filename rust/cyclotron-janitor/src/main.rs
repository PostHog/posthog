use std::sync::Arc;

use cyclotron_janitor::{
    app_context::AppContext,
    config::Config,
    http::{app, listen},
};
use envconfig::Envconfig;
use tracing::{error, info};

common_alloc::used!();

#[tokio::main]
async fn main() {
    let config = Config::init_from_env().expect("failed to load configuration from env");
    let bind = format!("{}:{}", config.host, config.port);
    tracing_subscriber::fmt::init();
    info!("starting janitor, bound to {}", bind);

    let context = Arc::new(AppContext::new(config).await);

    let m_context = context.clone();
    let janitor_loop = async move { m_context.cleanup_loop().await };

    let app = app(context.clone());

    let http_server = listen(app, bind);

    let loop_handle = tokio::spawn(janitor_loop);
    let server_handle = tokio::spawn(http_server);

    tokio::select! {
        _ = loop_handle => {
            error!("janitor loop exited");
        }
        _ = server_handle => {
            error!("http server exited");
        }
    }

    info!("exiting");
}
