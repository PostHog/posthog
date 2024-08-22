use std::net::SocketAddr;
use std::sync::Arc;

use reqwest::header::CONTENT_TYPE;
use tokio::net::TcpListener;
use tokio::sync::Notify;

use feature_flags::config::Config;
use feature_flags::server::serve;

pub struct ServerHandle {
    pub addr: SocketAddr,
    shutdown: Arc<Notify>,
}

impl ServerHandle {
    pub async fn for_config(config: Config) -> ServerHandle {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let notify = Arc::new(Notify::new());
        let shutdown = notify.clone();

        tokio::spawn(async move {
            serve(config, listener, async move { notify.notified().await }).await
        });
        ServerHandle { addr, shutdown }
    }

    pub async fn send_flags_request<T: Into<reqwest::Body>>(&self, body: T) -> reqwest::Response {
        let client = reqwest::Client::new();
        client
            .post(format!("http://{:?}/flags", self.addr))
            .body(body)
            .header(CONTENT_TYPE, "application/json")
            .send()
            .await
            .expect("failed to send request")
    }

    pub async fn send_invalid_header_for_flags_request<T: Into<reqwest::Body>>(
        &self,
        body: T,
    ) -> reqwest::Response {
        let client = reqwest::Client::new();
        client
            .post(format!("http://{:?}/flags", self.addr))
            .body(body)
            .header(CONTENT_TYPE, "xyz")
            .send()
            .await
            .expect("failed to send request")
    }
}

impl Drop for ServerHandle {
    fn drop(&mut self) {
        self.shutdown.notify_one()
    }
}
