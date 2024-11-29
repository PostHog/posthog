use std::{cmp::min, collections::HashMap, sync::Arc};

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
    contents::json->>'junk_drawer' as junk_drawer
FROM posthog_errortrackingstackframe frame
LEFT JOIN posthog_errortrackingsymbolset symbol_set
    ON frame.symbol_set_id = symbol_set.id
WHERE (contents::json->>'resolved_name') is n
    AND contents::json->>'lang' = 'javascript'
    AND contents::json->>'junk_drawer' IS NOT NULL
    AND symbol_set.storage_ptr IS NOT NULL;

*/
const NAMELESS_FRAMES_IN_RAW_FMT: &str = include_str!("./no_resolved_name_raw_frames.json");

#[tokio::main]
async fn main() {
    let start_at: usize = std::env::var("START_AT")
        .unwrap_or("0".to_string())
        .parse()
        .expect("START_AT must be an integer");
    let run_until: Option<usize> = std::env::var("RUN_UNTIL")
        .ok()
        .map(|s| s.parse().expect("RUN_UNTIL must be an integer"));

    let early_exit = std::env::var("EARLY_EXIT").is_ok();

    // I want a lot of line context while working on this
    std::env::set_var("CONTEXT_LINE_COUNT", "1");

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
            let junk: HashMap<String, Value> =
                serde_json::from_str(f["junk_drawer"].as_str().unwrap()).unwrap();
            serde_json::from_value(junk["raw_frame"].clone()).unwrap()
        })
        .collect();

    let run_until = min(frames.len(), run_until.unwrap_or(frames.len()));

    let mut failures = Vec::new();

    let mut resolved = 0;
    for (i, frame) in frames
        .into_iter()
        .enumerate()
        .skip(start_at)
        .take(run_until - start_at)
    {
        let res = frame.resolve(0, &catalog).await.unwrap();

        println!("-------------------");
        println!("Resolving frame {}", i);
        println!("Input frame: {:?}", frame);
        println!("Resolved: {}", res);
        println!("-------------------");

        if res.resolved_name.is_some() {
            resolved += 1;
        } else if early_exit {
            break;
        } else {
            failures.push((frame.clone(), res, i));
        }
    }

    println!("Failures:");
    for failure in failures {
        println!("-------------------");
        println!(
            "Failed to resolve name for frame {}, {:?}",
            failure.2, failure.0
        );
        println!(
            "Failure: {}",
            failure.1.resolve_failure.as_deref().unwrap_or("unknown")
        )
    }

    println!(
        "Resolved {} out of {} frames",
        resolved,
        run_until - start_at
    );
}
