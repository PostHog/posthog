//! Worker readiness probing, shared by both transports: workers always
//! serve `/_ready` over HTTP, whichever transport carries the batches.

use std::time::Duration;

use tracing::{info, warn};

/// Bound on one `/_ready` probe. A worker that accepts the connection but
/// never answers must not stall startup or shutdown.
pub const PROBE_TIMEOUT: Duration = Duration::from_secs(5);

/// Probe a worker's `/_ready` endpoint.
pub async fn check_ready(client: &reqwest::Client, worker_url: &str) -> bool {
    let url = format!("{worker_url}/_ready");
    match client.get(&url).timeout(PROBE_TIMEOUT).send().await {
        Ok(resp) => resp.status().is_success(),
        Err(_) => false,
    }
}

/// Wait until every worker is ready, polling with backoff. Probes run
/// concurrently, and shutdown wins over an in-progress round.
pub async fn wait_for_workers_ready(
    client: &reqwest::Client,
    worker_urls: &[String],
    shutdown: &lifecycle::Handle,
) -> anyhow::Result<()> {
    let poll_interval = Duration::from_secs(2);
    loop {
        let round = async {
            let results =
                futures::future::join_all(worker_urls.iter().map(|url| check_ready(client, url)))
                    .await;
            let mut all_ready = true;
            for (url, ready) in worker_urls.iter().zip(results) {
                if !ready {
                    warn!(worker = %url, "Worker not ready");
                    all_ready = false;
                }
            }
            all_ready
        };
        let all_ready = tokio::select! {
            _ = shutdown.shutdown_recv() => {
                anyhow::bail!("Shutdown received while waiting for workers");
            }
            all_ready = round => all_ready,
        };
        if all_ready {
            info!(workers = worker_urls.len(), "All workers ready");
            return Ok(());
        }
        tokio::select! {
            _ = shutdown.shutdown_recv() => {
                anyhow::bail!("Shutdown received while waiting for workers");
            }
            _ = tokio::time::sleep(poll_interval) => {}
        }
    }
}
