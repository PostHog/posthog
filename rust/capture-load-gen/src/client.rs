use std::io::Write;
use std::time::{Duration, Instant};

use anyhow::{Context, Result};
use common_types::RawEvent;
use flate2::write::GzEncoder;
use flate2::Compression as GzLevel;
use reqwest::header::{CONTENT_ENCODING, CONTENT_TYPE};

use crate::event::BatchPayload;

/// Sends event batches to a capture `/batch` endpoint.
pub struct CaptureClient {
    http: reqwest::Client,
    url: String,
    token: String,
    gzip: bool,
}

/// Outcome of a single batch request.
pub struct SendResult {
    pub latency: Duration,
    pub ok: bool,
}

impl CaptureClient {
    pub fn new(endpoint: &str, token: String, gzip: bool, timeout: Duration) -> Result<Self> {
        let http = reqwest::Client::builder()
            .timeout(timeout)
            .pool_max_idle_per_host(256)
            .build()
            .context("building reqwest client")?;

        Ok(Self {
            http,
            url: format!("{}/batch", endpoint.trim_end_matches('/')),
            token,
            gzip,
        })
    }

    /// Serialize (and optionally gzip) a batch into a request body.
    pub fn encode(&self, events: &[RawEvent]) -> Result<Vec<u8>> {
        let payload = BatchPayload {
            api_key: &self.token,
            batch: events,
        };
        let json = serde_json::to_vec(&payload).context("serializing batch")?;

        if !self.gzip {
            return Ok(json);
        }

        let mut encoder = GzEncoder::new(Vec::new(), GzLevel::fast());
        encoder.write_all(&json).context("gzip write")?;
        encoder.finish().context("gzip finish")
    }

    pub async fn send(&self, body: Vec<u8>) -> SendResult {
        let started = Instant::now();
        let mut req = self
            .http
            .post(&self.url)
            .header(CONTENT_TYPE, "application/json")
            .body(body);
        if self.gzip {
            req = req.header(CONTENT_ENCODING, "gzip");
        }

        let ok = match req.send().await {
            Ok(resp) => resp.status().is_success(),
            Err(_) => false,
        };

        SendResult {
            latency: started.elapsed(),
            ok,
        }
    }
}
