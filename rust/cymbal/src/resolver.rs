use crate::{
    error::{Error, JsResolveErr},
    symbol_store::SymbolStore,
    types::frames::{Frame, RawFrame},
};
use axum::async_trait;
use sourcemap::SourceMap;

#[async_trait]
pub trait Resolver: Send + Sync + 'static {
    // TODO - I'm not totally convinced this resolver interface shouldn't enforce
    // some kind of batch-style use (take a symbol set ref and a list of frame
    // explicitly? I'm not sure)... right now this interface is prone to "holding it
    // wrong" type performance issues. Resolvers should maybe even encode a "submit"
    // style interface, where users are expected to send them work in a stream and
    // asynchronously get back results - which would permit internal batching etc.
    // Idk, that's a lot of complexity. I'm a lot less happy with this interface
    // than I am with the store one, though.
    async fn resolve(&self, raw: RawFrame, team_id: i32) -> Result<Frame, Error>;
}

pub struct ResolverImpl {
    pub store: Box<dyn SymbolStore>,
}

impl ResolverImpl {
    pub fn new(store: Box<dyn SymbolStore>) -> Self {
        Self { store }
    }

    async fn resolve_impl(&self, raw: &RawFrame, team_id: i32) -> Result<Frame, Error> {
        let source_ref = raw.source_ref()?;
        let source = self.store.fetch(team_id, source_ref).await?;

        // Since we only support js right now, this is all we do. Everything from here
        // is js specific
        let RawFrame::JavaScript(raw) = raw;
        let sm = SourceMap::from_reader(source.as_slice()).map_err(JsResolveErr::from)?;
        let token = sm.lookup_token(raw.line, raw.column).ok_or_else(|| {
            // Unwrap is safe because, if this frame couldn't give us a source ref, we'd know already
            JsResolveErr::TokenNotFound(raw.source_ref().unwrap().to_string(), raw.line, raw.column)
        })?;

        Ok((raw, token).into())
    }
}

#[async_trait]
impl Resolver for ResolverImpl {
    async fn resolve(&self, raw: RawFrame, team_id: i32) -> Result<Frame, Error> {
        match self.resolve_impl(&raw, team_id).await {
            Ok(frame) => Ok(frame),
            Err(e) => raw.try_handle_resolve_error(e),
        }
    }
}

#[cfg(test)]
mod test {
    use common_types::ClickHouseEvent;
    use httpmock::MockServer;

    use crate::{
        config::Config,
        resolver::Resolver,
        symbol_store::{basic::BasicStore, caching::CachingStore},
        types::{frames::RawFrame, ErrProps},
    };

    use super::ResolverImpl;

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
        let mut test_stack: Vec<RawFrame> = props.exception_list[0]
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

        let store = BasicStore::new(&config).unwrap();
        // We're even going to assert we only hit the mockserver once for the source and sourcemap
        let store = CachingStore::new(Box::new(store), 10_000_000);

        let resolver = ResolverImpl::new(Box::new(store));

        let mut resolved_frames = Vec::new();
        for frame in test_stack {
            let resolved = resolver.resolve(frame, 1).await.unwrap();
            resolved_frames.push(resolved);
        }

        // The use of the caching layer is tested here - we should only have hit the server once
        source_mock.assert_hits(1);
        map_mock.assert_hits(1);
    }
}
