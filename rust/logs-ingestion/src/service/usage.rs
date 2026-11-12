//! Records dedupe by (team, usage key, record id), retry on transient codes, and never fail the batch.

use std::collections::HashSet;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use async_trait::async_trait;
use tonic::transport::Channel;
use tonic::Code;
use usage_ingestion_proto::usage_ingestion::v1::usage_ingestion_client::UsageIngestionClient;
use usage_ingestion_proto::usage_ingestion::v1::{BillingUsageRecord, IngestBillingUsageRequest};

use crate::pipeline::UsageRecordBatch;
use crate::property_filter::coerce::js_parse_int;
use crate::rate_limiter::Clock;

use super::config::UsageConfig;

const MAX_ATTEMPTS: u32 = 3;
const RETRY_BACKOFF_MS: u64 = 100;

#[derive(Debug, Clone)]
struct Pending {
    team_id: i64,
    usage_key: String,
    record_id: String,
    quantity: f64,
    unit: String,
}

#[derive(Default)]
struct Records {
    keys: HashSet<String>,
    list: Vec<Pending>,
}

pub struct GrpcUsageRecordBatch {
    client: Option<UsageIngestionClient<Channel>>,
    producer_id: Arc<str>,
    report_teams: String,
    max_batch_size: usize,
    timeout: Duration,
    records: Mutex<Records>,
    clock: Clock,
}

/// Only an exact `*` matches all, and each item is `parseInt(item)` with no radix.
fn report_teams_match(raw: &str, team_id: i64) -> bool {
    if raw.trim().is_empty() {
        return false;
    }
    if raw == "*" {
        return true;
    }
    raw.split(',')
        .any(|item| js_parse_int(item, None) == team_id as f64)
}

impl GrpcUsageRecordBatch {
    /// No address or no report teams means no client.
    pub fn new(config: &UsageConfig, producer_id: &str, clock: Clock) -> anyhow::Result<Self> {
        let client = if config.addr.is_empty() || config.report_teams.is_empty() {
            None
        } else {
            if config.tls {
                anyhow::bail!(
                    "USAGE_INGESTION_TLS=true is not supported by the Rust logs consumer"
                );
            }
            let channel = Channel::from_shared(format!("http://{}", config.addr))?
                .timeout(config.timeout)
                .connect_lazy();
            Some(UsageIngestionClient::new(channel))
        };
        Ok(Self {
            client,
            producer_id: Arc::from(producer_id),
            report_teams: config.report_teams.clone(),
            max_batch_size: config.max_batch_size.max(1),
            timeout: config.timeout,
            records: Mutex::new(Records::default()),
            clock,
        })
    }

    fn accepts(&self, team_id: i64) -> bool {
        self.client.is_some() && report_teams_match(&self.report_teams, team_id)
    }

    async fn ingest_chunk(
        &self,
        client: &UsageIngestionClient<Channel>,
        chunk: &[BillingUsageRecord],
    ) {
        let mut attempt = 0;
        loop {
            let mut request = tonic::Request::new(IngestBillingUsageRequest {
                records: chunk.to_vec(),
            });
            if let Ok(v) = self.producer_id.parse() {
                request.metadata_mut().insert("x-client-name", v);
            }
            // connect-rpc's `defaultTimeoutMs` bounds the whole call, connecting included.
            let mut client = client.clone();
            let call = tokio::time::timeout(self.timeout, client.ingest_billing_usage(request));
            let reply = match call.await {
                Ok(reply) => reply,
                Err(_) => Err(tonic::Status::deadline_exceeded(
                    "usage-ingestion call timed out",
                )),
            };
            match reply {
                Ok(response) => {
                    let accepted: HashSet<String> = response
                        .into_inner()
                        .accepted_record_ids
                        .into_iter()
                        .collect();
                    let mut rejected = 0;
                    for r in chunk {
                        let key: Arc<str> = Arc::from(r.usage_key.as_str());
                        if accepted.contains(&r.record_id) {
                            metrics::counter!("usage_ingestion_records_sent_total", "producer_id" => self.producer_id.clone(), "usage_key" => key).increment(1);
                        } else {
                            rejected += 1;
                            metrics::counter!("usage_ingestion_records_failed_total", "producer_id" => self.producer_id.clone(), "usage_key" => key, "error_code" => "rejected").increment(1);
                        }
                    }
                    if rejected > 0 {
                        tracing::warn!(producer_id = %self.producer_id, records = rejected, "usage-ingestion rejected usage records");
                    }
                    return;
                }
                Err(status) => {
                    let code = status.code();
                    let retryable = matches!(
                        code,
                        Code::Unavailable
                            | Code::DeadlineExceeded
                            | Code::ResourceExhausted
                            | Code::Aborted
                            | Code::Cancelled
                            | Code::Internal
                    );
                    let code_label: Arc<str> = Arc::from(format!("{code:?}"));
                    if attempt + 1 < MAX_ATTEMPTS && retryable {
                        metrics::counter!("usage_ingestion_retries_total", "producer_id" => self.producer_id.clone(), "error_code" => code_label).increment(1);
                        tokio::time::sleep(Duration::from_millis(
                            RETRY_BACKOFF_MS * 2u64.pow(attempt),
                        ))
                        .await;
                        attempt += 1;
                        continue;
                    }
                    for r in chunk {
                        let key: Arc<str> = Arc::from(r.usage_key.as_str());
                        metrics::counter!("usage_ingestion_records_failed_total", "producer_id" => self.producer_id.clone(), "usage_key" => key, "error_code" => code_label.clone()).increment(1);
                    }
                    tracing::warn!(producer_id = %self.producer_id, records = chunk.len(), error = %status, "failed to ingest usage records");
                    return;
                }
            }
        }
    }
}

#[async_trait]
impl UsageRecordBatch for GrpcUsageRecordBatch {
    fn add(&self, team_id: i64, usage_key: &str, record_id: &str, quantity: f64, unit: &str) {
        if quantity <= 0.0 || !self.accepts(team_id) {
            return;
        }
        let key = format!("{team_id}:{usage_key}:{record_id}");
        let mut records = self.records.lock().unwrap();
        if records.keys.insert(key) {
            records.list.push(Pending {
                team_id,
                usage_key: usage_key.to_string(),
                record_id: record_id.to_string(),
                quantity,
                unit: unit.to_string(),
            });
        }
    }

    async fn flush(&self) -> anyhow::Result<()> {
        let pending = std::mem::take(&mut *self.records.lock().unwrap()).list;
        let Some(client) = &self.client else {
            return Ok(());
        };
        if pending.is_empty() {
            return Ok(());
        }
        let flushed_at = (self.clock)() as i64;
        let mut records = Vec::with_capacity(pending.len());
        for p in pending {
            // `BigInt(quantity)` throws on a fraction, which fails the whole flush.
            if p.quantity.fract() != 0.0 || !p.quantity.is_finite() {
                anyhow::bail!(
                    "The number {} cannot be converted to a BigInt because it is not an integer",
                    p.quantity
                );
            }
            records.push(BillingUsageRecord {
                team_id: p.team_id,
                timestamp_ms: flushed_at,
                producer_id: self.producer_id.to_string(),
                usage_key: p.usage_key,
                record_id: p.record_id,
                quantity: p.quantity as i64,
                unit: p.unit,
            });
        }
        futures::future::join_all(
            records
                .chunks(self.max_batch_size)
                .map(|chunk| self.ingest_chunk(client, chunk)),
        )
        .await;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn report_teams_match_like_build_integer_matcher() {
        for (raw, expected) in [
            ("*", true),
            (" * ", false),
            ("*,5", true),
            ("*,6", false),
            ("3, 5", true),
            ("0x5", true),
            ("5abc", true),
            ("", false),
            ("  ", false),
            ("6", false),
        ] {
            assert_eq!(report_teams_match(raw, 5), expected, "{raw:?}");
        }
    }

    #[tokio::test]
    async fn a_usage_call_to_a_silent_server_ends_at_the_timeout() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            let mut held = Vec::new();
            while let Ok((socket, _)) = listener.accept().await {
                held.push(socket);
            }
        });
        let batch = GrpcUsageRecordBatch::new(
            &UsageConfig {
                addr: addr.to_string(),
                tls: false,
                timeout: Duration::from_millis(50),
                max_batch_size: 10,
                report_teams: "*".to_string(),
            },
            "logs",
            crate::rate_limiter::system_clock(),
        )
        .unwrap();
        batch.add(1, "logs_bytes", "record-1", 5.0, "bytes");
        tokio::time::timeout(Duration::from_secs(5), batch.flush())
            .await
            .expect("each attempt must end at its timeout")
            .unwrap();
    }
}
