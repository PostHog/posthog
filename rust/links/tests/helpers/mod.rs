use std::{
    net::SocketAddr,
    sync::{Arc, Once},
};

use links::state::State;
use links::{config::Config, server::serve};
use tokio::{net::TcpListener, sync::Notify};

static TRACING_INIT: Once = Once::new();
pub fn setup_tracing() {
    TRACING_INIT.call_once(|| {
        tracing_subscriber::fmt()
            .with_writer(tracing_subscriber::fmt::TestWriter::new())
            .init()
    });
}

pub struct ServerHandle {
    pub addr: SocketAddr,
    pub shutdown: Arc<Notify>,
}

impl ServerHandle {
    pub async fn for_config(config: Config) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let notify = Arc::new(Notify::new());
        let shutdown = notify.clone();

        let state = State::from_config(&config).await.unwrap();

        tokio::spawn(async move {
            serve(state, listener, async move { notify.notified().await }).await
        });

        Self { addr, shutdown }
    }
}

impl Drop for ServerHandle {
    fn drop(&mut self) {
        self.shutdown.notify_one()
    }
}
