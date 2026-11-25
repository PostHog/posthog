#![cfg(all(feature = "ui-tests", not(target_family = "wasm")))]
use core::prelude::v1::test;
use gpui_test as gpui;
use gpui_test::*;
use meep_render::{
    gpui_kit,
    script_view::ScriptView,
    sdk::{HostError, ViewContext, ViewHost},
};
use serde_json::{Value, json};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

struct Host;
#[async_trait::async_trait]
impl ViewHost for Host {
    async fn request(&self, method: &str, params: Value) -> Result<Value, HostError> {
        assert_eq!(method, "sources.call");
        assert_eq!(params["source"], "counter");
        assert_eq!(params["arguments"]["count"], 0);
        Ok(json!(1))
    }
}

#[gpui::test]
fn counter_mounts_and_settles_with_only_the_embedding_host(cx: &mut TestAppContext) {
    cx.background_executor.allow_parking();
    cx.update(meep_render::init);
    let mut surface = None;
    let (_, cx) = cx.add_window_view(|window, cx| {
        let runtime = Arc::new(tokio::runtime::Runtime::new().unwrap());
        let context = ViewContext::new(
            "counter".into(),
            json!({}),
            Arc::new(Host),
            runtime,
            "1".into(),
            true,
        );
        let mounted =
            meep_render::mount(include_str!("../examples/counter.js"), window, cx, context)
                .unwrap();
        let entity = mounted.view.clone().downcast::<ScriptView>().unwrap();
        surface = Some(mounted);
        gpui_kit::base::Root::new(entity, window, cx)
    });
    let mounted = surface.unwrap();
    cx.update(|window, cx| mounted.command("increment", Value::Null, window, cx))
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        cx.run_until_parked();
        if cx.update(|_, cx| mounted.checkpoint(cx))["count"] == 1 {
            break;
        }
        assert!(
            Instant::now() < deadline,
            "host reply never reached the mounted script"
        );
        std::thread::sleep(Duration::from_millis(5));
    }
}
