use std::{sync::Arc, time::Duration};

use anyhow::Error;
use async_trait::async_trait;
use reqwest::Client;
use tracing::warn;

use super::DataSource;

pub struct UrlList {
    pub urls: Vec<String>,
    pub client: Client,
    pub retries: usize,
}

impl UrlList {
    pub async fn new(
        urls: Vec<String>,
        allow_internal_ips: bool,
        timeout: Duration,
        retries: usize,
        validate_urls: bool,
    ) -> Result<Self, Error> {
        let resolver = Arc::new(common_dns::PublicIPv4Resolver {});

        let mut client = reqwest::Client::builder().timeout(timeout);

        if !allow_internal_ips {
            client = client.dns_resolver(resolver);
        }

        let client = client.build()?;

        let source = Self {
            urls,
            client,
            retries,
        };

        // Validate the passed urls, and assert they all support range requests
        if validate_urls {
            for url in &source.urls {
                source.assert_valid_url(url).await?;
            }
        }

        Ok(source)
    }

    // A url is valid to us if it supports range requests and returns a content-length header
    async fn assert_valid_url(&self, url: &str) -> Result<(), Error> {
        let response = self
            .client
            .head(url)
            .send()
            .await?
            .error_for_status()
            .map_err(|e| Error::msg(format!("Failed to get headers for {url}: {e}")))?;

        let accept_ranges = response
            .headers()
            .get("accept-ranges")
            .ok_or(Error::msg("Missing Accept-Ranges header"))?
            .to_str()
            .map_err(|e| Error::msg(format!("Failed to parse Accept-Ranges header: {e}")))?;

        if accept_ranges != "bytes" {
            return Err(Error::msg(format!(
                "Server does not support range requests for {url}"
            )));
        }

        let content_lenth = response
            .headers()
            .get("content-length")
            .ok_or(Error::msg("Missing Content-Length header"))?
            .to_str()
            .map_err(|e| Error::msg(format!("Failed to parse Content-Length header: {e}")))?;

        content_lenth
            .parse::<u64>()
            .map_err(|e| Error::msg(format!("Failed to parse Content-Length as u64: {e}")))?;

        Ok(())
    }

    async fn get_chunk_inner(&self, key: &str, offset: u64, size: u64) -> Result<Vec<u8>, Error> {
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

#[async_trait]
impl DataSource for UrlList {
    async fn keys(&self) -> Result<Vec<String>, Error> {
        Ok(self.urls.clone())
    }

    async fn size(&self, key: &str) -> Result<Option<u64>, Error> {
        // Ensure the passed key is in our list of URLs
        if !self.urls.contains(&key.to_string()) {
            return Err(Error::msg("Key not found"));
        }

        // For some reason calling `content_length()` doesn't work properly here, so we don't do that
        self.client
            .head(key)
            .send()
            .await?
            .headers()
            .get("content-length")
            .ok_or(Error::msg(format!(
                "Could not get content length for {key}"
            )))
            .and_then(|header| {
                header
                    .to_str()
                    .map_err(|e| Error::msg(format!("Failed to parse content length: {e}")))
            })
            .and_then(|length| {
                length
                    .parse::<u64>()
                    .map_err(|e| Error::msg(format!("Failed to parse content length as u64: {e}")))
            })
            .map(Some)
    }

    async fn get_chunk(&self, key: &str, offset: u64, size: u64) -> Result<Vec<u8>, Error> {
        let mut retries = self.retries;
        loop {
            match self.get_chunk_inner(key, offset, size).await {
                Ok(chunk) => return Ok(chunk),
                Err(e) => {
                    if retries == 0 {
                        return Err(e);
                    }
                    warn!(
                        "Encountered error when fetching chunk: {e:?}, remaining retries: {retries}"
                    );
                    tokio::time::sleep(Duration::from_secs(1)).await;
                    retries -= 1;
                }
            }
        }
    }
}

#[cfg(test)]
mod test {

    use std::time::Duration;

    use httpmock::MockServer;

    use crate::source::{url_list::UrlList, DataSource};

    const TEST_CONTENTS: &str = include_str!("../../tests/capture_request_dump.jsonl");

    #[tokio::test]
    async fn test_url_list_creation() {
        let server = MockServer::start();
        let head = server.mock(|when, then| {
            when.method(httpmock::Method::HEAD);
            then.status(200)
                .header("accept-ranges", "bytes")
                .header("content-length", TEST_CONTENTS.len().to_string());
        });

        let urls: Vec<_> = ["/1", "/2"].iter().map(|&path| server.url(path)).collect();
        let url_count = urls.len();
        let source = UrlList::new(urls, true, Duration::from_secs(10), 1, true)
            .await
            .unwrap();
        let keys = source.keys().await.unwrap();
        println!("{keys:?}");

        assert_eq!(head.hits(), url_count);
    }

    #[tokio::test]
    async fn test_url_list_no_accept_ranges() {
        let server = MockServer::start();
        let _ = server.mock(|when, then| {
            when.method(httpmock::Method::HEAD);
            then.status(200)
                .header("accept-ranges", "none")
                .header("content-length", TEST_CONTENTS.len().to_string());
        });

        let urls: Vec<_> = ["/1", "/2"].iter().map(|&path| server.url(path)).collect();
        let source_res = UrlList::new(urls, true, Duration::from_secs(10), 0, true).await;

        assert!(source_res.is_err());
    }

    #[tokio::test]
    async fn test_url_list_missing_accept_ranges() {
        let server = MockServer::start();
        let _ = server.mock(|when, then| {
            when.method(httpmock::Method::HEAD);
            then.status(200)
                .header("content-length", TEST_CONTENTS.len().to_string());
        });

        let urls: Vec<_> = ["/1", "/2"].iter().map(|&path| server.url(path)).collect();
        let source_res = UrlList::new(urls, true, Duration::from_secs(10), 0, true).await;

        assert!(source_res.is_err());
    }

    #[tokio::test]
    async fn test_url_list_missing_content_length() {
        let server = MockServer::start();
        let _ = server.mock(|when, then| {
            when.method(httpmock::Method::HEAD);
            then.status(200).header("accept-ranges", "bytes");
        });

        let urls: Vec<_> = ["/1", "/2"].iter().map(|&path| server.url(path)).collect();
        let source_res = UrlList::new(urls, true, Duration::from_secs(10), 0, true).await;

        assert!(source_res.is_err());
    }

    #[tokio::test]
    async fn test_non_usize_content_length() {
        let server = MockServer::start();
        let _ = server.mock(|when, then| {
            when.method(httpmock::Method::HEAD);
            then.status(200)
                .header("accept-ranges", "bytes")
                .header("content-length", "not a number");
        });

        let urls: Vec<_> = ["/1", "/2"].iter().map(|&path| server.url(path)).collect();
        let source_res = UrlList::new(urls, true, Duration::from_secs(10), 0, true).await;

        assert!(source_res.is_err());
    }

    #[tokio::test]
    async fn test_size() {
        let server = MockServer::start();
        let _ = server.mock(|when, then| {
            when.method(httpmock::Method::HEAD);
            then.status(200)
                .header("accept-ranges", "bytes")
                .header("content-length", TEST_CONTENTS.len().to_string());
        });

        let urls: Vec<_> = ["/1", "/2"].iter().map(|&path| server.url(path)).collect();
        let source = UrlList::new(urls.clone(), true, Duration::from_secs(10), 0, true)
            .await
            .unwrap();
        let size = source.size(&urls[0]).await.unwrap();

        assert_eq!(size, Some(TEST_CONTENTS.len() as u64));
    }

    #[tokio::test]
    async fn test_get_first_100_bytes() {
        let server = MockServer::start();
        let _ = server.mock(|when, then| {
            when.method(httpmock::Method::HEAD);
            then.status(200)
                .header("accept-ranges", "bytes")
                .header("content-length", TEST_CONTENTS.len().to_string());
        });
        let _ = server.mock(|when, then| {
            when.method(httpmock::Method::GET);
            then.status(200)
                .header("accept-ranges", "bytes")
                .header("content-length", 100.to_string())
                .body(&TEST_CONTENTS[0..100]);
        });

        let urls: Vec<_> = ["/1", "/2"].iter().map(|&path| server.url(path)).collect();
        let source = UrlList::new(urls.clone(), true, Duration::from_secs(10), 0, true)
            .await
            .unwrap();
        let chunk = source.get_chunk(&urls[0], 0, 100).await.unwrap();

        assert_eq!(chunk.len(), 100);
        assert_eq!(&chunk, &TEST_CONTENTS.as_bytes()[0..100]);
    }
}
