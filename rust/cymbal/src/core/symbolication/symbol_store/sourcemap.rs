use std::{collections::HashMap, net::IpAddr, sync::Arc, time::Duration};

use async_trait::async_trait;
use base64::Engine;
use bytes::Bytes;
use futures::StreamExt;
use posthog_symbol_data::{read_symbol_data_with_byte_count, write_symbol_data, SourceAndMap};
use reqwest::Url;
use sqlx::PgPool;
use symbolic::sourcemapcache::{SourceMapCache, SourceMapCacheWriter};
use tracing::{debug, info, warn};

use crate::{
    core::config::ResolverConfig,
    error::{JsResolveErr, ResolveError, UnhandledError},
    metric_consts::{
        CHUNK_ID_RESCUED_FROM_BODY, SOURCEMAP_BODY_FETCHES, SOURCEMAP_BODY_REF_FOUND,
        SOURCEMAP_EXTERNAL_BYTES, SOURCEMAP_FETCH, SOURCEMAP_HEADER_FOUND, SOURCEMAP_NOT_FOUND,
        SOURCEMAP_PARSE, SYMBOL_SET_DECOMPRESSED_BYTES,
    },
};

use super::{
    caching::Countable,
    chunk_id::{load_symbol_set_data, SymbolSetLoadResult},
    dart_minified_names::parse_dart_minified_names,
    BlobClient, Fetcher, Parser,
};

pub struct SourcemapProvider {
    pub client: reqwest::Client,
    pub chunk_id_rescue: Option<ChunkIdRescue>,
    pub max_response_bytes: usize,
    allow_internal_ips: bool,
}

/// How many redirects we follow. Installing a custom policy to vet each hop replaces reqwest's
/// default limit, so we have to impose our own.
const MAX_REDIRECTS: usize = 10;

/// Rejects URLs whose host is an IP literal that isn't globally routable.
///
/// `PublicIPv4Resolver` only ever sees hostnames: hyper skips DNS resolution
/// entirely when the host is already an IP literal, so `http://169.254.169.254/` or
/// `http://127.0.0.1:6379/` would otherwise sail straight past it. `Url::parse` normalizes the
/// octal, hex and integer IPv4 forms, so obfuscated literals arrive here as plain addresses.
///
/// Hostnames are passed through, to be vetted at connect time by whichever layer owns that:
/// `PublicIPv4Resolver` normally, or the egress proxy when one is configured.
fn ensure_fetchable_host(url: &Url, allow_internal_ips: bool) -> Result<(), JsResolveErr> {
    if allow_internal_ips {
        return Ok(());
    }

    let Some(host) = url.host_str() else {
        return Err(JsResolveErr::BlockedUrl(url.to_string()));
    };

    // IPv6 literals are bracketed in URLs, but `IpAddr` wants them bare.
    let bare = host
        .strip_prefix('[')
        .and_then(|h| h.strip_suffix(']'))
        .unwrap_or(host);

    let Ok(ip) = bare.parse::<IpAddr>() else {
        return Ok(());
    };

    if common_dns::is_global_ip(&ip) {
        return Ok(());
    }

    Err(JsResolveErr::BlockedUrl(url.to_string()))
}

#[derive(Clone)]
pub struct ChunkIdRescue {
    pub pool: PgPool,
    pub blob_client: Arc<dyn BlobClient>,
    pub bucket: String,
}

// Sigh. Later we can be smarter here to only do the parse once, but it involves
// `unsafe` for lifetime reasons. On the other hand, the parse is cheap, so maybe
// it doesn't matter?
#[derive(Debug)]
pub struct OwnedSourceMapCache {
    data: Vec<u8>,
    /// dart2js minified names mapping (minified -> original) for Flutter Web support.
    /// Parsed from the x_org_dartlang_dart2js.minified_names.global extension.
    dart_minified_names: Option<HashMap<String, String>>,
    /// Decompressed byte count from the symbol_data container, used for cache memory accounting.
    decompressed_bytes: usize,
}

impl OwnedSourceMapCache {
    pub fn new(data: Vec<u8>) -> Result<Self, symbolic::sourcemapcache::Error> {
        // Pass-through parse once to assert we're given valid data, so the unwrap below
        // is safe.
        SourceMapCache::parse(&data)?;
        let decompressed_bytes = data.len();
        Ok(Self {
            data,
            dart_minified_names: None,
            decompressed_bytes,
        })
    }

    pub fn from_source_and_map(
        sam: SourceAndMap,
        decompressed_bytes: usize,
    ) -> Result<Self, symbolic::sourcemapcache::SourceMapCacheWriterError> {
        // Parse dart2js minified names before we lose access to the raw JSON
        let dart_minified_names = parse_dart_minified_names(&sam.sourcemap);

        let mut data = Vec::with_capacity(sam.minified_source.len() + sam.sourcemap.len() + 16);
        let smcw = SourceMapCacheWriter::new(&sam.minified_source, &sam.sourcemap)?;
        smcw.serialize(&mut data).unwrap();
        Ok(Self {
            data,
            dart_minified_names,
            decompressed_bytes,
        })
    }

    pub fn get_smc(&self) -> SourceMapCache<'_> {
        // UNWRAP - we've already parsed this data once, so we know it's valid
        SourceMapCache::parse(&self.data).unwrap()
    }

    /// Returns the dart2js minified names map if this sourcemap has the extension.
    /// Used for remapping Flutter Web minified exception types like "minified:BA".
    pub fn get_dart_minified_names(&self) -> Option<&HashMap<String, String>> {
        self.dart_minified_names.as_ref()
    }
}

impl Countable for OwnedSourceMapCache {
    fn byte_count(&self) -> usize {
        self.decompressed_bytes
    }
}

impl SourcemapProvider {
    pub fn new(config: &ResolverConfig) -> Self {
        let timeout = Duration::from_secs(config.sourcemap_timeout_seconds);
        let connect_timeout = Duration::from_secs(config.sourcemap_connect_timeout_seconds);
        let mut client = reqwest::Client::builder()
            .timeout(timeout)
            .connect_timeout(connect_timeout);

        fn valid_proxy_url(var: &str) -> bool {
            std::env::var(var)
                .ok()
                .filter(|v| !v.is_empty())
                .and_then(|v| reqwest::Url::parse(&v).ok())
                .is_some()
        }

        let has_proxy = valid_proxy_url("HTTP_PROXY")
            || valid_proxy_url("HTTPS_PROXY")
            || valid_proxy_url("http_proxy")
            || valid_proxy_url("https_proxy");

        if has_proxy {
            // When an egress proxy (e.g. smokescreen) is configured, it owns vetting where a
            // *hostname* ends up resolving. We can't do that ourselves here: PublicIPv4Resolver
            // would block the connection to the proxy itself, since the proxy resolves to a
            // cluster-internal IP. `ensure_fetchable_host` below still applies either way - it
            // inspects the target url's host, not the proxy's, so it costs the proxy nothing.
            info!("HTTP(S)_PROXY is set, skipping PublicIPv4Resolver (proxy vets hostnames)");
        } else if !config.allow_internal_ips {
            client = client.dns_resolver(Arc::new(common_dns::PublicIPv4Resolver {}));
        } else {
            warn!("Internal IPs are allowed, this is a security risk");
        }

        // Redirect targets are as attacker-controlled as the original URL, so vet every hop the
        // same way. Whoever vets hostnames above covers those; this catches IP-literal hops,
        // which never reach a DNS resolver at all.
        let allow_internal_ips = config.allow_internal_ips;
        client = client.redirect(reqwest::redirect::Policy::custom(move |attempt| {
            // `previous` holds the urls already requested, so its length is the number of this
            // hop - refusing above the limit follows exactly MAX_REDIRECTS of them.
            if attempt.previous().len() > MAX_REDIRECTS {
                return attempt.error(JsResolveErr::RedirectError(format!(
                    "exceeded {MAX_REDIRECTS} redirects"
                )));
            }
            match ensure_fetchable_host(attempt.url(), allow_internal_ips) {
                Ok(()) => attempt.follow(),
                Err(e) => attempt.error(e),
            }
        }));

        let client = client.build().unwrap();

        Self {
            client,
            chunk_id_rescue: None,
            max_response_bytes: config.sourcemap_max_response_bytes,
            allow_internal_ips,
        }
    }

    pub fn with_chunk_id_rescue(
        mut self,
        pool: PgPool,
        blob_client: Arc<dyn BlobClient>,
        bucket: String,
    ) -> Self {
        self.chunk_id_rescue = Some(ChunkIdRescue {
            pool,
            blob_client,
            bucket,
        });
        self
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
    type Fetched = Bytes;
    type Err = ResolveError;
    async fn fetch(&self, team_id: i32, r: Url) -> Result<Bytes, Self::Err> {
        let start = common_metrics::timing_guard(SOURCEMAP_FETCH, &[]);
        let peek = find_sourcemap_url(
            &self.client,
            r,
            self.max_response_bytes,
            self.allow_internal_ips,
        )
        .await?;

        let start = start.label("found_url", "true");

        if let Some(rescue) = &self.chunk_id_rescue {
            if let Some(chunk_id) = peek.chunk_id_from_body.as_deref() {
                if let Some(data) = try_chunk_id_rescue(rescue, team_id, chunk_id).await? {
                    start
                        .label("found_data", "true")
                        .label("rescued", "true")
                        .fin();
                    return Ok(data);
                }
            }
        }

        let sourcemap = match peek.sourcemap_url {
            SourceMappingUrl::Url(sourcemap_url) => {
                fetch_source_map(
                    &self.client,
                    sourcemap_url.clone(),
                    self.max_response_bytes,
                    self.allow_internal_ips,
                )
                .await?
            }
            SourceMappingUrl::Data(data) => data,
        };

        // This isn't needed for correctness, but it gives nicer errors to users
        assert_is_sourcemap(&sourcemap)?;

        let sam = SourceAndMap {
            minified_source: peek.body,
            sourcemap,
        };
        let data = write_symbol_data(sam).map_err(JsResolveErr::JSDataError)?;

        start.label("found_data", "true").fin();

        Ok(Bytes::from(data))
    }
}

async fn try_chunk_id_rescue(
    rescue: &ChunkIdRescue,
    team_id: i32,
    chunk_id: &str,
) -> Result<Option<Bytes>, ResolveError> {
    match load_symbol_set_data(
        &rescue.pool,
        rescue.blob_client.as_ref(),
        &rescue.bucket,
        team_id,
        chunk_id,
    )
    .await
    .map_err(ResolveError::UnhandledError)?
    {
        SymbolSetLoadResult::Data(data) => {
            metrics::counter!(CHUNK_ID_RESCUED_FROM_BODY).increment(1);
            info!(
                "Rescued URL-fetched JS frame via uploaded symbol set for chunk id {}",
                chunk_id
            );
            Ok(Some(data))
        }
        SymbolSetLoadResult::MissingBlob(mut record) => {
            warn!(
                "Symbol set record for chunk id {} points to a missing S3 object",
                record.set_ref
            );
            record
                .delete(&rescue.pool)
                .await
                .map_err(ResolveError::UnhandledError)?;
            Ok(None)
        }
        SymbolSetLoadResult::Missing
        | SymbolSetLoadResult::Failed(_)
        | SymbolSetLoadResult::MissingStoragePtr(_) => Ok(None),
    }
}

#[async_trait]
impl Parser for SourcemapProvider {
    type Source = Bytes;
    type Set = OwnedSourceMapCache;
    type Err = ResolveError;
    async fn parse(&self, data: Bytes) -> Result<Self::Set, Self::Err> {
        let start = common_metrics::timing_guard(SOURCEMAP_PARSE, &[]);
        // `read_symbol_data_with_byte_count` zstd-decompresses a potentially large blob, and
        // `SourceMapCacheWriter::new` is a CPU-bound serializer. Running them on a tokio
        // worker blocks the runtime; offload to a blocking thread instead.
        let smc =
            tokio::task::spawn_blocking(move || -> Result<OwnedSourceMapCache, ResolveError> {
                let (sam, decompressed_bytes): (SourceAndMap, usize) =
                    read_symbol_data_with_byte_count(&data).map_err(JsResolveErr::JSDataError)?;
                metrics::histogram!(SYMBOL_SET_DECOMPRESSED_BYTES, "kind" => "sourcemap")
                    .record(decompressed_bytes as f64);
                OwnedSourceMapCache::from_source_and_map(sam, decompressed_bytes)
                    .map_err(|_| JsResolveErr::InvalidSourceAndMap.into())
            })
            .await
            .map_err(|e| UnhandledError::Other(format!("sourcemap parse task failed: {e}")))??;

        start.label("success", "true").fin();
        Ok(smc)
    }
}

struct JsSourcePeek {
    body: String,
    sourcemap_url: SourceMappingUrl,
    chunk_id_from_body: Option<String>,
}

const CHUNK_ID_COMMENT_PREFIXES: &[&str] = &["//# chunkId=", "//@ chunkId="];

fn extract_chunk_id_from_body(body: &str) -> Option<String> {
    for line in body.lines().rev().take(32) {
        let trimmed = line.trim();
        for prefix in CHUNK_ID_COMMENT_PREFIXES {
            if let Some(rest) = trimmed.strip_prefix(prefix) {
                let id = rest.trim();
                if !id.is_empty() {
                    return Some(id.to_string());
                }
            }
        }
    }
    None
}

async fn find_sourcemap_url(
    client: &reqwest::Client,
    start: Url,
    max_response_bytes: usize,
    allow_internal_ips: bool,
) -> Result<JsSourcePeek, ResolveError> {
    // The frame's source url comes straight off an ingested event, so vet it before we connect.
    // Every other url in here is derived from the response, and so keeps this validated host,
    // except an absolute sourcemap url - `fetch_source_map` vets that one itself.
    ensure_fetchable_host(&start, allow_internal_ips)?;

    debug!("Fetching script source from {}", start);

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
    let body = read_response_text_limited(res, &final_url, max_response_bytes).await?;
    metrics::histogram!(SOURCEMAP_EXTERNAL_BYTES, "kind" => "source").record(body.len() as f64);

    let chunk_id_from_body = extract_chunk_id_from_body(&body);

    if let Some(header_url) = header_url {
        debug!("Found sourcemap header: {:?}", header_url);
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
        return Ok(JsSourcePeek {
            body,
            sourcemap_url: url.into(),
            chunk_id_from_body,
        });
    }

    // If we didn't find a header, we have to check the body

    let lines = body.lines().rev(); // Our needle tends to be at the bottom of the haystack
    for line in lines {
        if line.starts_with("//# sourceMappingURL=") {
            metrics::counter!(SOURCEMAP_BODY_REF_FOUND).increment(1);
            let found = line.trim_start_matches("//# sourceMappingURL=");

            // If we can parse this as a data URL, we can just use that
            if let Some(data) = maybe_as_data_url(
                final_url.as_ref(),
                found,
                max_response_bytes,
                data_url_to_json_str,
            )? {
                return Ok(JsSourcePeek {
                    body,
                    sourcemap_url: SourceMappingUrl::Data(data),
                    chunk_id_from_body,
                });
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
            return Ok(JsSourcePeek {
                body,
                sourcemap_url: url.into(),
                chunk_id_from_body,
            });
        }
    }

    metrics::counter!(SOURCEMAP_NOT_FOUND).increment(1);

    // We looked in the headers and the body, and couldn't find a source map. We lastly just see if there's some data at
    // the start URL, with `.map` appended. We don't actually fetch the body here, just see if the URL resolves to a 200
    let mut test_url = start; // Move the `start` into `test_url`, since we don't need it anymore, making it mutable
    test_url.set_path(&(test_url.path().to_owned() + ".map"));
    if let Ok(res) = client.head(test_url.clone()).send().await {
        if res.status().is_success() {
            return Ok(JsSourcePeek {
                body,
                sourcemap_url: res.url().clone().into(),
                chunk_id_from_body,
            });
        }
    }

    // We failed entirely to find a sourcemap. This /might/ indicate the frame is not minified, or it might
    // just indicate someone misconfigured their sourcemaps - we'll hand this error back to the frame itself
    // to figure out.
    Err(JsResolveErr::NoSourcemap(final_url.to_string()).into())
}

async fn fetch_source_map(
    client: &reqwest::Client,
    url: Url,
    max_response_bytes: usize,
    allow_internal_ips: bool,
) -> Result<String, ResolveError> {
    // A `SourceMap` header or `//# sourceMappingURL=` comment can name an absolute url on any
    // host, so this needs vetting independently of the source url it came from.
    ensure_fetchable_host(&url, allow_internal_ips)?;

    metrics::counter!(SOURCEMAP_BODY_FETCHES).increment(1);
    let res = client.get(url).send().await.map_err(JsResolveErr::from)?;
    res.error_for_status_ref().map_err(JsResolveErr::from)?;
    let final_url = res.url().clone();
    let sourcemap = read_response_text_limited(res, &final_url, max_response_bytes).await?;
    metrics::histogram!(SOURCEMAP_EXTERNAL_BYTES, "kind" => "sourcemap")
        .record(sourcemap.len() as f64);
    Ok(sourcemap)
}

async fn read_response_text_limited(
    response: reqwest::Response,
    url: &Url,
    max_response_bytes: usize,
) -> Result<String, ResolveError> {
    let mut body = Vec::with_capacity(
        response
            .content_length()
            .and_then(|length| usize::try_from(length).ok())
            .unwrap_or_default()
            .min(max_response_bytes),
    );
    let mut stream = response.bytes_stream();

    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(JsResolveErr::from)?;
        if body.len().saturating_add(chunk.len()) > max_response_bytes {
            return Err(JsResolveErr::NetworkError(format!(
                "Response from {url} exceeded the {max_response_bytes} byte limit"
            ))
            .into());
        }
        body.extend_from_slice(&chunk);
    }

    Ok(String::from_utf8_lossy(&body).into_owned())
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
    max_response_bytes: usize,
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

    if data.len() > max_response_bytes {
        return Err(JsResolveErr::NetworkError(format!(
            "Response from {source_url} exceeded the {max_response_bytes} byte limit"
        ))
        .into());
    }

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
    use crate::error::FrameError;
    use httpmock::MockServer;

    const MINIFIED: &[u8] = include_bytes!("../../../../tests/static/chunk-PGUQKT6S.js");
    const MAP: &[u8] = include_bytes!("../../../../tests/static/chunk-PGUQKT6S.js.map");
    const MINIFIED_WITH_NO_MAP_REF: &[u8] =
        include_bytes!("../../../../tests/static/chunk-PGUQKT6S-no-map.js");
    const TEST_MAX_RESPONSE_BYTES: usize = 25_000_000;

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
        let peek = find_sourcemap_url(&client, url, TEST_MAX_RESPONSE_BYTES, true)
            .await
            .unwrap();

        let SourceMappingUrl::Url(res) = peek.sourcemap_url else {
            panic!("Expected URL, got something else");
        };

        // We're doing relative-URL resolution here, so we have to account for that
        let expected = server.url("/static/chunk-PGUQKT6S.js.map").parse().unwrap();
        assert_eq!(res, expected);
        mock.assert_hits(1);
    }

    #[tokio::test]
    async fn fetch_decompresses_gzip_source() {
        let server = MockServer::start();
        let compressed = common_compression::compress_gzip(MINIFIED).unwrap();

        let source_mock = server.mock(|when, then| {
            when.method("GET").path("/static/chunk-PGUQKT6S.js");
            then.status(200)
                .header("Content-Encoding", "gzip")
                .body(compressed);
        });
        let map_mock = server.mock(|when, then| {
            when.method("GET").path("/static/chunk-PGUQKT6S.js.map");
            then.status(200).body(MAP);
        });

        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.allow_internal_ips = true;
        let provider = SourcemapProvider::new(&config);
        let url = server.url("/static/chunk-PGUQKT6S.js").parse().unwrap();
        let data = provider.fetch(1, url).await.unwrap();
        let (source_and_map, _): (SourceAndMap, usize) =
            read_symbol_data_with_byte_count(&data).unwrap();

        assert_eq!(source_and_map.minified_source.as_bytes(), MINIFIED);
        source_mock.assert_hits(1);
        map_mock.assert_hits(1);
    }

    #[tokio::test]
    async fn fetch_rejects_oversized_compressed_source() {
        let server = MockServer::start();
        let compressed = common_compression::compress_gzip(&vec![b'a'; 1024]).unwrap();

        let source_mock = server.mock(|when, then| {
            when.method("GET").path("/static/oversized.js");
            then.status(200)
                .header("Content-Encoding", "gzip")
                .body(compressed);
        });

        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.allow_internal_ips = true;
        config.sourcemap_max_response_bytes = 128;
        let provider = SourcemapProvider::new(&config);
        let url = server.url("/static/oversized.js").parse().unwrap();

        let error = provider.fetch(1, url).await.unwrap_err();

        assert!(matches!(
            error,
            ResolveError::ResolutionError(FrameError::JavaScript(JsResolveErr::NetworkError(
                message
            ))) if message.contains("exceeded the 128 byte limit")
        ));
        source_mock.assert_hits(1);
    }

    #[tokio::test]
    async fn fetch_rejects_oversized_compressed_sourcemap() {
        let server = MockServer::start();
        let source = "console.log('hello');\n//# sourceMappingURL=oversized.js.map\n";
        let compressed_map = common_compression::compress_gzip(&vec![b'a'; 1024]).unwrap();

        let source_mock = server.mock(|when, then| {
            when.method("GET").path("/static/oversized.js");
            then.status(200).body(source);
        });
        let map_mock = server.mock(|when, then| {
            when.method("GET").path("/static/oversized.js.map");
            then.status(200)
                .header("Content-Encoding", "gzip")
                .body(compressed_map);
        });

        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.allow_internal_ips = true;
        config.sourcemap_max_response_bytes = 128;
        let provider = SourcemapProvider::new(&config);
        let url = server.url("/static/oversized.js").parse().unwrap();

        let error = provider.fetch(1, url).await.unwrap_err();

        assert!(matches!(
            error,
            ResolveError::ResolutionError(FrameError::JavaScript(JsResolveErr::NetworkError(
                message
            ))) if message.contains("exceeded the 128 byte limit")
        ));
        source_mock.assert_hits(1);
        map_mock.assert_hits(1);
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

        let mut config = ResolverConfig::init_with_defaults().unwrap();
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

        let mut config = ResolverConfig::init_with_defaults().unwrap();
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
        let data_url_example: &str =
            include_str!("../../../../tests/static/inline_sourcemap_example.js");

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
        let peek = find_sourcemap_url(&client, url, TEST_MAX_RESPONSE_BYTES, true)
            .await
            .unwrap();

        let SourceMappingUrl::Data(res) = peek.sourcemap_url else {
            panic!("Expected Data, got something else");
        };

        let expected = include_str!("../../../../tests/static/inline_sourcemap_example.js.map");

        assert_eq!(res.trim(), expected.trim());

        mock.assert_hits(1);
    }

    #[test]
    fn data_url_rejects_decoded_payload_over_limit() {
        let error = maybe_as_data_url(
            "https://example.com/chunk.js",
            "data:application/json;base64,eHh4eHh4eHg=",
            4,
            data_url_to_json_str,
        )
        .unwrap_err();

        assert!(matches!(
            error,
            ResolveError::ResolutionError(FrameError::JavaScript(JsResolveErr::NetworkError(
                message
            ))) if message.contains("exceeded the 4 byte limit")
        ));
    }

    #[test]
    fn ensure_fetchable_host_blocks_internal_ip_literals() {
        // Literal IPs never reach PublicIPv4Resolver, so this guard is the only thing
        // standing between an ingested frame url and an internal host.
        let blocked = [
            "http://127.0.0.1/app.js",
            "http://127.0.0.1:6379/app.js",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.5/app.js",
            "http://192.168.1.1/app.js",
            "http://172.16.0.1/app.js",
            "http://100.64.0.1/app.js",
            "http://[::1]/app.js",
            // Userinfo can dress a literal up as a hostname, but the host is still an IP.
            "http://www.example.com@127.0.0.1/app.js",
        ];

        for raw in blocked {
            let url: Url = raw.parse().unwrap();
            assert!(
                matches!(
                    ensure_fetchable_host(&url, false),
                    Err(JsResolveErr::BlockedUrl(_))
                ),
                "expected {raw} to be blocked"
            );
            // The local-development escape hatch still lets these through.
            assert!(
                ensure_fetchable_host(&url, true).is_ok(),
                "expected {raw} to be allowed when internal IPs are permitted"
            );
        }

        // Obfuscated literals: `Url::parse` normalizes these to plain addresses per the URL
        // spec. If a form fails to parse instead, that's equally fine - we never fetch it.
        for raw in ["http://2130706433/app.js", "http://0177.0.0.1/app.js"] {
            let Ok(url) = raw.parse::<Url>() else {
                continue;
            };
            assert_eq!(
                url.host_str(),
                Some("127.0.0.1"),
                "expected {raw} to normalize to a plain address"
            );
            assert!(
                matches!(
                    ensure_fetchable_host(&url, false),
                    Err(JsResolveErr::BlockedUrl(_))
                ),
                "expected {raw} to be blocked, normalized to {url}"
            );
        }

        let allowed = [
            "http://8.8.8.8/app.js",
            "https://example.com/static/app.js",
            // Hostnames are the DNS resolver's job, so the guard waves them through and
            // PublicIPv4Resolver rejects them at connect time.
            "http://localhost/app.js",
        ];

        for raw in allowed {
            let url: Url = raw.parse().unwrap();
            assert!(
                ensure_fetchable_host(&url, false).is_ok(),
                "expected {raw} to pass the guard"
            );
        }
    }

    #[tokio::test]
    async fn fetch_refuses_ip_literal_that_bypasses_the_dns_resolver() {
        let server = MockServer::start();
        let mock = server.mock(|when, then| {
            when.method("GET").path("/static/chunk-PGUQKT6S.js");
            then.status(200).body(MINIFIED);
        });

        // httpmock listens on a 127.0.0.1 literal, which hyper connects to without ever
        // consulting the DNS resolver, so only the host guard can stop this fetch.
        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.allow_internal_ips = false;
        let provider = SourcemapProvider::new(&config);
        let url: Url = server.url("/static/chunk-PGUQKT6S.js").parse().unwrap();

        let error = provider.fetch(1, url).await.unwrap_err();

        assert!(
            matches!(
                error,
                ResolveError::ResolutionError(FrameError::JavaScript(JsResolveErr::BlockedUrl(
                    ref blocked
                ))) if blocked.contains("127.0.0.1")
            ),
            "unexpected error: {error:?}"
        );
        mock.assert_hits(0);
    }

    #[test]
    fn extract_chunk_id_from_body_handles_known_prefixes() {
        let canonical =
            "/* code */\n//# sourceMappingURL=foo.map\n//# chunkId=019dfdfb-2ec9-7d71-84a2-6c269108158f\n";
        assert_eq!(
            extract_chunk_id_from_body(canonical),
            Some("019dfdfb-2ec9-7d71-84a2-6c269108158f".to_string())
        );

        assert_eq!(
            extract_chunk_id_from_body("//@ chunkId=abc-123\n"),
            Some("abc-123".to_string())
        );

        assert_eq!(extract_chunk_id_from_body("just some code"), None);
        assert_eq!(extract_chunk_id_from_body("//# chunkId=\n"), None);
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn chunk_id_rescue_short_circuits_when_map_url_is_404(db: PgPool) {
        use crate::symbolication::symbol_store::{saving::SymbolSetRecord, MockS3Client};
        use chrono::Utc;
        use mockall::predicate;
        use uuid::Uuid;

        const RESCUE_BUCKET: &str = "test-bucket";

        let chunk_id = "019dfdfb-2ec9-7d71-84a2-6c269108158f".to_string();
        let map_path = "/static/chunk.js.map";
        let js_path = "/static/chunk.js";

        let server = MockServer::start();
        let body = format!(
            "console.log('hello');\n//# sourceMappingURL={map_path}\n//# chunkId={chunk_id}\n"
        );
        let js_mock = server.mock(|when, then| {
            when.method("GET").path(js_path);
            then.status(200).body(body);
        });
        let map_mock = server.mock(|when, then| {
            when.method("GET").path(map_path);
            then.status(404);
        });

        let storage_key = format!("symbolsets/{}", Uuid::now_v7());
        SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id: 1,
            set_ref: chunk_id.clone(),
            storage_ptr: Some(storage_key.clone()),
            failure_reason: None,
            created_at: Utc::now(),
            content_hash: Some("fake-hash".to_string()),
            last_used: Some(Utc::now()),
        }
        .save(&db)
        .await
        .unwrap();

        let saved_payload = Bytes::from(
            write_symbol_data(SourceAndMap {
                minified_source: String::from_utf8(MINIFIED.to_vec()).unwrap(),
                sourcemap: String::from_utf8(MAP.to_vec()).unwrap(),
            })
            .unwrap(),
        );
        let saved_payload_for_mock = saved_payload.clone();

        let mut s3 = MockS3Client::default();
        s3.expect_get()
            .with(
                predicate::eq(RESCUE_BUCKET),
                predicate::eq(storage_key.clone()),
            )
            .returning(move |_, _| Ok(Some(saved_payload_for_mock.clone())));
        let s3: Arc<dyn BlobClient> = Arc::new(s3);

        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.allow_internal_ips = true;
        let provider = SourcemapProvider::new(&config).with_chunk_id_rescue(
            db.clone(),
            s3,
            RESCUE_BUCKET.to_string(),
        );

        let url = server.url(js_path).parse().unwrap();
        let got = provider.fetch(1, url).await.unwrap();

        assert_eq!(got, saved_payload, "rescue should return saved S3 bytes");
        js_mock.assert_hits(1);
        map_mock.assert_hits(0);
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn chunk_id_rescue_falls_through_when_no_db_record(db: PgPool) {
        use crate::symbolication::symbol_store::MockS3Client;

        const RESCUE_BUCKET: &str = "test-bucket";

        let server = MockServer::start();
        let js_mock = server.mock(|when, then| {
            when.method("GET").path("/static/chunk-PGUQKT6S.js");
            then.status(200).body(MINIFIED);
        });
        let map_mock = server.mock(|when, then| {
            when.method("GET").path("/static/chunk-PGUQKT6S.js.map");
            then.status(200).body(MAP);
        });

        let s3: Arc<dyn BlobClient> = Arc::new(MockS3Client::default());

        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.allow_internal_ips = true;
        let provider = SourcemapProvider::new(&config).with_chunk_id_rescue(
            db.clone(),
            s3,
            RESCUE_BUCKET.to_string(),
        );

        let url = server.url("/static/chunk-PGUQKT6S.js").parse().unwrap();
        provider.fetch(1, url).await.unwrap();

        js_mock.assert_hits(1);
        map_mock.assert_hits(1);
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn chunk_id_rescue_deletes_stale_record_when_blob_is_missing(db: PgPool) {
        use crate::symbolication::symbol_store::{saving::SymbolSetRecord, MockS3Client};
        use chrono::Utc;
        use mockall::predicate;
        use uuid::Uuid;

        const RESCUE_BUCKET: &str = "test-bucket";

        let chunk_id = "019dfdfb-2ec9-7d71-84a2-6c269108158f".to_string();
        let storage_key = format!("symbolsets/{}", Uuid::now_v7());

        SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id: 1,
            set_ref: chunk_id.clone(),
            storage_ptr: Some(storage_key.clone()),
            failure_reason: None,
            created_at: Utc::now(),
            content_hash: Some("fake-hash".to_string()),
            last_used: Some(Utc::now()),
        }
        .save(&db)
        .await
        .unwrap();

        let server = MockServer::start();
        let body =
            format!("console.log('hello');\n//# sourceMappingURL=/static/chunk.js.map\n//# chunkId={chunk_id}\n");
        let js_mock = server.mock(|when, then| {
            when.method("GET").path("/static/chunk.js");
            then.status(200).body(body);
        });
        let map_mock = server.mock(|when, then| {
            when.method("GET").path("/static/chunk.js.map");
            then.status(200).body(MAP);
        });

        let mut s3 = MockS3Client::default();
        s3.expect_get()
            .with(
                predicate::eq(RESCUE_BUCKET),
                predicate::eq(storage_key.clone()),
            )
            .returning(|_, _| Ok(None));
        let s3: Arc<dyn BlobClient> = Arc::new(s3);

        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.allow_internal_ips = true;
        let provider = SourcemapProvider::new(&config).with_chunk_id_rescue(
            db.clone(),
            s3,
            RESCUE_BUCKET.to_string(),
        );

        let url = server.url("/static/chunk.js").parse().unwrap();
        provider.fetch(1, url).await.unwrap();

        assert!(SymbolSetRecord::load(&db, 1, &chunk_id)
            .await
            .unwrap()
            .is_none());
        js_mock.assert_hits(1);
        map_mock.assert_hits(1);
    }
}
