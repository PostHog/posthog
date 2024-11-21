use std::sync::Arc;

use cymbal::{
    config::Config,
    langs::js::RawJSFrame,
    symbol_store::{
        caching::{Caching, SymbolSetCache},
        sourcemap::SourcemapProvider,
        Catalog,
    },
};
use serde_json::Value;
use tokio::sync::Mutex;

/**
Input data gathered by running the following, then converting to json:
SELECT
    symbol_set.ref as filename,
    contents::json->>'mangled_name' as "function",
    (contents::json->>'in_app')::boolean as in_app,
    CASE
        WHEN contents::json->>'line' IS NOT NULL
        THEN (contents::json->>'line')::int
    END as lineno,
    CASE
        WHEN contents::json->>'column' IS NOT NULL
        THEN (contents::json->>'column')::int
    END as colno
FROM posthog_errortrackingstackframe frame
LEFT JOIN posthog_errortrackingsymbolset symbol_set
    ON frame.symbol_set_id = symbol_set.id
WHERE (contents::json->>'resolved_name') is null
    AND contents::json->>'lang' = 'javascript'
    AND symbol_set.storage_ptr IS NOT NULL;

This doesn't actually work - we don't have the original line and column number, and
so can't repeat the original resolution. I couldn't find a way to reverse that mapping
with sourcemaps, so instead I'm going to temporarily add the raw frame to the resolve
Frame.
*/
const NAMELESS_FRAMES_IN_RAW_FMT: &str = include_str!("./nameless_frames_in_raw_format.json");

#[tokio::main]
async fn main() {
    let config = Config::init_with_defaults().unwrap();
    let provider = SourcemapProvider::new(&config);
    let cache = Arc::new(Mutex::new(SymbolSetCache::new(1_000_000_000)));
    let provider = Caching::new(provider, cache);

    let catalog = Catalog::new(provider);

    let frames: Vec<Value> = serde_json::from_str(NAMELESS_FRAMES_IN_RAW_FMT).unwrap();

    // Deal with metabase giving me string-only values
    let frames: Vec<RawJSFrame> = frames
        .into_iter()
        .map(|f| {
            let mut f = f;
            let in_app = f["in_app"].as_str().unwrap() == "true";
            f["in_app"] = Value::Bool(in_app);
            let lineno: u32 = f["lineno"]
                .as_str()
                .unwrap()
                .replace(",", "")
                .parse()
                .unwrap();
            let colno: u32 = f["colno"]
                .as_str()
                .unwrap()
                .replace(",", "")
                .parse()
                .unwrap();
            f["lineno"] = Value::Number(lineno.into());
            f["colno"] = Value::Number(colno.into());
            serde_json::from_value(f).unwrap()
        })
        .collect();

    for frame in frames {
        let res = frame.resolve(0, &catalog).await.unwrap();

        if res.resolved_name.is_none() {
            panic!("Frame name not resolved: {:?}", frame);
        }
    }
}
