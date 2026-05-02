use std::time::Duration;

use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

const POLL_INTERVAL: Duration = Duration::from_secs(2);
const MAX_WAIT: Duration = Duration::from_secs(60);

/// Block until `GET /_alias/<alias>` returns 200, or fail after `MAX_WAIT`.
/// Decision #7 in the plan: the indexer refuses to start if the alias is
/// missing — auto-creating an index would silently produce wrong mappings, so
/// we'd rather page the operator than ingest into a bad target.
///
/// Honors `shutdown` so a SIGTERM during the gate window terminates promptly
/// instead of running out the 60s timer (matters for K8s rollouts that catch
/// the indexer mid-wait).
pub async fn wait_for_alias(
    client: &reqwest::Client,
    opensearch_url: &str,
    alias: &str,
    shutdown: CancellationToken,
) -> anyhow::Result<()> {
    let url = format!(
        "{}/_alias/{}",
        opensearch_url.trim_end_matches('/'),
        alias
    );
    let start = tokio::time::Instant::now();
    let mut attempt: u32 = 0;
    loop {
        let probe = tokio::select! {
            _ = shutdown.cancelled() => {
                anyhow::bail!("shutdown signaled during readiness gate");
            }
            r = client.get(&url).send() => r,
        };
        match probe {
            Ok(resp) if resp.status().is_success() => {
                info!(alias, attempts = attempt + 1, "OpenSearch alias ready");
                return Ok(());
            }
            Ok(resp) => warn!(status = %resp.status(), attempt, "alias not yet ready"),
            Err(e) => warn!(error = %e, attempt, "alias check failed"),
        }
        if start.elapsed() >= MAX_WAIT {
            anyhow::bail!(
                "OpenSearch alias `{alias}` did not become ready within {}s",
                MAX_WAIT.as_secs()
            );
        }
        tokio::select! {
            _ = shutdown.cancelled() => {
                anyhow::bail!("shutdown signaled during readiness gate");
            }
            _ = tokio::time::sleep(POLL_INTERVAL) => {}
        }
        attempt += 1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use httpmock::prelude::*;

    fn client() -> reqwest::Client {
        reqwest::Client::builder()
            .timeout(Duration::from_secs(2))
            .build()
            .unwrap()
    }

    #[tokio::test]
    async fn returns_ok_when_alias_exists_first_try() {
        let server = MockServer::start_async().await;
        let mock = server
            .mock_async(|when, then| {
                when.method(GET).path("/_alias/llm-traces");
                then.status(200).body(r#"{"some-index":{"aliases":{"llm-traces":{}}}}"#);
            })
            .await;

        let result = wait_for_alias(
            &client(),
            &server.base_url(),
            "llm-traces",
            CancellationToken::new(),
        )
        .await;

        assert!(result.is_ok(), "expected Ok, got {result:?}");
        mock.assert_async().await;
    }

    #[tokio::test]
    async fn retries_then_succeeds_when_alias_appears() {
        let server = MockServer::start_async().await;
        // Stage 1: alias missing.
        let miss = server
            .mock_async(|when, then| {
                when.method(GET).path("/_alias/llm-traces");
                then.status(404);
            })
            .await;

        // Spawn the gate; it will see 404 → wait → re-poll.
        let url = server.base_url();
        let token = CancellationToken::new();
        let gate = tokio::spawn(async move {
            wait_for_alias(&client(), &url, "llm-traces", token).await
        });

        // After ~1.5s replace the 404 mock with a 200 mock — the gate's next
        // poll (POLL_INTERVAL = 2s) will succeed.
        tokio::time::sleep(Duration::from_millis(1500)).await;
        miss.delete_async().await;
        let _hit = server
            .mock_async(|when, then| {
                when.method(GET).path("/_alias/llm-traces");
                then.status(200).body("{}");
            })
            .await;

        let result = gate.await.expect("task joined");
        assert!(result.is_ok(), "expected Ok, got {result:?}");
    }

    #[tokio::test]
    async fn cancelled_token_returns_err_promptly() {
        let server = MockServer::start_async().await;
        let _miss = server
            .mock_async(|when, then| {
                when.method(GET).path("/_alias/llm-traces");
                then.status(404);
            })
            .await;
        let token = CancellationToken::new();
        let token_clone = token.clone();
        tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(100)).await;
            token_clone.cancel();
        });

        let start = tokio::time::Instant::now();
        let result = wait_for_alias(
            &client(),
            &server.base_url(),
            "llm-traces",
            token,
        )
        .await;
        let elapsed = start.elapsed();

        assert!(result.is_err(), "expected Err, got {result:?}");
        assert!(
            elapsed < Duration::from_secs(3),
            "should bail well before POLL_INTERVAL: took {:?}",
            elapsed
        );
        let err = format!("{:#}", result.unwrap_err());
        assert!(err.contains("shutdown"), "error should mention shutdown: {err}");
    }

    #[tokio::test]
    async fn url_strips_trailing_slash() {
        let server = MockServer::start_async().await;
        let mock = server
            .mock_async(|when, then| {
                // Note: NOT `/_alias/llm-traces` with double slash.
                when.method(GET).path("/_alias/llm-traces");
                then.status(200).body("{}");
            })
            .await;

        let url_with_slash = format!("{}/", server.base_url());
        let result = wait_for_alias(
            &client(),
            &url_with_slash,
            "llm-traces",
            CancellationToken::new(),
        )
        .await;

        assert!(result.is_ok(), "expected Ok, got {result:?}");
        mock.assert_async().await;
    }
}
