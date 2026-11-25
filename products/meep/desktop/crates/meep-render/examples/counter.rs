//! A complete native host. Run with `cargo run --example counter`.
use meep_render::{
    gpui_kit::{self, *},
    sdk::{HostError, ViewContext, ViewHost},
};
use serde_json::{Value, json};
use std::sync::Arc;
struct CounterHost;
#[async_trait::async_trait]
impl ViewHost for CounterHost {
    async fn request(&self, method: &str, params: Value) -> Result<Value, HostError> {
        match (method, params["source"].as_str(), params["tool"].as_str()) {
            ("sources.call", Some("counter"), Some("add")) => Ok(json!(
                params["arguments"]["count"].as_u64().unwrap_or_default() + 1
            )),
            _ => Err(format!("Unknown operation {method}").into()),
        }
    }
}

fn main() {
    let runtime = Arc::new(tokio::runtime::Runtime::new().expect("runtime"));
    gpui_kit::application()
        .with_assets(gpui_kit::assets::AllAssets)
        .run(move |cx| {
            meep_render::init(cx);
            gpui_kit::open_window(WindowOptions::default(), cx, |window, cx| {
                let context = ViewContext::new(
                    "counter".into(),
                    json!({}),
                    Arc::new(CounterHost),
                    runtime,
                    "1".into(),
                    true,
                );
                meep_render::mount(include_str!("counter.js"), window, cx, context)
                    .expect("mount counter")
                    .view
                    .downcast::<meep_render::script_view::ScriptView>()
                    .expect("script entity")
            })
            .expect("open counter window");
            cx.activate(true);
        });
}
