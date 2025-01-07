use std::{sync::Arc, time::Duration};

use anyhow::Error;
use async_trait::async_trait;
use reqwest::Client;

use super::DataSource;

pub struct UrlList {
    pub urls: Vec<String>,
    pub client: Client,
}

impl UrlList {
    pub async fn new(
        urls: Vec<String>,
        allow_internal_ips: bool,
        timeout: Duration,
    ) -> Result<Self, Error> {
        let resolver = Arc::new(common_dns::PublicIPv4Resolver {});

        let mut client = reqwest::Client::builder().timeout(timeout);

        if !allow_internal_ips {
            client = client.dns_resolver(resolver);
        }

        let client = client.build()?;

        let source = Self { urls, client };

        // Validate the passed urls, and assert they all support range requests
        for url in &source.urls {
            source.assert_supports_range_requests(url).await?;
        }

        Ok(source)
    }

    pub async fn assert_supports_range_requests(&self, url: &str) -> Result<(), Error> {
        let response = self
            .client
            .head(url)
            .send()
            .await?
            .error_for_status()
            .map_err(|e| Error::msg(format!("Failed to get headers for {}: {}", url, e)))?;

        let accept_ranges = response
            .headers()
            .get("accept-ranges")
            .ok_or(Error::msg("Missing Accept-Ranges header"))?
            .to_str()
            .map_err(|e| Error::msg(format!("Failed to parse Accept-Ranges header: {}", e)))?;

        if accept_ranges != "bytes" {
            return Err(Error::msg(format!(
                "Server does not support range requests for {}",
                url
            )));
        }

        Ok(())
    }
}

#[async_trait]
impl DataSource for UrlList {
    async fn keys(&self) -> Result<Vec<String>, Error> {
        Ok(self.urls.clone())
    }

    async fn size(&self, key: &str) -> Result<usize, Error> {
        // Ensure the passed key is in our list of URLs
        if !self.urls.contains(&key.to_string()) {
            return Err(Error::msg("Key not found"));
        }

        self.client
            .head(key)
            .send()
            .await?
            .content_length()
            .ok_or(Error::msg(format!(
                "Could not get content length for {}",
                key
            )))
            .map(|size| size as usize)
    }

    async fn get_chunk(&self, key: &str, offset: usize, size: usize) -> Result<Vec<u8>, Error> {
        // Ensure the passed key is in our list of URLs
        if !self.urls.contains(&key.to_string()) {
            return Err(Error::msg("Key not found"));
        }

        let response = self
            .client
            .get(key)
            .header("Range", format!("bytes={}-{}", offset, offset + size - 1))
            .send()
            .await?
            .error_for_status();

        match response {
            Ok(response) => Ok(response.bytes().await.map(|bytes| bytes.to_vec())?),
            Err(e) => Err(e.into()),
        }
    }
}
