use std::sync::Arc;

use common_types::ClickHouseEvent;
use cymbal::{
    app_context::AppContext,
    config::Config,
    handle_event,
    types::{OutputErrProps, Stacktrace},
};
use sqlx::Executor;

const EXCEPTION_DATA: &str = include_str!("./local_exception.json");

fn setup_env() {
    std::env::set_var("RUST_LOG", "info");
    std::env::set_var("KAFKA_CONSUMER_GROUP", "cymbal");
    std::env::set_var("KAFKA_CONSUMER_TOPIC", "exception_symbolification_events");
    std::env::set_var("OBJECT_STORAGE_BUCKET", "posthog");
    std::env::set_var("OBJECT_STORAGE_ACCESS_KEY_ID", "object_storage_root_user");
    std::env::set_var(
        "OBJECT_STORAGE_SECRET_ACCESS_KEY",
        "object_storage_root_password",
    );
    std::env::set_var("FRAME_CACHE_TTL_SECONDS", "0");
    std::env::set_var("ALLOW_INTERNAL_IPS", "true");
}

async fn reset(context: &AppContext) {
    context.pool.execute("delete from posthog_errortrackingstackframe; delete from posthog_errortrackingsymbolset;").await.unwrap();
}

#[tokio::main]
async fn main() {
    setup_env();
    let config = Config::init_with_defaults().unwrap();
    let context = Arc::new(AppContext::new(&config).await.unwrap());

    reset(&context).await;

    let count = 1000;

    let mut results = Vec::with_capacity(count);
    let mut elapsed = std::time::Duration::from_secs(0);
    for _ in 0..count {
        let start = std::time::Instant::now();
        let event: ClickHouseEvent = serde_json::from_str(EXCEPTION_DATA).unwrap();
        results.push(handle_event(context.clone(), event).await.unwrap());
        elapsed += start.elapsed();
        reset(&context).await;
    }

    for res in results {
        let props: OutputErrProps = serde_json::from_str(res.properties.as_ref().unwrap()).unwrap();
        let stack = props.exception_list[0].stack.as_ref().unwrap();
        let Stacktrace::Resolved { frames } = stack else {
            panic!("Expected a Resolved stacktrace");
        };
        for frame in frames {
            assert!(frame.resolved)
        }
    }

    println!(
        "Processed {} events in {:?}, {} events/s",
        count,
        elapsed,
        count as f64 / elapsed.as_secs_f64()
    );
}
