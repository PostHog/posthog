use std::net::SocketAddr;
use std::str::FromStr;
use std::string::ToString;
use std::sync::Arc;

use once_cell::sync::Lazy;
use reqwest::header::CONTENT_TYPE;
use tokio::net::TcpListener;
use tokio::sync::Notify;

use feature_flags::config::Config;
use feature_flags::server::serve;

pub static DEFAULT_CONFIG: Lazy<Config> = Lazy::new(|| Config {
    address: SocketAddr::from_str("127.0.0.1:0").unwrap(),
    redis_url: "redis://localhost:6379/".to_string(),
    write_database_url: "postgres://posthog:posthog@localhost:15432/test_database".to_string(),
    read_database_url: "postgres://posthog:posthog@localhost:15432/test_database".to_string(),
    max_concurrent_jobs: 1024,
    max_pg_connections: 100,
});

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
