use common_types::ClickHouseEvent;
use cymbal::{
    config::Config,
    symbol_store::{sourcemap::SourcemapProvider, Catalog},
    types::{frames::RawFrame, ErrProps},
};
use httpmock::MockServer;

const CHUNK_PATH: &str = "/static/chunk-PGUQKT6S.js";
const MINIFIED: &[u8] = include_bytes!("../tests/static/chunk-PGUQKT6S.js");
const MAP: &[u8] = include_bytes!("../tests/static/chunk-PGUQKT6S.js.map");
const EXAMPLE_EXCEPTION: &str = include_str!("../tests/static/raw_ch_exception_list.json");

#[tokio::test]
async fn end_to_end_resolver_test() {
    let server = MockServer::start();

    let source_mock = server.mock(|when, then| {
        when.method("GET").path(CHUNK_PATH);
        then.status(200).body(MINIFIED);
    });

    let map_mock = server.mock(|when, then| {
        // Our minified example source uses a relative URL, formatted like this
        when.method("GET").path(format!("{}.map", CHUNK_PATH));
        then.status(200).body(MAP);
    });

    let exception: ClickHouseEvent = serde_json::from_str(EXAMPLE_EXCEPTION).unwrap();
    let props: ErrProps = serde_json::from_str(&exception.properties.unwrap()).unwrap();
    let mut test_stack: Vec<RawFrame> = props.exception_list.unwrap()[0]
        .stacktrace
        .as_ref()
        .unwrap()
        .frames
        .clone();

    // We're going to pretend out stack consists exclusively of JS frames whose source
    // we have locally
    test_stack.retain(|s| {
        let RawFrame::JavaScript(s) = s;
        s.source_url.as_ref().unwrap().contains(CHUNK_PATH)
    });

    for frame in &mut test_stack {
        let RawFrame::JavaScript(frame) = frame;
        // Our test data contains our /actual/ source urls - we need to swap that to localhost
        // When I first wrote this test, I forgot to do this, and it took me a while to figure out
        // why the test was passing before I'd even set up the mockserver - which was pretty cool, tbh
        frame.source_url = Some(server.url(CHUNK_PATH).to_string());
    }

    let mut config = Config::init_with_defaults().unwrap();
    config.allow_internal_ips = true; // We're hitting localhost for the tests

    let sourcemap = SourcemapProvider::new(&config).unwrap();

    let catalog = Catalog::new(config.symbol_store_cache_max_bytes, sourcemap);

    let mut resolved_frames = Vec::new();
    for frame in test_stack {
        resolved_frames.push(frame.resolve(exception.team_id, &catalog).await.unwrap());
    }

    println!("{:?}", resolved_frames);

    // The use of the caching layer is tested here - we should only have hit the server once
    source_mock.assert_hits(1);
    map_mock.assert_hits(1);
}
