use std::time::Duration;

use anyhow::Context;
use reqwest::Client as HttpClient;

use crate::config::Config;

pub struct AppContext {
    pub config: Config,
    pub http: HttpClient,
}

impl AppContext {
    pub async fn new(config: Config) -> anyhow::Result<Self> {
        let http = HttpClient::builder()
            .pool_idle_timeout(Duration::from_secs(30))
            .build()
            .context("failed to build reqwest client")?;

        Ok(Self { config, http })
    }
}
