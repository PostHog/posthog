use std::{sync::Arc, time::Duration};

use axum::async_trait;
use base64::Engine;
use posthog_symbol_data::{read_symbol_data, write_symbol_data, SourceAndMap};
use reqwest::Url;
use symbolic::sourcemapcache::{SourceMapCache, SourceMapCacheWriter};
use tracing::{info, warn};

use crate::{
    config::Config,
    error::{JsResolveErr, ResolveError},
    metric_consts::{
        SOURCEMAP_BODY_FETCHES, SOURCEMAP_BODY_REF_FOUND, SOURCEMAP_FETCH, SOURCEMAP_HEADER_FOUND,
        SOURCEMAP_NOT_FOUND, SOURCEMAP_PARSE,
    },
};

use super::{Fetcher, Parser};

pub struct SourcemapProvider {
    pub client: reqwest::Client,
}

// Sigh. Later we can be smarter here to only do the parse once, but it involves
// `unsafe` for lifetime reasons. On the other hand, the parse is cheap, so maybe
// it doesn't matter?
#[derive(Debug)]
pub struct OwnedSourceMapCache {
    data: Vec<u8>,
}

impl OwnedSourceMapCache {
    pub fn new(data: Vec<u8>) -> Result<Self, symbolic::sourcemapcache::Error> {
        // Pass-through parse once to assert we're given valid data, so the unwrap below
        // is safe.
        SourceMapCache::parse(&data)?;
        Ok(Self { data })
    }

    pub fn from_source_and_map(
        sam: SourceAndMap,
    ) -> Result<Self, symbolic::sourcemapcache::SourceMapCacheWriterError> {
        let mut data = Vec::with_capacity(sam.minified_source.len() + sam.sourcemap.len() + 16);
        let smcw = SourceMapCacheWriter::new(&sam.minified_source, &sam.sourcemap)?;
        smcw.serialize(&mut data).unwrap();
        Ok(Self { data })
    }

    pub fn get_smc(&self) -> SourceMapCache {
        // UNWRAP - we've already parsed this data once, so we know it's valid
        SourceMapCache::parse(&self.data).unwrap()
    }
}

impl SourcemapProvider {
    pub fn new(config: &Config) -> Self {
        let timeout = Duration::from_secs(config.sourcemap_timeout_seconds);
        let connect_timeout = Duration::from_secs(config.sourcemap_connect_timeout_seconds);
        let mut client = reqwest::Client::builder()
            .timeout(timeout)
            .connect_timeout(connect_timeout);

        if !config.allow_internal_ips {
            client = client.dns_resolver(Arc::new(common_dns::PublicIPv4Resolver {}));
        } else {
            warn!("Internal IPs are allowed, this is a security risk");
        }

        let client = client.build().unwrap();

        Self { client }
    }
}

#[derive(Debug, Clone)]
enum SourceMappingUrl {
    Url(Url),
    Data(String),
}

impl From<Url> for SourceMappingUrl {
    fn from(url: Url) -> Self {
        Self::Url(url)
    }
}

#[async_trait]
impl Fetcher for SourcemapProvider {
    type Ref = Url;
    type Fetched = Vec<u8>;
    type Err = ResolveError;
    async fn fetch(&self, _: i32, r: Url) -> Result<Vec<u8>, Self::Err> {
        let start = common_metrics::timing_guard(SOURCEMAP_FETCH, &[]);
        let (smu, minified_source) = find_sourcemap_url(&self.client, r).await?;

        let start = start.label("found_url", "true");

        let sourcemap = match smu {
            SourceMappingUrl::Url(sourcemap_url) => {
                fetch_source_map(&self.client, sourcemap_url.clone()).await?
            }
            SourceMappingUrl::Data(data) => data,
        };

        // This isn't needed for correctness, but it gives nicer errors to users
        assert_is_sourcemap(&sourcemap)?;

        let sam = SourceAndMap {
            minified_source,
            sourcemap,
        };
        let data = write_symbol_data(sam).map_err(JsResolveErr::JSDataError)?;

        start.label("found_data", "true").fin();

        Ok(data)
    }
}

#[async_trait]
impl Parser for SourcemapProvider {
    type Source = Vec<u8>;
    type Set = OwnedSourceMapCache;
    type Err = ResolveError;
    async fn parse(&self, data: Vec<u8>) -> Result<Self::Set, Self::Err> {
        let start = common_metrics::timing_guard(SOURCEMAP_PARSE, &[]);
        let sam: SourceAndMap = read_symbol_data(data).map_err(JsResolveErr::JSDataError)?;
        let smc = OwnedSourceMapCache::from_source_and_map(sam)
            .map_err(|_| JsResolveErr::InvalidSourceAndMap)?;

        start.label("success", "true").fin();
        Ok(smc)
    }
}

async fn find_sourcemap_url(
    client: &reqwest::Client,
    start: Url,
) -> Result<(SourceMappingUrl, String), ResolveError> {
    info!("Fetching script source from {}", start);

    // If this request fails, we cannot resolve the frame, and hand this error to the frames
    // failure-case handling.
    let res = client
        .get(start.clone())
        .send()
        .await
        .map_err(JsResolveErr::from)?;

    res.error_for_status_ref().map_err(JsResolveErr::from)?;

    // we use the final URL of the response in the relative case, to account for any redirects
    let mut final_url = res.url().clone();

    // First, we check for the sourcemap headers: SourceMap, or X-SourceMap
    let headers = res.headers();
    let header_url = headers
        .get("SourceMap")
        .or_else(|| headers.get("X-SourceMap"))
        .cloned();

    // We always need the body
    let body = res.text().await.map_err(JsResolveErr::from)?;

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
        return Ok((url.into(), body));
    }

    // If we didn't find a header, we have to check the body

    let lines = body.lines().rev(); // Our needle tends to be at the bottom of the haystack
    for line in lines {
        if line.starts_with("//# sourceMappingURL=") {
            metrics::counter!(SOURCEMAP_BODY_REF_FOUND).increment(1);
            let found = line.trim_start_matches("//# sourceMappingURL=");

            // If we can parse this as a data URL, we can just use that
            if let Some(data) = maybe_as_data_url(final_url.as_ref(), found, data_url_to_json_str)?
            {
                return Ok((SourceMappingUrl::Data(data), body));
            }

            // If the found url has a scheme, we can just parse it
            let url = if found.starts_with("http") {
                found
                    .parse()
                    .map_err(|_| JsResolveErr::InvalidSourceMapUrl(found.to_string()))?
            } else if !found.contains('/') {
                // If it doesn't contain a slash, assume it only replaces the final part of the path
                let Some(segments) = final_url.path_segments() else {
                    // We should never hit this - path_segments() should always return Some for a URL
                    // that "can be base" - basically a url with a domain name and scheme - and we know
                    // final_url has that because it's the url we got the body we just parsed from.
                    return Err(JsResolveErr::InvalidSourceMapUrl(found.to_string()).into());
                };

                let mut segments = segments.collect::<Vec<_>>();
                segments.pop();
                segments.push(found);
                final_url.set_path(&segments.join("/"));
                final_url
            } else {
                final_url.set_path(found);
                final_url
            };
            return Ok((url.into(), body));
        }
    }

    metrics::counter!(SOURCEMAP_NOT_FOUND).increment(1);

    // We looked in the headers and the body, and couldn't find a source map. We lastly just see if there's some data at
    // the start URL, with `.map` appended. We don't actually fetch the body here, just see if the URL resolves to a 200
    let mut test_url = start; // Move the `start` into `test_url`, since we don't need it anymore, making it mutable
    test_url.set_path(&(test_url.path().to_owned() + ".map"));
    if let Ok(res) = client.head(test_url.clone()).send().await {
        if res.status().is_success() {
            return Ok((res.url().clone().into(), body));
        }
    }

    // We failed entirely to find a sourcemap. This /might/ indicate the frame is not minified, or it might
    // just indicate someone misconfigured their sourcemaps - we'll hand this error back to the frame itself
    // to figure out.
    Err(JsResolveErr::NoSourcemap(final_url.to_string()).into())
}

async fn fetch_source_map(client: &reqwest::Client, url: Url) -> Result<String, ResolveError> {
    metrics::counter!(SOURCEMAP_BODY_FETCHES).increment(1);
    let res = client.get(url).send().await.map_err(JsResolveErr::from)?;
    res.error_for_status_ref().map_err(JsResolveErr::from)?;
    let sourcemap = res.text().await.map_err(JsResolveErr::from)?;
    Ok(sourcemap)
}

// Below as per https://developer.mozilla.org/en-US/docs/Web/URI/Reference/Schemes/data
const DATA_SCHEME: &str = "data:";

struct DataUrlContent {
    data: Vec<u8>,
    mime_type: String,
}

// Returns none if this isn't a data URL, but Err if it is and we can't parse it
fn maybe_as_data_url<T>(
    source_url: &str,
    data: &str,
    parse_fn: impl FnOnce(DataUrlContent) -> Result<T, ResolveError>,
) -> Result<Option<T>, ResolveError> {
    if !data.starts_with(DATA_SCHEME) {
        return Ok(None);
    }

    let data = data.trim_start_matches(DATA_SCHEME);

    let (header, data) = data.split_once(',').ok_or(JsResolveErr::InvalidDataUrl(
        source_url.into(),
        "Could split into header and data segment, no comma".into(),
    ))?;

    let mut chunks = header.split(";");

    let mime_type = chunks.next().expect("split always returns 1");
    let mut b64 = "";
    match (chunks.next(), chunks.next(), chunks.next()) {
        (None, None, None) => {}
        (Some(v), None, None) => {
            b64 = v;
        }
        (Some(charset), Some(encoding), None) => {
            if charset != "charset=utf-8" {
                return Err(JsResolveErr::InvalidDataUrl(
                    source_url.into(),
                    "Only utf-8 charset is supported".into(),
                )
                .into());
            }
            if encoding != "base64" {
                return Err(JsResolveErr::InvalidDataUrl(
                    source_url.into(),
                    "Only base64 encoding is supported".into(),
                )
                .into());
            }
            b64 = encoding;
        }
        (_, _, _) => {
            return Err(JsResolveErr::InvalidDataUrl(
                source_url.into(),
                "Too many parts in data URL header".into(),
            )
            .into());
        }
    }

    // This must be either plaintext or b64 encoded data
    if !b64.is_empty() && b64 != "base64" {
        return Err(JsResolveErr::InvalidDataUrl(
            source_url.into(),
            "Only base64 data URLs are supported".into(),
        )
        .into());
    }

    let data = if b64.is_empty() {
        data.as_bytes().to_vec()
    } else {
        match base64::engine::general_purpose::STANDARD.decode(data) {
            Ok(d) => d,
            Err(e) => {
                return Err(JsResolveErr::InvalidDataUrl(
                    source_url.into(),
                    format!("Failed to decode base64 data: {e:?}"),
                )
                .into())
            }
        }
    };

    let mime_type = mime_type.to_string();

    let content = DataUrlContent { data, mime_type };

    Ok(Some(parse_fn(content)?))
}

fn data_url_to_json_str(content: DataUrlContent) -> Result<String, ResolveError> {
    if !content.mime_type.starts_with("application/json") {
        return Err(JsResolveErr::InvalidDataUrl(
            "data".into(),
            "Data URL was not a JSON mime type".into(),
        )
        .into());
    }

    let data = std::str::from_utf8(&content.data).map_err(|e| {
        JsResolveErr::InvalidDataUrl(
            "data".into(),
            format!("Data URL was not valid UTF-8: {e:?}"),
        )
    })?;

    Ok(data.to_string())
}

fn assert_is_sourcemap(data: &str) -> Result<(), ResolveError> {
    if let Err(e) = sourcemap::decode_slice(data.as_bytes()) {
        return Err(JsResolveErr::InvalidSourceMap(e.to_string()).into());
    }
    Ok(())
}

#[cfg(test)]
mod test {
    use httpmock::MockServer;

    const MINIFIED: &[u8] = include_bytes!("../../tests/static/chunk-PGUQKT6S.js");
    const MAP: &[u8] = include_bytes!("../../tests/static/chunk-PGUQKT6S.js.map");
    const MINIFIED_WITH_NO_MAP_REF: &[u8] =
        include_bytes!("../../tests/static/chunk-PGUQKT6S-no-map.js");

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
        let (res, _) = find_sourcemap_url(&client, url).await.unwrap();

        let SourceMappingUrl::Url(res) = res else {
            panic!("Expected URL, got {res:?}");
        };

        // We're doing relative-URL resolution here, so we have to account for that
        let expected = server.url("/static/chunk-PGUQKT6S.js.map").parse().unwrap();
        assert_eq!(res, expected);
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
        let store = SourcemapProvider::new(&config);

        let start_url = server.url("/static/chunk-PGUQKT6S.js").parse().unwrap();

        store.fetch(1, start_url).await.unwrap();

        first_mock.assert_hits(1);
        second_mock.assert_hits(1);
    }

    #[tokio::test]
    async fn checks_dot_map_urls_test() {
        let server = MockServer::start();

        let first_mock = server.mock(|when, then| {
            when.method("GET").path("/static/chunk-PGUQKT6S.js");
            then.status(200).body(MINIFIED_WITH_NO_MAP_REF);
        });

        // We expect cymbal to then make a HEAD request to see if the map might exist
        let head_mock = server.mock(|when, then| {
            when.method("HEAD").path("/static/chunk-PGUQKT6S.js.map");
            then.status(200);
        });

        // And then fetch it
        let second_mock = server.mock(|when, then| {
            when.method("GET").path("/static/chunk-PGUQKT6S.js.map");
            then.status(200).body(MAP);
        });

        let mut config = Config::init_with_defaults().unwrap();
        // Needed because we're using mockserver, so hitting localhost
        config.allow_internal_ips = true;
        let store = SourcemapProvider::new(&config);

        let start_url = server.url("/static/chunk-PGUQKT6S.js").parse().unwrap();

        store.fetch(1, start_url).await.unwrap();

        first_mock.assert_hits(1);
        head_mock.assert_hits(1);
        second_mock.assert_hits(1);
    }

    #[tokio::test]
    pub async fn data_url_test() {
        let data_url_example: &str = include_str!("../../tests/static/inline_sourcemap_example.js");

        let server = MockServer::start();

        let mock = server.mock(|when, then| {
            when.method("GET")
                .path("/static/inline_sourcemap_example.js");
            then.status(200).body(data_url_example);
        });

        let client = reqwest::Client::new();
        let url = server
            .url("/static/inline_sourcemap_example.js")
            .parse()
            .unwrap();
        let (res, _) = find_sourcemap_url(&client, url).await.unwrap();

        let SourceMappingUrl::Data(res) = res else {
            panic!("Expected Data, got {res:?}");
        };

        let expected = include_str!("../../tests/static/inline_sourcemap_example.js.map");

        assert_eq!(res.trim(), expected.trim());

        mock.assert_hits(1);
    }
}
