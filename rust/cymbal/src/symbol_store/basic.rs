use std::{sync::Arc, time::Duration};

use axum::async_trait;
use reqwest::Url;
use tracing::{info, warn};

use crate::{
    config::Config,
    error::Error,
    metric_consts::{
        BASIC_FETCHES, SOURCEMAP_BODY_FETCHES, SOURCEMAP_BODY_REF_FOUND, SOURCEMAP_HEADER_FOUND,
        SOURCEMAP_NOT_FOUND, SOURCE_REF_BODY_FETCHES,
    },
};

use super::{SymbolSetRef, SymbolStore};

// A store that implements basic lookups, for whatever that means for each language. In
// JS, that means it does fetching and searches for sourcemap references. In other languages,
// it might mean talking to S3, or something else. It implements no caching, and no storing of
// fetched symbol sets - other stores should wrap this one to provide that functionality.
pub struct BasicStore {
    pub client: reqwest::Client,
}

impl BasicStore {
    pub fn new(config: &Config) -> Result<Self, Error> {
        let mut client = reqwest::Client::builder();

        let timeout = Duration::from_secs(config.sourcemap_timeout_seconds);

        if !config.allow_internal_ips {
            client = client.dns_resolver(Arc::new(common_dns::PublicIPv4Resolver {}));
        } else {
            warn!("Internal IPs are allowed, this is a security risk");
        }

        let client = client.timeout(timeout).build()?;

        Ok(Self { client })
    }
}

#[async_trait]
impl SymbolStore for BasicStore {
    async fn fetch(&self, _: i32, r: SymbolSetRef) -> Result<Arc<Vec<u8>>, Error> {
        metrics::counter!(BASIC_FETCHES).increment(1);
        let SymbolSetRef::Js(sref) = r; // We only support this
        let Some(sourcemap_url) = find_sourcemap_url(&self.client, sref.clone()).await? else {
            warn!("No sourcemap URL found for {}", sref);
            // TODO - this might not actually count as an error, and simply means we don't /need/ a sourcemap
            // for a give frame, but I haven't decided how to handle that yet
            return Err(Error::InvalidSourceRef(format!(
                "No sourcemap URL found for {}",
                sref
            )));
        };
        fetch_source_map(&self.client, sourcemap_url)
            .await
            .map(Arc::new)
    }
}

async fn find_sourcemap_url(client: &reqwest::Client, start: Url) -> Result<Option<Url>, Error> {
    info!("Fetching sourcemap from {}", start);
    let res = client.get(start).send().await?;

    // we use the final URL of the response in the relative case, to account for any redirects
    let mut final_url = res.url().clone();

    // First, we check for the sourcemap headers: SourceMap, or X-SourceMap
    let headers = res.headers();
    let header_url = headers
        .get("SourceMap")
        .or_else(|| headers.get("X-SourceMap"));

    if let Some(header_url) = header_url {
        info!("Found sourcemap header: {:?}", header_url);
        metrics::counter!(SOURCEMAP_HEADER_FOUND).increment(1);
        let url = header_url.to_str().map_err(|_| {
            Error::InvalidSourceRef(format!("Failed to parse url from header of {}", res.url()))
        })?;

        let url = if url.starts_with("http") {
            url.parse()
                .map_err(|_| Error::InvalidSourceRef(format!("Failed to parse {} to a url", url)))?
        } else {
            final_url.set_path(url);
            final_url
        };
        return Ok(Some(url));
    }

    // If we didn't find a header, we have to check the body

    // Grab the body as text, and split it into lines
    metrics::counter!(SOURCE_REF_BODY_FETCHES).increment(1);
    let body = res.text().await?;
    let lines = body.lines().rev(); // Our needle tends to be at the bottom of the haystack
    for line in lines {
        if line.starts_with("//# sourceMappingURL=") {
            metrics::counter!(SOURCEMAP_BODY_REF_FOUND).increment(1);
            let found = line.trim_start_matches("//# sourceMappingURL=");
            // These URLs can be relative, so we have to check if they are, and if they are, append the base URLs domain to them
            let url = if found.starts_with("http") {
                found.parse().map_err(|_| {
                    Error::InvalidSourceRef(format!("Failed to parse url from found ref {}", found))
                })?
            } else {
                final_url.set_path(found);
                final_url
            };
            return Ok(Some(url));
        }
    }

    metrics::counter!(SOURCEMAP_NOT_FOUND).increment(1);

    Ok(None) // We didn't hit an error, but we failed to find a sourcemap for the provided URL
}

async fn fetch_source_map(client: &reqwest::Client, url: Url) -> Result<Vec<u8>, Error> {
    metrics::counter!(SOURCEMAP_BODY_FETCHES).increment(1);
    let res = client.get(url).send().await?;
    let bytes = res.bytes().await?;
    Ok(bytes.to_vec())
}

#[cfg(test)]
mod test {
    use httpmock::MockServer;

    const MINIFIED: &[u8] = include_bytes!("../../tests/static/chunk-PGUQKT6S.js");
    const MAP: &[u8] = include_bytes!("../../tests/static/chunk-PGUQKT6S.js.map");

    use super::*;

    #[tokio::test]
    async fn find_sourcemap_url_in_body_test() {
        let server = MockServer::start();

        let mock = server.mock(|when, then| {
            when.method("GET").path("/static/chunk-PGUQKT6S.js");
            then.status(200).body(MINIFIED);
        });

        let client = reqwest::Client::new();
        let url = server.url("/static/chunk-PGUQKT6S.js").parse().unwrap();
        let res = find_sourcemap_url(&client, url).await.unwrap();

        // We're doing relative-URL resolution here, so we have to account for that
        let expected = Some(server.url("/static/chunk-PGUQKT6S.js.map").parse().unwrap());
        assert_eq!(res, expected);
        mock.assert_hits(1);
    }

    #[tokio::test]
    async fn fetch_source_map_test() {
        // This ones maybe a little silly - we're almost just testing reqwest
        let server = MockServer::start();

        let mock = server.mock(|when, then| {
            when.method("GET").path("/static/chunk-PGUQKT6S.js.map");
            then.status(200).body(MAP);
        });

        let client = reqwest::Client::new();
        let url = server.url("/static/chunk-PGUQKT6S.js.map").parse().unwrap();
        let res = fetch_source_map(&client, url).await.unwrap();

        assert_eq!(res, MAP);
        mock.assert_hits(1);
    }

    #[tokio::test]
    async fn full_follows_links_test() {
        let server = MockServer::start();

        let first_mock = server.mock(|when, then| {
            when.method("GET").path("/static/chunk-PGUQKT6S.js");
            then.status(200).body(MINIFIED);
        });

        let second_mock = server.mock(|when, then| {
            when.method("GET").path("/static/chunk-PGUQKT6S.js.map");
            then.status(200).body(MAP);
        });

        let mut config = Config::init_with_defaults().unwrap();
        // Needed because we're using mockserver, so hitting localhost
        config.allow_internal_ips = true;
        let store = BasicStore::new(&config).unwrap();

        let start_url = server.url("/static/chunk-PGUQKT6S.js").parse().unwrap();

        let res = store.fetch(1, SymbolSetRef::Js(start_url)).await.unwrap();

        assert_eq!(*res, MAP);
        first_mock.assert_hits(1);
        second_mock.assert_hits(1);
    }

    // TODO - tests for the non-relative //sourcemap case, for the SourceMap header, and for the X-SourceMap header
}
