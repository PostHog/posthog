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
            Ok(resp) => {
                let ok = resp.status().is_success();
                // Drain the body so hyper can return the connection to the pool
                // rather than closing it — matters most at high error rates.
                resp.bytes().await.ok();
                ok
            }
            Err(_) => false,
        };

        SendResult {
            latency: started.elapsed(),
            ok,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::read::GzDecoder;
    use std::io::Read;

    fn sample_events(n: usize) -> Vec<RawEvent> {
        (0..n)
            .map(|i| RawEvent {
                event: format!("e{i}"),
                ..Default::default()
            })
            .collect()
    }

    fn client(gzip: bool) -> CaptureClient {
        CaptureClient::new(
            "http://localhost:0",
            "tok".into(),
            gzip,
            Duration::from_secs(1),
        )
        .unwrap()
    }

    #[test]
    fn encode_plain_is_a_valid_batch_payload() {
        let body = client(false).encode(&sample_events(3)).unwrap();
        let value: serde_json::Value = serde_json::from_slice(&body).unwrap();

        assert_eq!(value["api_key"], "tok");
        let batch: Vec<RawEvent> = serde_json::from_value(value["batch"].clone()).unwrap();
        assert_eq!(batch.len(), 3);
        assert_eq!(batch[0].event, "e0");
    }

    #[test]
    fn encode_gzip_roundtrips_to_the_same_payload() {
        let body = client(true).encode(&sample_events(5)).unwrap();

        let mut json = String::new();
        GzDecoder::new(&body[..]).read_to_string(&mut json).unwrap();
        let value: serde_json::Value = serde_json::from_str(&json).unwrap();

        assert_eq!(value["api_key"], "tok");
        assert_eq!(value["batch"].as_array().unwrap().len(), 5);
    }
}
