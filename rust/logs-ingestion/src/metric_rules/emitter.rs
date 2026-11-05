//! The crate has no HTTP client, so the POST is behind `OtlpTransport`. `LogsMetricsEmitter` keeps Node's two attempts and 2xx check.

use std::sync::Arc;

use async_trait::async_trait;

use crate::js::{json_stringify, JsValue};

pub const EXPORT_FAILED_COUNTER: &str = "logs_metrics_rules_export_failed_total";

const EXPORT_ATTEMPTS: u32 = 2;

#[async_trait]
pub trait MetricsEmitter: Send + Sync {
    async fn emit(&self, token: &str, team_id: i64, payload: &JsValue) -> bool;
}

/// The implementation reads the whole response body before it returns, as `response.dump()` does in Node.
#[async_trait]
pub trait OtlpTransport: Send + Sync {
    async fn post(&self, url: &str, headers: &[(&str, String)], body: &str) -> anyhow::Result<u16>;
}

/// Posts with the team's own token, so the series goes through the customer capture pipeline. After one retry the window is dropped.
pub struct LogsMetricsEmitter<T: OtlpTransport> {
    url: String,
    transport: T,
}

impl<T: OtlpTransport> LogsMetricsEmitter<T> {
    pub fn new(url: impl Into<String>, transport: T) -> Self {
        Self {
            url: url.into(),
            transport,
        }
    }
}

#[async_trait]
impl<T: OtlpTransport> MetricsEmitter for LogsMetricsEmitter<T> {
    async fn emit(&self, token: &str, team_id: i64, payload: &JsValue) -> bool {
        let body = json_stringify(payload);
        let headers = [
            ("Authorization", format!("Bearer {token}")),
            ("Content-Type", "application/json".to_string()),
        ];
        for attempt in 1..=EXPORT_ATTEMPTS {
            match self.transport.post(&self.url, &headers, &body).await {
                Ok(status) if (200..300).contains(&status) => return true,
                Ok(status) => tracing::warn!(
                    team_id,
                    status,
                    attempt,
                    "[logs-metric-rules] OTLP export rejected"
                ),
                Err(error) => tracing::warn!(
                    team_id,
                    error = %error,
                    attempt,
                    "[logs-metric-rules] OTLP export failed"
                ),
            }
        }
        let team_label: Arc<str> = Arc::from(team_id.to_string());
        metrics::counter!(EXPORT_FAILED_COUNTER, "team_id" => team_label).increment(1);
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    struct Scripted(Mutex<Vec<anyhow::Result<u16>>>, Mutex<Vec<String>>);

    #[async_trait]
    impl OtlpTransport for Scripted {
        async fn post(
            &self,
            _url: &str,
            headers: &[(&str, String)],
            body: &str,
        ) -> anyhow::Result<u16> {
            self.1
                .lock()
                .unwrap()
                .push(format!("{}|{body}", headers[0].1));
            self.0.lock().unwrap().remove(0)
        }
    }

    #[tokio::test]
    async fn retries_once_then_gives_up() {
        let payload = crate::js::json_parse(r#"{"a":1e21}"#).unwrap();
        let t = Scripted(
            Mutex::new(vec![Err(anyhow::anyhow!("reset")), Ok(503), Ok(200)]),
            Mutex::new(vec![]),
        );
        let emitter = LogsMetricsEmitter::new("http://x", t);
        assert!(!emitter.emit("tok", 7, &payload).await);
        assert_eq!(
            *emitter.transport.1.lock().unwrap(),
            vec!["Bearer tok|{\"a\":1e+21}", "Bearer tok|{\"a\":1e+21}"]
        );
        assert!(emitter.emit("tok", 7, &payload).await);
    }
}
