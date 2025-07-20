use anyhow::Result;
use reqwest::Client;
use tracing::{debug, error};

use crate::config::Config;
use crate::posthog::PostHogEvent;

pub async fn send_to_posthog(config: &Config, event: PostHogEvent) -> Result<()> {
    let client = Client::new();
    let url = &config.capture_host;

    debug!("Sending event to PostHog: {}", url);
    debug!("Event data: {}", serde_json::to_string_pretty(&event)?);

    let response = client
        .post(url)
        .header("Content-Type", "application/json")
        .json(&event)
        .send()
        .await?;

    let status = response.status();
    let body = response.text().await?;

    if !status.is_success() {
        error!("PostHog API error - Status: {}, Body: {}", status, body);
        anyhow::bail!("PostHog API returned error status: {}", status);
    }

    debug!("PostHog response: {}", body);

    Ok(())
}