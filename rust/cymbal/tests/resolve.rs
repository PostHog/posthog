use core::str;
use std::sync::Arc;

use axum::async_trait;
use common_types::ClickHouseEvent;
use cymbal::{
    config::Config,
    frames::{Frame, RawFrame},
    symbol_store::{
        caching::{Caching, SymbolSetCache},
        chunk_id::OrChunkId,
        hermesmap::HermesMapProvider,
        proguard::ProguardProvider,
        sourcemap::{OwnedSourceMapCache, SourcemapProvider},
        Catalog, Fetcher, Parser,
    },
    types::{RawErrProps, Stacktrace},
};
use httpmock::MockServer;
use posthog_symbol_data::{read_symbol_data, SourceAndMap};
use symbolic::sourcemapcache::SourcePosition;
use tokio::sync::Mutex;

const CHUNK_PATH: &str = "/static/chunk-PGUQKT6S.js";
const MINIFIED: &[u8] = include_bytes!("../tests/static/chunk-PGUQKT6S.js");
const MAP: &[u8] = include_bytes!("../tests/static/chunk-PGUQKT6S.js.map");
const EXAMPLE_EXCEPTION: &str = include_str!("../tests/static/raw_ch_exception_list.json");

struct NoOpChunkIdFetcher<P> {
    inner: P,
}

#[async_trait]
impl<P> Fetcher for NoOpChunkIdFetcher<P>
where
    P: Fetcher,
    P::Ref: Send,
{
    type Ref = OrChunkId<P::Ref>;
    type Fetched = P::Fetched;
    type Err = P::Err;

    async fn fetch(&self, team_id: i32, r: Self::Ref) -> Result<Self::Fetched, Self::Err> {
        let r = match r {
            OrChunkId::Inner(r) => r,
            OrChunkId::ChunkId(_) => panic!("Unexpected chunk id"),
            OrChunkId::Both { inner, id: _ } => inner,
        };

        self.inner.fetch(team_id, r).await
    }
}

#[async_trait]
impl<P> Parser for NoOpChunkIdFetcher<P>
where
    P: Parser,
    P::Source: Send,
{
    type Source = P::Source;
    type Set = P::Set;
    type Err = P::Err;

    async fn parse(&self, source: Self::Source) -> Result<Self::Set, Self::Err> {
        self.inner.parse(source).await
    }
}

#[tokio::test]
async fn end_to_end_resolver_test() {
    let server = MockServer::start();

    let source_mock = server.mock(|when, then| {
        when.method("GET").path(CHUNK_PATH);
        then.status(200).body(MINIFIED);
    });

    let map_mock = server.mock(|when, then| {
        // Our minified example source uses a relative URL, formatted like this
        when.method("GET").path(format!("{CHUNK_PATH}.map"));
        then.status(200).body(MAP);
    });

    let exception: ClickHouseEvent = serde_json::from_str(EXAMPLE_EXCEPTION).unwrap();
    let mut props: RawErrProps = serde_json::from_str(&exception.properties.unwrap()).unwrap();
    let Stacktrace::Raw {
        frames: mut test_stack,
    } = props.exception_list.swap_remove(0).stack.unwrap()
    else {
        panic!("Expected a Raw stacktrace")
    };

    // We're going to pretend out stack consists exclusively of JS frames whose source
    // we have locally
    test_stack.retain(|s| {
        let RawFrame::JavaScriptWeb(s) = s else {
            panic!("Expected a JavaScript frame")
        };
        s.source_url.as_ref().unwrap().contains(CHUNK_PATH)
    });

    for frame in test_stack.iter_mut() {
        let RawFrame::JavaScriptWeb(frame) = frame else {
            panic!("Expected a JavaScript frame")
        };
        // Our test data contains our /actual/ source urls - we need to swap that to localhost
        // When I first wrote this test, I forgot to do this, and it took me a while to figure out
        // why the test was passing before I'd even set up the mockserver - which was pretty cool, tbh
        frame.source_url = Some(server.url(CHUNK_PATH).to_string());
    }

    let mut config = Config::init_with_defaults().unwrap();
    config.allow_internal_ips = true; // We're hitting localhost for the tests

    let sourcemap = SourcemapProvider::new(&config);
    let cache = Arc::new(Mutex::new(SymbolSetCache::new(
        config.symbol_store_cache_max_bytes,
    )));

    let wrapped = NoOpChunkIdFetcher { inner: sourcemap };
    let hmp = NoOpChunkIdFetcher {
        inner: HermesMapProvider {},
    };

    let pgp = NoOpChunkIdFetcher {
        inner: ProguardProvider {},
    };

    let catalog = Catalog::new(Caching::new(wrapped, cache), hmp, pgp);

    let mut resolved_frames = Vec::new();
    for frame in test_stack {
        resolved_frames.push(frame.resolve(exception.team_id, &catalog).await.unwrap());
    }

    // The use of the caching layer is tested here - we should only have hit the server once
    source_mock.assert_hits(1);
    map_mock.assert_hits(1);
}

#[tokio::test]
async fn sourcemap_nulls_dont_go_on_frames() {
    let content = "{\"colno\":15,\"filename\":\"irrelevant_for_test\",\"function\":\"?\",\"in_app\":true,\"lineno\":476,\"platform\":\"web:javascript\"}";
    let frame: RawFrame = serde_json::from_str(content).unwrap();

    let jsdata_bytes = include_bytes!("static/sourcemap_with_nulls.jsdata").to_vec();
    let data: SourceAndMap = read_symbol_data(jsdata_bytes).unwrap();
    let smc = OwnedSourceMapCache::from_source_and_map(data).unwrap();
    let c = smc.get_smc();

    let RawFrame::JavaScriptWeb(frame) = frame else {
        panic!("Expected a JavaScript web frame")
    };

    let location = frame.location.clone().unwrap();

    let token = c
        .lookup(SourcePosition::new(location.line - 1, location.column))
        .unwrap();

    let res = Frame::from((&frame, token));

    assert!(!res.source.unwrap().contains('\0'));
}
