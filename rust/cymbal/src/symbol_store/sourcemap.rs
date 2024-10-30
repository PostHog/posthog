use std::{sync::Arc, time::Duration};

use axum::async_trait;
use reqwest::Url;
use sourcemap::SourceMap;
use tracing::{info, warn};

use crate::{
    config::Config,
    error::{Error, JsResolveErr},
    metric_consts::{
        SOURCEMAP_BODY_FETCHES, SOURCEMAP_BODY_REF_FOUND, SOURCEMAP_HEADER_FOUND,
        SOURCEMAP_NOT_FOUND, SOURCE_REF_BODY_FETCHES,
    },
};

use super::{Fetcher, Parser};

pub struct SourcemapProvider {
    pub client: reqwest::Client,
}

impl SourcemapProvider {
    pub fn new(config: &Config) -> Result<Self, Error> {
        let timeout = Duration::from_secs(config.sourcemap_timeout_seconds);
        let mut client = reqwest::Client::builder().timeout(timeout);

        if !config.allow_internal_ips {
            client = client.dns_resolver(Arc::new(common_dns::PublicIPv4Resolver {}));
        } else {
            warn!("Internal IPs are allowed, this is a security risk");
        }

        let client = client.build()?;

        Ok(Self { client })
    }
}

#[async_trait]
impl Fetcher for SourcemapProvider {
    type Ref = Url;
    async fn fetch(&self, _: i32, r: Url) -> Result<Vec<u8>, Error> {
        let sourcemap_url = find_sourcemap_url(&self.client, r).await?;
        Ok(fetch_source_map(&self.client, sourcemap_url).await?)
    }
}

impl Parser for SourcemapProvider {
    type Set = SourceMap;
    fn parse(&self, data: Vec<u8>) -> Result<Self::Set, Error> {
        Ok(SourceMap::from_reader(data.as_slice()).map_err(JsResolveErr::from)?)
    }
}

async fn find_sourcemap_url(client: &reqwest::Client, start: Url) -> Result<Url, Error> {
    info!("Fetching sourcemap from {}", start);

    // If this request fails, we cannot resolve the frame, and do not hand this error to the frames
    // failure-case handling - it just didn't work. We should tell the user about it, somehow, though.
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

        // If the header was set but is unusable, that's a js-specific resolution error - one we can try to handle,
        // or at least tell the user about.
        let url = header_url
            .to_str()
            .map_err(|_| JsResolveErr::InvalidSourceMapHeader(final_url.to_string()))?;

        let url = if url.starts_with("http") {
            url.parse()
                .map_err(|_| JsResolveErr::InvalidSourceMapUrl(url.to_string()))?
        } else {
            // It's wild to me that this is infallible - feels like it must be a bug, there's no way
            // "literally any string" is a valid URL path segment, even if there are escaping rules
            final_url.set_path(url);
            final_url
        };
        return Ok(url);
    }

    // If we didn't find a header, we have to check the body

    // Grab the body as text, and split it into lines
    metrics::counter!(SOURCE_REF_BODY_FETCHES).increment(1);
    let body = res.text().await?; // Transport error, unresolvable
    let lines = body.lines().rev(); // Our needle tends to be at the bottom of the haystack
    for line in lines {
        if line.starts_with("//# sourceMappingURL=") {
            metrics::counter!(SOURCEMAP_BODY_REF_FOUND).increment(1);
            let found = line.trim_start_matches("//# sourceMappingURL=");
            // These URLs can be relative, so we have to check if they are, and if they are, append the base URLs domain to them
            let url = if found.starts_with("http") {
                found
                    .parse()
                    .map_err(|_| JsResolveErr::InvalidSourceMapUrl(found.to_string()))?
            } else {
                final_url.set_path(found);
                final_url
            };
            return Ok(url);
        }
    }

    metrics::counter!(SOURCEMAP_NOT_FOUND).increment(1);
    // We looked in the headers and the body, and couldn't find a source map. This /might/ indicate the frame
    // is not minified, or it might just indicate someone misconfigured their sourcemaps - we'll hand this error
    // back to the frame itself to figure out.
    Err(JsResolveErr::NoSourcemap(final_url.to_string()).into())
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
        let expected = server.url("/static/chunk-PGUQKT6S.js.map").parse().unwrap();
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
        let store = SourcemapProvider::new(&config).unwrap();

        let start_url = server.url("/static/chunk-PGUQKT6S.js").parse().unwrap();

        store.fetch(1, start_url).await.unwrap();

        first_mock.assert_hits(1);
        second_mock.assert_hits(1);
    }

    // TODO - tests for the non-relative //sourcemap case, for the SourceMap header, and for the X-SourceMap header
}
